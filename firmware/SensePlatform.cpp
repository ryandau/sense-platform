#include "SensePlatform.hpp"
#include <Arduino.h>

static const char *TAG = "SensePlatform";

SensePlatform::SensePlatform()
    : _typeSlug("air_quality"),
      _latitude(0),
      _longitude(0),
      _hasLocation(false) {}

void SensePlatform::setEndpoint(const String &url) { _endpoint = url; }
void SensePlatform::setApiKey(const String &key)    { _apiKey = key; }
void SensePlatform::setDeviceId(const String &id)   { _deviceId = id; }
void SensePlatform::setTypeSlug(const String &slug)  { _typeSlug = slug; }

void SensePlatform::setLocation(float latitude, float longitude,
                                const String &locationLabel,
                                const String &countryCode) {
    _latitude      = latitude;
    _longitude     = longitude;
    _locationLabel = locationLabel;
    _countryCode   = countryCode;
    _hasLocation   = true;
}

bool SensePlatform::upload(float pm1_0, float pm2_5, float pm4_0, float pm10_0,
                           float sen_temperature, float sen_humidity,
                           float voc_index, float nox_index,
                           uint16_t co2, float scd_temperature,
                           float scd_humidity) {
    if (_endpoint.isEmpty() || _apiKey.isEmpty() || _deviceId.isEmpty()) {
        log_e("SensePlatform not configured (endpoint/apiKey/deviceId missing)");
        return false;
    }

    // Build JSON payload matching Sense Platform /ingest schema
    cJSON *root = cJSON_CreateObject();
    cJSON *data = cJSON_CreateObject();
    if (!root || !data) {
        log_e("cJSON allocation failed");
        cJSON_Delete(root);
        cJSON_Delete(data);
        return false;
    }

    cJSON_AddStringToObject(root, "device_id", _deviceId.c_str());
    cJSON_AddStringToObject(root, "type_slug", _typeSlug.c_str());

    // Sensor data — flat key structure matching air_quality device type
    cJSON_AddNumberToObject(data, "pm1_0", pm1_0);
    cJSON_AddNumberToObject(data, "pm2_5", pm2_5);
    cJSON_AddNumberToObject(data, "pm4_0", pm4_0);
    cJSON_AddNumberToObject(data, "pm10_0", pm10_0);
    cJSON_AddNumberToObject(data, "temperature", sen_temperature);
    cJSON_AddNumberToObject(data, "humidity", sen_humidity);
    cJSON_AddNumberToObject(data, "voc_index", voc_index);
    cJSON_AddNumberToObject(data, "nox_index", nox_index);
    cJSON_AddNumberToObject(data, "co2", (double)co2);
    cJSON_AddNumberToObject(data, "scd_temperature", scd_temperature);
    cJSON_AddNumberToObject(data, "scd_humidity", scd_humidity);

    cJSON_AddItemToObject(root, "data", data);

    if (_hasLocation) {
        cJSON_AddNumberToObject(root, "latitude", _latitude);
        cJSON_AddNumberToObject(root, "longitude", _longitude);
        if (!_locationLabel.isEmpty())
            cJSON_AddStringToObject(root, "location_label", _locationLabel.c_str());
        if (!_countryCode.isEmpty())
            cJSON_AddStringToObject(root, "country_code", _countryCode.c_str());
    }

    char *payload = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    if (!payload) {
        log_e("cJSON print failed");
        return false;
    }

    // POST to /ingest
    String url = _endpoint;
    if (!url.endsWith("/")) url += "/";
    url += "ingest";

    HTTPClient http;
    http.begin(url);
    http.addHeader("Content-Type", "application/json");
    http.addHeader("X-API-Key", _apiKey);
    http.setTimeout(10000);

    log_d("POST %s", url.c_str());
    int httpCode = http.POST(payload);
    free(payload);

    bool success = false;
    if (httpCode == 200 || httpCode == 201) {
        String response = http.getString();
        log_d("Response: %s", response.c_str());

        cJSON *rsp = cJSON_Parse(response.c_str());
        if (rsp) {
            cJSON *status = cJSON_GetObjectItem(rsp, "status");
            if (status && cJSON_IsString(status) &&
                strcmp(status->valuestring, "accepted") == 0) {
                success = true;
            }
            cJSON_Delete(rsp);
        }
    } else {
        log_e("HTTP %d: %s", httpCode, http.getString().c_str());
    }

    http.end();
    return success;
}
