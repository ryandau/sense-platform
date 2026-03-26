#pragma once

#include <WString.h>


class DataBase {
public:
    DataBase() {}
    ~DataBase() {}

    void saveToFile();
    void dump();
    void loadFromFile();

public:
    bool factoryState;
    struct {
        String ssid;
        String password;
    } wifi;
    struct {
        int sleepInterval;
    } rtc;
    struct {
        String ntpServer0;
        String ntpServer1;
        String tz;
    } ntp;
    struct {
        String endpoint;
        String apiKey;
        String deviceId;
        float latitude;
        float longitude;
        String locationLabel;
        String countryCode;
        String dashboardUrl;
    } sense;
    struct {
        bool onoff;
    } buzzer;

    String nickname;

    bool isFactoryTestMode = false;

    // not persisted
    bool isConfigState;
    bool pskStatus = true;
};


extern DataBase db;
