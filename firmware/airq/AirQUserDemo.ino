#include <Arduino.h>
#include <Wire.h>
#include <LittleFS.h>
#include <M5Unified.h>
#include <lgfx/v1/panel/Panel_GDEW0154D67.hpp>
#include <WiFi.h>
#include <esp_sntp.h>

#include "I2C_BM8563.h"
#include <SensirionI2CScd4x.h>
#include <SensirionI2CSen5x.h>
#include <Preferences.h>

#include "SensePlatform.hpp"
#include "config.h"
#include "DataBase.hpp"
#include "Sensor.hpp"


// ═══════════════════════════════════════════
// E-INK DISPLAY
// ═══════════════════════════════════════════
class AirQ_GFX : public lgfx::LGFX_Device {
    lgfx::Panel_GDEW0154D67 _panel_instance;
    lgfx::Bus_SPI           _spi_bus_instance;
public:
    AirQ_GFX(void) {
        {
            auto cfg = _spi_bus_instance.config();
            cfg.pin_mosi   = EPD_MOSI;
            cfg.pin_miso   = EPD_MISO;
            cfg.pin_sclk   = EPD_SCLK;
            cfg.pin_dc     = EPD_DC;
            cfg.freq_write = EPD_FREQ;
            _spi_bus_instance.config(cfg);
            _panel_instance.setBus(&_spi_bus_instance);
        }
        {
            auto cfg = _panel_instance.config();
            cfg.invert       = false;
            cfg.pin_cs       = EPD_CS;
            cfg.pin_rst      = EPD_RST;
            cfg.pin_busy     = EPD_BUSY;
            cfg.panel_width  = 200;
            cfg.panel_height = 200;
            cfg.offset_x     = 0;
            cfg.offset_y     = 0;
            _panel_instance.config(cfg);
        }
        setPanel(&_panel_instance);
    }
    bool begin(void) { return init_impl(true, false); };
};


// ═══════════════════════════════════════════
// GLOBALS
// ═══════════════════════════════════════════
AirQ_GFX lcd;

SensirionI2CScd4x scd4x;
SensirionI2CSen5x sen5x;
I2C_BM8563 bm8563(I2C_BM8563_DEFAULT_ADDRESS, Wire);
Sensor sensor(scd4x, sen5x, bm8563);

SensePlatform sensePlatform;
Preferences preferences;
uint32_t successCounter = 0;
uint32_t failCounter = 0;


// ═══════════════════════════════════════════
// QR CODE
// ═══════════════════════════════════════════
void showDashboardQR() {
    String url = db.sense.dashboardUrl;
    if (url.length() == 0) return;
    lcd.wakeup();
    lcd.clear(TFT_WHITE);
    lcd.waitDisplay();
    lcd.qrcode(url, 25, 25, 150);
    lcd.waitDisplay();
}


// ═══════════════════════════════════════════
// WIFI
// ═══════════════════════════════════════════
void onWiFiGotIP(WiFiEvent_t event, WiFiEventInfo_t info) {
    log_i("WiFi connected — IP: %s",
        IPAddress(info.got_ip.ip_info.ip.addr).toString().c_str());
}

void onWiFiDisconnected(WiFiEvent_t event, WiFiEventInfo_t info) {
    log_w("WiFi disconnected — reason: %d", info.wifi_sta_disconnected.reason);
}

void wifiSetup() {
    WiFi.disconnect();
    delay(500);
    WiFi.mode(WIFI_STA);
    WiFi.onEvent(onWiFiGotIP, WiFiEvent_t::ARDUINO_EVENT_WIFI_STA_GOT_IP);
    WiFi.onEvent(onWiFiDisconnected, WiFiEvent_t::ARDUINO_EVENT_WIFI_STA_DISCONNECTED);

    if (db.wifi.ssid.length() == 0) {
        log_w("WiFi SSID not configured");
    } else {
        log_i("WiFi: connecting to %s", db.wifi.ssid.c_str());
        WiFi.begin(db.wifi.ssid.c_str(), db.wifi.password.c_str());
    }
}


// ═══════════════════════════════════════════
// NTP
// ═══════════════════════════════════════════
void TZConvert(const String &old, String &out) {
    out = old;
    if (out.indexOf("-") != -1) {
        out.replace("-", "+");
    } else if (out.indexOf("+") != -1) {
        out.replace("+", "-");
    }
}

void timeavailable(struct timeval *t) {
    log_i("NTP time sync");
    struct tm timeinfo;
    if (getLocalTime(&timeinfo, 1000)) {
        I2C_BM8563_TimeTypeDef ts;
        ts.hours = timeinfo.tm_hour;
        ts.minutes = timeinfo.tm_min;
        ts.seconds = timeinfo.tm_sec;
        bm8563.setTime(&ts);

        I2C_BM8563_DateTypeDef ds;
        ds.year = 1900 + timeinfo.tm_year;
        ds.month = timeinfo.tm_mon + 1;
        ds.date = timeinfo.tm_mday;
        ds.weekDay = timeinfo.tm_wday;
        bm8563.setDate(&ds);
    }
}


// ═══════════════════════════════════════════
// SENSOR READING + UPLOAD
// ═══════════════════════════════════════════
void readAndUpload() {
    log_i("Reading sensors");
    sensor.getSCD40MeasurementResult();
    sensor.getSEN55MeasurementResult();
    sensor.getBatteryVoltageRaw();

    log_i("PM2.5: %.1f  CO2: %d  Temp: %.1f  Hum: %.1f  Bat: %dmV",
        sensor.sen55.massConcentrationPm2p5,
        sensor.scd40.co2,
        sensor.sen55.ambientTemperature,
        sensor.sen55.ambientHumidity,
        sensor.battery.raw);

    if (!WiFi.isConnected() || db.sense.endpoint.length() == 0) {
        log_w("WiFi not connected or endpoint not configured — skipping upload");
        return;
    }

    sensePlatform.setEndpoint(db.sense.endpoint);
    sensePlatform.setApiKey(db.sense.apiKey);
    sensePlatform.setDeviceId(db.sense.deviceId);
    if (db.sense.latitude != 0 || db.sense.longitude != 0) {
        sensePlatform.setLocation(
            db.sense.latitude, db.sense.longitude,
            db.sense.locationLabel, db.sense.countryCode
        );
    }

    for (int attempt = 1; attempt <= EZDATA_UPLOAD_RETRY_COUNT; attempt++) {
        log_i("Uploading (attempt %d/%d)", attempt, EZDATA_UPLOAD_RETRY_COUNT);

        if (sensePlatform.upload(
                sensor.sen55.massConcentrationPm1p0,
                sensor.sen55.massConcentrationPm2p5,
                sensor.sen55.massConcentrationPm4p0,
                sensor.sen55.massConcentrationPm10p0,
                sensor.sen55.ambientTemperature,
                sensor.sen55.ambientHumidity,
                sensor.sen55.vocIndex,
                sensor.sen55.noxIndex,
                sensor.scd40.co2,
                sensor.scd40.temperature,
                sensor.scd40.humidity,
                sensor.battery.raw)) {
            successCounter++;
            preferences.putUInt("OK", successCounter);
            log_i("Upload OK:%d", successCounter);
            return;
        }

        failCounter++;
        preferences.putUInt("NG", failCounter);
        log_w("Upload NG:%d", failCounter);
    }

    log_w("All upload retries exhausted");
}


// ═══════════════════════════════════════════
// SETUP
// ═══════════════════════════════════════════
void setup() {
    Serial.begin(115200);
    log_i("AirQ Sense Platform — v%s — %s %s", APP_VERSION, __DATE__, __TIME__);

    // Power
    pinMode(POWER_HOLD, OUTPUT);
    digitalWrite(POWER_HOLD, HIGH);
    pinMode(SEN55_POWER_EN, OUTPUT);
    digitalWrite(SEN55_POWER_EN, LOW);

    // Filesystem + config
    FILESYSTEM.begin();
    db.loadFromFile();

    // NVS
    preferences.begin("airq", false);
    successCounter = preferences.getUInt("OK", 0);
    failCounter = preferences.getUInt("NG", 0);

    // E-ink — draw QR once on cold boot, then sleep display
    lcd.begin();
    lcd.setEpdMode(epd_mode_t::epd_fastest);
    esp_sleep_wakeup_cause_t wake = esp_sleep_get_wakeup_cause();
    if (wake != ESP_SLEEP_WAKEUP_TIMER) {
        showDashboardQR();
    }
    lcd.sleep();

    // WiFi (STA only)
    wifiSetup();

    // I2C + sensors
    Wire.begin(I2C1_SDA_PIN, I2C1_SCL_PIN);

    bm8563.begin();
    bm8563.clearIRQ();

    // NTP
    esp_sntp_servermode_dhcp(1);
    String tz;
    TZConvert(db.ntp.tz, tz);
    configTzTime(tz.c_str(),
        db.ntp.ntpServer0.c_str(),
        db.ntp.ntpServer1.c_str(),
        "pool.ntp.org");
    sntp_set_time_sync_notification_cb(timeavailable);

    // SCD40 (CO2)
    char err[256];
    scd4x.begin(Wire);
    uint16_t error = scd4x.stopPeriodicMeasurement();
    if (error) { errorToString(error, err, 256); log_w("SCD40 stop: %s", err); }
    error = scd4x.startPeriodicMeasurement();
    if (error) { errorToString(error, err, 256); log_w("SCD40 start: %s", err); }

    // SEN55 (PM, VOC, NOx, temp, humidity)
    sen5x.begin(Wire);
    error = sen5x.deviceReset();
    if (error) { errorToString(error, err, 256); log_w("SEN55 reset: %s", err); }
    sen5x.setTemperatureOffsetSimple(0.0);
    error = sen5x.startMeasurement();
    if (error) { errorToString(error, err, 256); log_w("SEN55 start: %s", err); }

    // Wait for first SCD40 reading
    log_i("Waiting for sensors...");
    bool ready = false;
    do {
        error = scd4x.getDataReadyFlag(ready);
        if (error) { errorToString(error, err, 256); log_w("SCD40 ready: %s", err); break; }
    } while (!ready);

    log_i("Setup complete — OK:%d NG:%d", successCounter, failCounter);
}


// ═══════════════════════════════════════════
// POWER OFF (battery) / DELAY (USB)
// ═══════════════════════════════════════════
void sleepUntilNextReading() {
    // Set RTC alarm to wake the device
    bm8563.clearIRQ();
    bm8563.SetAlarmIRQ(db.rtc.sleepInterval);

    log_i("Powering off — next wake in %d seconds", db.rtc.sleepInterval);
    delay(10);

    // Cut power — on battery this kills the device immediately.
    // The RTC alarm will re-trigger the power latch to boot.
    digitalWrite(POWER_HOLD, LOW);

    // If we're still alive, USB is providing power.
    // Fall back to delay-based loop.
    delay(100);
    digitalWrite(POWER_HOLD, HIGH); // re-latch power
    log_i("USB powered — using delay loop (%d seconds)", db.rtc.sleepInterval);
    delay(db.rtc.sleepInterval * 1000);
}


// ═══════════════════════════════════════════
// MAIN LOOP
// ═══════════════════════════════════════════
void loop() {
    readAndUpload();
    sleepUntilNextReading();
}
