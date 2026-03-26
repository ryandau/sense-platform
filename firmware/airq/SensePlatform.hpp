#pragma once

#include <WString.h>
#include <HTTPClient.h>
#include <cJSON.h>

/**
 * SensePlatform — drop-in replacement for EzData.
 *
 * Posts sensor readings to the Sense Platform /ingest endpoint.
 * Configured via the device's web UI (stored in /db.json).
 */
class SensePlatform {
public:
    SensePlatform();

    void setEndpoint(const String &url);
    void setApiKey(const String &key);
    void setDeviceId(const String &id);
    void setTypeSlug(const String &slug);
    void setLocation(float latitude, float longitude,
                     const String &locationLabel = "",
                     const String &countryCode = "");

    /**
     * Upload a reading to the Sense Platform.
     * Returns true on HTTP 200/201 with status "accepted".
     */
    bool upload(float pm1_0, float pm2_5, float pm4_0, float pm10_0,
                float sen_temperature, float sen_humidity,
                float voc_index, float nox_index,
                uint16_t co2, float scd_temperature, float scd_humidity,
                uint32_t battery_mv);

private:
    String _endpoint;   // e.g. "https://xxxxxxx.execute-api.ap-southeast-2.amazonaws.com/v1"
    String _apiKey;
    String _deviceId;   // e.g. "airq-001"
    String _typeSlug;   // e.g. "air_quality"
    float  _latitude;
    float  _longitude;
    String _locationLabel;
    String _countryCode;
    bool   _hasLocation;
};
