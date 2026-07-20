#include <WiFi.h>
#include <Firebase_ESP_Client.h>
#include <ModbusRTU.h>
#include <time.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>

  // ==================================================
  // LCD
  // ==================================================

LiquidCrystal_I2C lcd(0x27, 16, 2);

  // ==================================================
  // WIFI
  // ==================================================

#define WIFI_SSID "Nisrinaririi"
#define WIFI_PASSWORD "12345678"

  // ==================================================
  // FIREBASE
  // ==================================================

#define API_KEY "AIzaSyD90Jc1p9rXCiuUEtWHkPX7EWzpmfa_F70"

#define DATABASE_URL "https:

#define USER_EMAIL "pioneerspalm@gmail.com"

#define USER_PASSWORD "sawitmuda"

FirebaseData fbdo;
FirebaseAuth auth;
FirebaseConfig config;

  // ==================================================
  // PIN CONFIG
  // ==================================================

#define RXD2 16
#define TXD2 17
#define RE_DE 4

#define PH_PIN 34
#define SOIL_PIN 35

  // ==================================================
  // MODBUS
  // ==================================================

HardwareSerial RS485Serial(2);
ModbusRTU mb;

uint16_t ecData[1];

  // ==================================================
  // CALIBRATION
  // ==================================================

int AIR_VALUE = 2870;
int WATER_VALUE = 1500;

float PH7_VOLTAGE = 2.50;
float PH4_VOLTAGE = 3.00;

  // ==================================================
  // TIME
  // ==================================================

const char* ntpServer = "pool.ntp.org";

const long gmtOffset_sec = 25200;
const int daylightOffset_sec = 0;

  // ==================================================
  // CALLBACK
  // ==================================================

bool cb(Modbus::ResultCode event,
        uint16_t transactionId,
        void* data) {

  return true;
}

  // ==================================================
  // READ PH
  // ==================================================

float readPH()
{
    long total = 0;

    for(int i = 0; i < 30; i++)
    {
        total += analogRead(PH_PIN);
        delay(10);
    }

    float adc = total / 30.0;
    float voltage = adc * (3.25 / 4095.0);

    if(voltage < 0.2 || voltage > 3.2)
    {
        return 0;
    }

    float ph =
       (0.0 + 7) + ((PH7_VOLTAGE - voltage) /
        (PH4_VOLTAGE - PH7_VOLTAGE)) * 3;

    if(ph < 0) ph = 0;
    if(ph > 14) ph = 14;

    return ph;
}

  // ==================================================
  // READ MOISTURE
  // ==================================================

float readMoisture() {

  long total = 0;

  for (int i = 0; i < 30; i++) {

    total += analogRead(SOIL_PIN);

    delay(10);
  }

  int adc = total / 30.0;

  float moisture = map(
                      adc,
                      AIR_VALUE,
                      WATER_VALUE,
                      0,
                      100
                    );

  if (moisture > 100) moisture = 100;

  if (moisture < 0) moisture = 0;
    Serial.print("Soil ADC = ");
  Serial.println(adc);

  return moisture;
}

  // ==================================================
  // TIMESTAMP
  // ==================================================

String getTimeStamp() {

  struct tm timeinfo;

  if (!getLocalTime(&timeinfo)) {

    return "0";
  }

  char timeStringBuff[30];

  strftime(
    timeStringBuff,
    sizeof(timeStringBuff),
    "%Y-%m-%d_%H-%M-%S",
    &timeinfo
  );

  return String(timeStringBuff);
}

  // ==================================================
  // WIFI CONNECT
  // ==================================================

void connectWiFi() {

  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("Connecting WiFi");

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  while (WiFi.status() != WL_CONNECTED) {

    delay(500);

    Serial.print(".");
  }

  Serial.println();

  Serial.println("WiFi Connected");

  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("WiFi Connected");

  delay(1000);
}

  // ==================================================
  // SETUP
  // ==================================================

void setup() {

  Serial.begin(115200);

  analogReadResolution(12);

  // =================================================
  // LCD
  // =================================================

  lcd.init();

  lcd.backlight();

  lcd.setCursor(0, 0);

  lcd.print("Soil Monitoring");

  delay(2000);

  // =================================================
  // RS485
  // =================================================

  pinMode(RE_DE, OUTPUT);

  digitalWrite(RE_DE, LOW);

  RS485Serial.begin(
    9600,
    SERIAL_8N1,
    RXD2,
    TXD2
  );

  mb.begin(&RS485Serial, RE_DE);

  mb.master();

  // =================================================
  // WIFI
  // =================================================

  connectWiFi();

  // =================================================
  // NTP
  // =================================================

  configTime(
    gmtOffset_sec,
    daylightOffset_sec,
    ntpServer
  );

  // =================================================
  // FIREBASE
  // =================================================

  lcd.clear();

  lcd.setCursor(0, 0);

  lcd.print("Firebase Init");

  config.api_key = API_KEY;

  config.database_url = DATABASE_URL;

  auth.user.email = USER_EMAIL;

  auth.user.password = USER_PASSWORD;

  Firebase.reconnectWiFi(true);

  Firebase.begin(&config, &auth);

  while (!Firebase.ready()) {

    delay(500);

    Serial.print(".");
  }

  lcd.clear();

  lcd.setCursor(0, 0);

  lcd.print("Firebase Ready");

  delay(2000);
}

  // =================================================
  // LOOP
  // =================================================

void loop() {

  // =================================================
  // CHECK WIFI
  // =================================================

  if (WiFi.status() != WL_CONNECTED) {

    connectWiFi();
  }

  // =================================================
  // READ EC
  // =================================================

  if (!mb.slave()) {

    mb.readHreg(
      1,
      7,
      ecData,
      1,
      cb
    );
  }

  mb.task();

const int EC_BASELINE = 2020;

float ec = ((ecData[0] + 0) - EC_BASELINE) / 1000.0;

if (ec < 0)
    ec = 0;

  // =================================================
  // READ SENSOR
  // =================================================

  float ph = readPH();

  float moisture = readMoisture();

  // =================================================
  // TIMESTAMP
  // =================================================

  String timestamp = getTimeStamp();

  // =================================================
  // FIREBASE PATH
  // =================================================

  String realtimePath =
    "/soil_monitoring/realtime";

  String historyPath =
    "/soil_monitoring/history/" + timestamp;

  // =================================================
  // SEND REALTIME DATA
  // =================================================

  Firebase.RTDB.setFloat(
    &fbdo,
    realtimePath + "/ec",
    ec
  );

  Firebase.RTDB.setFloat(
    &fbdo,
    realtimePath + "/ph",
    ph
  );

  Firebase.RTDB.setFloat(
    &fbdo,
    realtimePath + "/moisture",
    moisture
  );

  Firebase.RTDB.setString(
    &fbdo,
    realtimePath + "/timestamp",
    timestamp
  );

  // =================================================
  // SEND HISTORY
  // =================================================

  Firebase.RTDB.setFloat(
    &fbdo,
    historyPath + "/ec",
    ec
  );

  Firebase.RTDB.setFloat(
    &fbdo,
    historyPath + "/ph",
    ph
  );

  Firebase.RTDB.setFloat(
    &fbdo,
    historyPath + "/moisture",
    moisture
  ); 

  // =================================================
  // SERIAL MONITOR
  // =================================================

  Serial.println("====================");

  Serial.print("EC : ");
  Serial.println(ec);

  Serial.print("pH : ");
  Serial.println(ph);

  Serial.print("Moisture : ");
  Serial.println(moisture);

  Serial.print("Raw EC : ");
  Serial.println(ecData[0]);

  // =================================================
  // LCD DISPLAY
  // =================================================

  lcd.clear();

  lcd.setCursor(0, 0);

  lcd.print("EC:");
  lcd.print(ec, 2);

  lcd.print(" pH:");
  lcd.print(ph, 1);

  lcd.setCursor(0, 1);

  lcd.print("M:");
  lcd.print(moisture, 0);

  lcd.print("% ");

  delay(5000);
}
