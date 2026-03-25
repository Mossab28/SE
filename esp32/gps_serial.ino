#include <TinyGPS++.h>
#include <HardwareSerial.h>

TinyGPSPlus gps;
HardwareSerial SerialGPS(1);
unsigned long lastSend = 0;

void setup() {
  Serial.begin(115200);
  SerialGPS.begin(9600, SERIAL_8N1, 16, 17);
  Serial.println("GPS_SERIAL_READY");
}

void loop() {
  while (SerialGPS.available() > 0) {
    gps.encode(SerialGPS.read());
  }

  if (gps.location.isUpdated()) {
    Serial.print("{\"gps_lat\":");
    Serial.print(gps.location.lat(), 6);
    Serial.print(",\"gps_lng\":");
    Serial.print(gps.location.lng(), 6);
    Serial.print(",\"gps_speed_kmh\":");
    Serial.print(gps.speed.kmph(), 1);
    Serial.print(",\"gps_satellites\":");
    Serial.print(gps.satellites.value());
    Serial.println("}");
    lastSend = millis();
  } else if (millis() - lastSend >= 1000) {
    Serial.println("{\"gps_lat\":null,\"gps_lng\":null,\"gps_speed_kmh\":null,\"gps_satellites\":0}");
    lastSend = millis();
  }
}
