"""Read ESP32 JSON from USB serial, publish to MQTT."""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
import serial
from dotenv import load_dotenv

load_dotenv()

SERIAL_PORT = os.getenv("SERIAL_PORT", "COM3")
SERIAL_BAUD = int(os.getenv("SERIAL_BAUD", "115200"))
MQTT_HOST = os.getenv("MQTT_HOST", "212.227.88.180")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1884"))
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


def main() -> None:
    ser = connect_serial()
    mqtt_client = connect_mqtt()

    print(f"Bridge actif: {SERIAL_PORT} -> MQTT {MQTT_HOST}:{MQTT_PORT}/{MQTT_TOPIC}")

    while True:
        try:
            line = ser.readline().decode("utf-8", errors="ignore").strip()
            if not line or not line.startswith("{"):
                continue

            data = json.loads(line)
            data["timestamp"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            data["source"] = "esp32_bateau"

            mqtt_client.publish(MQTT_TOPIC, json.dumps(data), qos=1)
            print(f"Publie: {data}")

        except json.JSONDecodeError:
            print(f"JSON invalide ignore: {line[:80]}")
        except serial.SerialException:
            print("Port serie perdu, reconnexion...")
            ser.close()
            ser = connect_serial()
        except Exception as exc:
            print(f"Erreur: {exc}")
            time.sleep(1)


if __name__ == "__main__":
    main()
