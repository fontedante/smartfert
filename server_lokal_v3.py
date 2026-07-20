import time
import requests
import joblib
import pandas as pd

# ======================================================================
# KONFIGURASI SMART SCHEDULING (AGRONOMICALLY CALIBRATED)
# ======================================================================
MIN_HARI_SEJAK_PEMUPUKAN = 100    # Sawit baru boleh dipupuk lagi setelah ~3.5 bulan
EC_THRESHOLD_CRITICAL = 0.08      # Batas kelaparan
MIN_MOISTURE_UNTUK_PUPUK = 25.0   # Pengaman: Jangan memupuk saat kekeringan ekstrem

# URL Firebase (Rest API)
FIREBASE_URL = "https://pioneerspalm-78855-default-rtdb.firebaseio.com/soil_monitoring/realtime.json"

# Koordinat Lokasi: Kasomalang Wetan, Jalancagak, Kab. Subang
LATITUDE = -6.6839
LONGITUDE = 107.7253

# Data Cuaca URL
OPEN_METEO_URL = (
    f"https://api.open-meteo.com/v1/forecast"
    f"?latitude={LATITUDE}&longitude={LONGITUDE}"
    f"&current=precipitation,weather_code,temperature_2m,relative_humidity_2m"
    f"&daily=precipitation_sum,precipitation_probability_max,weather_code"
    f"&timezone=Asia/Jakarta"
    f"&forecast_days=3"
)

WEATHER_DESCRIPTIONS = {
    0: "Cerah ☀️", 1: "Sebagian Cerah 🌤️", 2: "Berawan Sebagian ⛅",
    3: "Mendung ☁️", 45: "Berkabut 🌫️", 48: "Kabut Tebal 🌫️",
    51: "Gerimis Ringan 🌦️", 53: "Gerimis Sedang 🌦️", 55: "Gerimis Lebat 🌧️",
    61: "Hujan Ringan 🌧️", 63: "Hujan Sedang 🌧️", 65: "Hujan Lebat 🌧️",
    80: "Hujan Sebentar 🌦️", 81: "Hujan Sedang 🌦️", 82: "Hujan Lebat ⛈️",
    95: "Badai Petir ⛈️", 96: "Badai + Hujan Es ⛈️", 99: "Badai Besar ⛈️",
}

def get_weather_data():
    try:
        resp = requests.get(OPEN_METEO_URL, timeout=10)
        resp.raise_for_status()
        weather = resp.json()

        current = weather.get('current', {})
        daily = weather.get('daily', {})

        rainfall_mm = current.get('precipitation', 0.0)
        weather_code = current.get('weather_code', 0)
        temperature = current.get('temperature_2m', None)
        humidity = current.get('relative_humidity_2m', None)

        daily_precip = daily.get('precipitation_sum', [0.0])
        daily_forecast_mm = daily_precip[0] if len(daily_precip) > 0 else 0.0
        hujan_3hari_kedepan = sum(daily_precip) if len(daily_precip) > 0 else 0.0

        probs = daily.get('precipitation_probability_max', [0])
        rain_probability = probs[0] if len(probs) > 0 else 0

        weather_desc = WEATHER_DESCRIPTIONS.get(weather_code, f"Kode {weather_code}")
        
        daily_weather_codes = daily.get('weather_code', [])
        daily_weather_desc = [WEATHER_DESCRIPTIONS.get(c, f"Kode {c}") for c in daily_weather_codes]
        weather_desc_3days = " | ".join(daily_weather_desc) if daily_weather_desc else "Tidak tersedia"

        return {
            'rainfall_mm': float(rainfall_mm),
            'hujan_3hari_kedepan': float(hujan_3hari_kedepan),
            'weather_desc': weather_desc,
            'weather_desc_3days': weather_desc_3days,
            'temperature': temperature,
            'humidity': humidity,
            'daily_forecast_mm': float(daily_forecast_mm),
            'rain_probability': rain_probability,
        }
    except Exception as e:
        print(f"    [!] Gagal mengambil data cuaca: {e}")
        return None

# 1. Load Otak AI TERBARU (XGBoost / Extreme Gradient Boosting)
try:
    import joblib
    model = joblib.load('model_xgb_smartfert.pkl')
    print("=" * 60)
    print("   SmartFert Backend Lokal — AI (XGBoost) Aktif")
    print("=" * 60)
    print(f"   Lokasi Cuaca : Kasomalang Wetan, Jalancagak, Kab. Subang")
    print(f"   Fitur ML     : ec, moisture, ph, hari sejak terakhir pemupukan")
    print(f"   Dosis Range  : ~3.500g hingga 4.250g (Ter-Update)")
    print("=" * 60)
    print("Menunggu data sensor baru dari Firebase pioneerspalm...\n")
except Exception as e:
    print(f"Gagal memuat model: {e}")
    exit()

last_timestamp = None

# 2. Loop tanpa henti (sebagai Server)
while True:
    try:
        response = requests.get(FIREBASE_URL)
        data = response.json()

        if data and 'timestamp' in data:
            current_timestamp = data['timestamp']

            # Jika data baru masuk dari ESP32
            if current_timestamp != last_timestamp:
                print(f"[+] Data baru masuk pada: {current_timestamp}")
                print(f"    Sensor Mentah -> pH: {data.get('ph')}, Moisture: {data.get('moisture')}, EC: {data.get('ec')}")

                # Ambil Cuaca
                weather = get_weather_data()
                if weather:
                    hujan_3hari = weather['hujan_3hari_kedepan']
                    print(f"    Cuaca Saat Ini -> {weather['weather_desc']} | {weather['temperature']}°C")
                else:
                    hujan_3hari = 0.0
                    print(f"    Cuaca          -> Tidak tersedia")

                # Mapping Fitur AI 
                # (Sesuai dengan training: ec, moisture, ph, hari sejak terakhir pemupukan)
                days_since = int(data.get('days_since_last_fert', 104))
                input_data = pd.DataFrame([{
                    'ec': float(data.get('ec', 1.0)),
                    'moisture': float(data.get('moisture', 50.0)),
                    'ph': float(data.get('ph', 5.5)),
                    'hari sejak terakhir pemupukan': days_since,
                    'dosis_historis_gram': float(data.get('dosis_historis_gram', 3800))
                }])

                # Proses prediksi AI (Langsung tanpa StandardScaler karena berbasis Tree)
                prediction = model.predict(input_data)
                dosis = round(float(prediction[0]), 2)
                
                # Prevent negative doses
                if dosis < 0:
                    dosis = 0.0

                print(f"    Prediksi AI   -> Rekomendasi Dosis: {dosis} gram")

                # ======================================================================
                # LOGIKA EVALUASI JADWAL PINTAR (BATAS BARU: pH 4.0-6.5 & EC 0.2-1.2)
                # ======================================================================
                ec_current = float(data.get('ec', 0.5))
                moisture_current = float(data.get('moisture', 50.0))
                ph_current = float(data.get('ph', 5.5))
                hari_terakhir = days_since

                # 1. Tentukan target dasar interval (SOP Perusahaan)
                if ec_current > 1.20:
                    target_days = None # Salinitas bahaya, tangguhkan
                else:
                    target_days = 180 # Standar interval serentak perkebunan (6 bulan)

                estimasi_sisa_hari = float('inf') if target_days is None else int(target_days - hari_terakhir)
                status_kelayakan = "BERJALAN"
                pesan_tambahan = "Kondisi tanah optimal."

                # 2. Dynamic Delay: Modifikasi jika waktu pemupukan sudah dekat (<= 3 hari)
                if estimasi_sisa_hari <= 3 and target_days is not None:
                    list_pesan_tunda = []
                    
                    if weather:
                        curah_hujan_mm = weather.get('daily_forecast_mm', 0)
                        peluang_hujan_persen = weather.get('precipitation_probability_max', 0)
                        hujan_3hari = weather.get('hujan_3hari_kedepan', 0)
                        
                        # Cek Hujan Harian & Probabilitas
                        if curah_hujan_mm > 20.0 and peluang_hujan_persen > 80:
                            status_kelayakan = "DITUNDA"
                            list_pesan_tunda.append(f"Hujan hari ini {curah_hujan_mm}mm (Peluang {peluang_hujan_persen}%)")
                            
                        # Cek Akumulasi Hujan 3 Hari
                        elif hujan_3hari > 50.0:
                            status_kelayakan = "DITUNDA"
                            list_pesan_tunda.append(f"Akumulasi hujan 3 hari ekstrem ({hujan_3hari}mm)")
                    
                    # Cek Kelembaban Tanah
                    if moisture_current < 30.0:
                        status_kelayakan = "DITUNDA"
                        list_pesan_tunda.append("Tanah terlalu kering (Moisture < 30%)")
                        
                    # Cek pH Kritis
                    if ph_current < 4.0:
                        status_kelayakan = "DITUNDA"
                        list_pesan_tunda.append("pH < 4.0 (Asam Ekstrem). Wajib Dolomit")

                    # Terapkan penundaan jika ada kendala
                    if status_kelayakan == "DITUNDA":
                        estimasi_sisa_hari = 5
                        pesan_tambahan = "DITUNDA: " + ", ".join(list_pesan_tunda)

                # 3. Penentuan Akhir Output
                estimasi_sisa_hari = max(0, estimasi_sisa_hari)

                if ec_current > 1.20:
                    status_kelayakan = "DITANGGUHKAN"
                    teks_estimasi = "Ditangguhkan"
                    pesan_alarm = f"DITANGGUHKAN: Bahaya salinitas tinggi (EC: {ec_current} dS/m > 1.2 dS/m). Lakukan flushing!"
                    print(f"    [WARN] {pesan_alarm}")
                    estimasi_sisa_hari = -1 # Gunakan -1 sebagai kode suspend di frontend
                elif estimasi_sisa_hari == 0:
                    status_kelayakan = "BERJALAN"
                    teks_estimasi = "Hari Ini!"
                    if ec_current < 0.2:
                        pesan_tambahan = "Catatan: Hara tanah sangat rendah (EC < 0.2). Dosis AI menyesuaikan."
                    pesan_alarm = f"Waktunya Memupuk! Rekomendasi ML: {dosis}g. {pesan_tambahan}"
                    print(f"    [ALARM] {pesan_alarm}")
                else:
                    teks_estimasi = f"{estimasi_sisa_hari} Hari"
                    pesan_alarm = f"Estimasi Pemupukan Berikutnya: {estimasi_sisa_hari} Hari. {pesan_tambahan}"
                    print(f"    [INFO] {pesan_alarm}")

                # Kirim hasil AI ke Firebase
                update_data = {
                    "ml_fertilizer_dose_grams": dosis,
                    "Estimasi Pemupukan Berikutnya": teks_estimasi,
                    "weather_hujan_3hari_mm": hujan_3hari,
                    "weather_description": weather['weather_desc'] if weather else "Tidak tersedia",
                    "weather_description_3days": weather['weather_desc_3days'] if weather else "Tidak tersedia",
                    "weather_daily_forecast_mm": weather['daily_forecast_mm'] if weather else 0,
                    "weather_rain_probability": weather['rain_probability'] if weather else 0,
                    
                    # === CLEANUP FIELD LAMA (Hapus dari database) ===
                    "estimasi_sisa_hari_pemupukan": None,
                    "pesan_peringatan_agronomi": None,
                    "fertilizer_alert_message": None,
                    "is_time_to_fertilize": None,
                    "ml_ideal_interval_days": None,
                }
                requests.patch(FIREBASE_URL, json=update_data)
                print("    [V] Berhasil menulis prediksi + data cuaca ke database!\n")

                last_timestamp = current_timestamp

        time.sleep(3)

    except Exception as e:
        print(f"Terjadi gangguan koneksi: {e}")
        time.sleep(5)
