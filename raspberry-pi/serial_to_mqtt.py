"""Read ESP32 text GPS data from USB serial, publish as JSON to MQTT."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
import serial
from dotenv import load_dotenv

load_dotenv()

SERIAL_PORT = os.getenv("SERIAL_PORT", "/dev/ttyUSB0")
SERIAL_BAUD = int(os.getenv("SERIAL_BAUD", "115200"))
MQTT_HOST = os.getenv("MQTT_HOST", "212.227.88.180")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "nereides/telemetry")


def connect_serial() -> serial.Serial:
    """Connect to serial port with retry."""
    while True:
        try:
            ser = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=2)
            print(f"Serie connectee sur {SERIAL_PORT}")
            return ser
        except serial.SerialException:
            print(f"Port {SERIAL_PORT} indisponible, retry dans 2s...")
            time.sleep(2)


def connect_mqtt() -> mqtt.Client:
    """Connect to MQTT broker with retry."""
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

    while True:
        try:
            client.connect(MQTT_HOST, MQTT_PORT)
            client.loop_start()
            print(f"MQTT connecte a {MQTT_HOST}:{MQTT_PORT}")
            return client
        except Exception:
            print(f"MQTT {MQTT_HOST}:{MQTT_PORT} indisponible, retry dans 2s...")
            time.sleep(2)


def parse_text_block(lines: list[str]) -> dict | None:
    """Parse the text output from the existing ESP32 firmware.

    Expected format:
        ------ Données GPS ------
        Latitude  : 48.268266
        Longitude : 4.068358
        Satellites: 4
        Vitesse   : 0.37 km/h
        -------------------------
    """
    data = {}
    for line in lines:
        if line.startswith("Latitude"):
            data["gps_lat"] = float(line.split(":")[1].strip())
        elif line.startswith("Longitude"):
            data["gps_lng"] = float(line.split(":")[1].strip())
        elif line.startswith("Satellites"):
            data["gps_satellites"] = int(line.split(":")[1].strip())
        elif line.startswith("Vitesse"):
            data["gps_speed_kmh"] = float(line.split(":")[1].strip().replace("km/h", "").strip())

    if "gps_lat" in data:
        return data
    return None


def main() -> None:
    ser = connect_serial()
    mqtt_client = connect_mqtt()

    print(f"Bridge actif: {SERIAL_PORT} -> MQTT {MQTT_HOST}:{MQTT_PORT}/{MQTT_TOPIC}")

    block: list[str] = []
    in_block = False

    while True:
        try:
            line = ser.readline().decode("utf-8", errors="ignore").strip()
            if not line:
                continue

            if "Données GPS" in line or "Donnees GPS" in line:
                in_block = True
                block = []
                continue

            if in_block and line.startswith("-----"):
                data = parse_text_block(block)
                if data:
                    data["timestamp"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
                    data["source"] = "esp32_bateau"
                    mqtt_client.publish(MQTT_TOPIC, json.dumps(data), qos=1)
                    print(f"Publie: {data}")
                in_block = False
                block = []
                continue

            if in_block:
                block.append(line)

        except serial.SerialException:
            print("Port serie perdu, reconnexion...")
            ser.close()
            ser = connect_serial()
        except Exception as exc:
            print(f"Erreur: {exc}")
            time.sleep(1)


if __name__ == "__main__":
    main()
