"""Bridge ESP32 -> MQTT VPS + WebSocket local pour interface pilote.

Le bridge :
- Lit les donnees GPS du port serie (format texte de l'ESP32)
- Publie sur le broker MQTT du VPS (pour le dashboard online)
- Diffuse sur un WebSocket local (port 8765) pour l'interface pilote en local
  qui fonctionne meme sans internet.

Mode --fake : pas de port serie, genere des donnees simulees (pour tests).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import threading
import time
from datetime import datetime, timezone

import paho.mqtt.client as mqtt
import serial
import urllib.request
import websockets
from dotenv import load_dotenv

load_dotenv()

SERIAL_PORT = os.getenv("SERIAL_PORT", "COM4")
SERIAL_BAUD = int(os.getenv("SERIAL_BAUD", "115200"))
MQTT_HOST = os.getenv("MQTT_HOST", "212.227.88.180")
MQTT_PORT = int(os.getenv("MQTT_PORT", "8883"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "nereides/telemetry")
MQTT_TLS = os.getenv("MQTT_TLS", "true").lower() in ("1", "true", "yes")
WS_PORT = int(os.getenv("WS_LOCAL_PORT", "8765"))
BACKEND_HTTP_URL = os.getenv("BACKEND_HTTP_URL", "http://nereides.pwn-ai.fr/backend/telemetry")


ws_clients: set = set()
ws_loop: asyncio.AbstractEventLoop | None = None


async def _ws_handler(websocket):
    ws_clients.add(websocket)
    try:
        await websocket.wait_closed()
    finally:
        ws_clients.discard(websocket)


async def _ws_server() -> None:
    global ws_loop
    ws_loop = asyncio.get_event_loop()
    async with websockets.serve(_ws_handler, "0.0.0.0", WS_PORT):
        print(f"WebSocket local actif sur ws://0.0.0.0:{WS_PORT}")
        await asyncio.Future()


def start_ws_server() -> None:
    asyncio.run(_ws_server())


async def _ws_broadcast(message: str) -> None:
    if not ws_clients:
        return
    await asyncio.gather(
        *(client.send(message) for client in ws_clients),
        return_exceptions=True,
    )


def broadcast_to_pilot(payload: dict) -> None:
    if ws_loop is None or not ws_clients:
        return
    msg = json.dumps(payload)
    asyncio.run_coroutine_threadsafe(_ws_broadcast(msg), ws_loop)


def build_statuses(data: dict) -> dict:
    voltage = data.get("battery_voltage")
    batt_temp = data.get("battery_temperature")
    motor_pressure = data.get("motor_pressure")
    motor_temp = data.get("motor_temperature")
    safety = (data.get("controller_safety") or "").lower()
    sats = data.get("gps_satellites", 0) or 0

    power_ok = (voltage is None or voltage >= 45) and (batt_temp is None or batt_temp < 45)
    cooling_ok = (motor_pressure is None or motor_pressure >= 1.5) and (motor_temp is None or motor_temp < 85)
    controller_ok = safety not in {"fault", "trip", "critical"}
    comms_ok = sats >= 4

    return {
        "power": {
            "text": "Operationnelle" if power_ok else "Sur alerte",
            "tone": "ok" if power_ok else "alert",
        },
        "cooling": {
            "text": "Operationnel" if cooling_ok else "A surveiller",
            "tone": "ok" if cooling_ok else "warn",
        },
        "controller": {
            "text": "Nominal" if controller_ok else "Defaut",
            "tone": "ok" if controller_ok else "alert",
        },
        "comms": {
            "text": "Operationnelle" if comms_ok else "Sat. faibles",
            "tone": "ok" if comms_ok else "warn",
        },
    }


def build_pilot_payload(data: dict) -> dict:
    """Format expected by pilot-ui/script.js."""
    fields = {k: v for k, v in data.items() if k not in ("timestamp", "source")}
    return {
        "connected": True,
        "fields": fields,
        "statuses": build_statuses(data),
        "event": f"Trame de {data.get('source', 'esp32_bateau')} a {datetime.now().strftime('%H:%M:%S')}.",
    }


def connect_serial() -> serial.Serial:
    while True:
        try:
            ser = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=2)
            print(f"Serie connectee sur {SERIAL_PORT}")
            return ser
        except serial.SerialException:
            print(f"Port {SERIAL_PORT} indisponible, retry dans 2s...")
            time.sleep(2)


def connect_mqtt() -> mqtt.Client:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if MQTT_TLS:
        import ssl
        client.tls_set(cert_reqs=ssl.CERT_NONE)
        client.tls_insecure_set(True)
    proto = "mqtts" if MQTT_TLS else "mqtt"
    while True:
        try:
            client.connect(MQTT_HOST, MQTT_PORT)
            client.loop_start()
            print(f"MQTT connecte a {proto}://{MQTT_HOST}:{MQTT_PORT}")
            return client
        except Exception as exc:
            print(f"MQTT {proto}://{MQTT_HOST}:{MQTT_PORT} indispo ({exc}), retry dans 2s...")
            time.sleep(2)


def parse_text_block(lines: list[str]) -> dict | None:
    """Parse the text output from the existing ESP32 firmware."""
    data: dict = {}
    for line in lines:
        if line.startswith("Latitude"):
            data["gps_lat"] = float(line.split(":")[1].strip())
        elif line.startswith("Longitude"):
            data["gps_lng"] = float(line.split(":")[1].strip())
        elif line.startswith("Satellites"):
            data["gps_satellites"] = int(line.split(":")[1].strip())
        elif line.startswith("Vitesse"):
            data["gps_speed_kmh"] = float(
                line.split(":")[1].strip().replace("km/h", "").strip()
            )

    if "gps_lat" in data:
        return data
    return None


def post_to_backend(data: dict) -> None:
    """Bypass MQTT and POST directly to backend HTTP endpoint."""
    try:
        req = urllib.request.Request(
            BACKEND_HTTP_URL,
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=3).read()
    except Exception as exc:
        print(f"HTTP POST error: {exc}")


def publish_data(mqtt_client: mqtt.Client | None, data: dict, also_http: bool = False) -> None:
    data["timestamp"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    data.setdefault("source", "esp32_bateau")

    if mqtt_client is not None:
        try:
            mqtt_client.publish(MQTT_TOPIC, json.dumps(data), qos=1)
        except Exception as exc:
            print(f"MQTT publish error: {exc}")

    if also_http:
        post_to_backend(data)

    pilot_payload = build_pilot_payload(data)
    broadcast_to_pilot(pilot_payload)
    print(f"Publie: {data}")


def run_serial_mode(mqtt_client: mqtt.Client, also_http: bool = True) -> None:
    ser = connect_serial()
    target = f"MQTT {MQTT_HOST}:{MQTT_PORT}/{MQTT_TOPIC} + WS :{WS_PORT}"
    if also_http:
        target += f" + HTTP {BACKEND_HTTP_URL}"
    print(f"Bridge actif: {SERIAL_PORT} -> {target}")

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
                    publish_data(mqtt_client, data, also_http=also_http)
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


def run_fake_mode(mqtt_client: mqtt.Client, also_http: bool = False) -> None:
    target = f"MQTT {MQTT_HOST}:{MQTT_PORT}/{MQTT_TOPIC} + WS :{WS_PORT}"
    if also_http:
        target += f" + HTTP {BACKEND_HTTP_URL}"
    print(f"Bridge en mode FAKE -> {target}")
    print("Generation de donnees simulees (Ctrl+C pour arreter).")

    distance_km = 0.0
    start_time = time.time()
    lat_base, lng_base = 48.2674, 4.0743

    while True:
        try:
            distance_km += random.uniform(0.005, 0.05)
            elapsed = int(time.time() - start_time)
            duration = f"{elapsed // 3600:02d}:{(elapsed % 3600) // 60:02d}:{elapsed % 60:02d}"

            voltage = round(random.uniform(46.0, 52.0), 2)
            current = round(random.uniform(40.0, 160.0), 2)

            data = {
                "gps_lat": round(lat_base + random.uniform(-0.005, 0.005), 6),
                "gps_lng": round(lng_base + random.uniform(-0.005, 0.005), 6),
                "gps_speed_kmh": round(random.uniform(0.0, 28.0), 1),
                "gps_satellites": random.randint(6, 14),
                "battery_voltage": voltage,
                "battery_current": current,
                "battery_power": round(voltage * current / 1000, 2),
                "battery_temperature": round(random.uniform(28.0, 44.0), 1),
                "battery_soc": random.randint(50, 95),
                "motor_temperature": round(random.uniform(45.0, 88.0), 1),
                "motor_pressure": round(random.uniform(1.4, 3.8), 2),
                "motor_speed": round(random.uniform(800, 3200), 0),
                "motor_torque": round(random.uniform(50.0, 220.0), 1),
                "controller_temperature": round(random.uniform(35.0, 70.0), 1),
                "controller_current": round(random.uniform(15.0, 90.0), 1),
                "controller_mode": random.choice(["Standby", "Drive", "Boost"]),
                "controller_safety": random.choices(
                    ["Nominal", "Warning", "fault"], weights=[80, 18, 2]
                )[0],
                "controller_efficiency": round(random.uniform(84.0, 97.0), 1),
                "boat_distance_km": round(distance_km, 2),
                "boat_activity_duration": duration,
                "source": "fake_simulator",
            }
            publish_data(mqtt_client, data, also_http=also_http)
            time.sleep(1)
        except KeyboardInterrupt:
            print("\nArret demande.")
            break
        except Exception as exc:
            print(f"Erreur fake: {exc}")
            time.sleep(1)


SCENARIO_PHASES = [
    # (label, duree_sec, generateur_de_data)
    ("NORMAL", 12, lambda: {
        "battery_voltage": round(random.uniform(48.5, 51.5), 2),
        "battery_temperature": round(random.uniform(28.0, 35.0), 1),
        "battery_soc": random.randint(70, 95),
        "battery_current": round(random.uniform(40.0, 90.0), 2),
        "controller_temperature": round(random.uniform(35.0, 50.0), 1),
        "controller_current": round(random.uniform(15.0, 50.0), 1),
        "controller_safety": "Nominal",
        "motor_temperature": round(random.uniform(45.0, 65.0), 1),
        "motor_pressure": round(random.uniform(2.0, 3.5), 2),
        "gps_speed_kmh": round(random.uniform(8.0, 18.0), 1),
        "gps_satellites": random.randint(8, 14),
    }),
    ("WARNING - batterie chaude / moteur tendu", 12, lambda: {
        "battery_voltage": round(random.uniform(46.0, 48.5), 2),
        "battery_temperature": round(random.uniform(40.5, 44.5), 1),
        "battery_soc": random.randint(25, 45),
        "battery_current": round(random.uniform(100.0, 140.0), 2),
        "controller_temperature": round(random.uniform(62.0, 78.0), 1),
        "controller_current": round(random.uniform(60.0, 85.0), 1),
        "controller_safety": "Warning",
        "motor_temperature": round(random.uniform(70.0, 84.0), 1),
        "motor_pressure": round(random.uniform(1.5, 2.0), 2),
        "gps_speed_kmh": round(random.uniform(15.0, 25.0), 1),
        "gps_satellites": random.randint(5, 8),
    }),
    ("ALERT - panne controleur + sur-temperature", 12, lambda: {
        "battery_voltage": round(random.uniform(43.0, 45.5), 2),
        "battery_temperature": round(random.uniform(46.0, 52.0), 1),
        "battery_soc": random.randint(8, 18),
        "battery_current": round(random.uniform(140.0, 180.0), 2),
        "controller_temperature": round(random.uniform(82.0, 95.0), 1),
        "controller_current": round(random.uniform(85.0, 110.0), 1),
        "controller_safety": "fault",
        "motor_temperature": round(random.uniform(86.0, 95.0), 1),
        "motor_pressure": round(random.uniform(0.8, 1.4), 2),
        "gps_speed_kmh": round(random.uniform(0.0, 5.0), 1),
        "gps_satellites": random.randint(2, 4),
    }),
    ("RECOVERY - retour normal", 8, lambda: {
        "battery_voltage": round(random.uniform(47.5, 49.5), 2),
        "battery_temperature": round(random.uniform(35.0, 39.0), 1),
        "battery_soc": random.randint(40, 60),
        "battery_current": round(random.uniform(60.0, 90.0), 2),
        "controller_temperature": round(random.uniform(50.0, 60.0), 1),
        "controller_current": round(random.uniform(30.0, 55.0), 1),
        "controller_safety": "Nominal",
        "motor_temperature": round(random.uniform(55.0, 70.0), 1),
        "motor_pressure": round(random.uniform(1.8, 2.5), 2),
        "gps_speed_kmh": round(random.uniform(5.0, 12.0), 1),
        "gps_satellites": random.randint(7, 10),
    }),
]


def run_scenario_mode(mqtt_client: mqtt.Client, also_http: bool = True) -> None:
    target = f"WS :{WS_PORT}"
    if also_http:
        target += f" + HTTP {BACKEND_HTTP_URL}"
    if mqtt_client is not None:
        target += f" + MQTT {MQTT_HOST}:{MQTT_PORT}"
    print(f"Bridge en mode SCENARIO -> {target}")
    print("Cycles : NORMAL -> WARNING -> ALERT -> RECOVERY -> NORMAL ...")
    print("Ctrl+C pour arreter.\n")

    distance_km = 0.0
    start_time = time.time()
    lat_base, lng_base = 48.2674, 4.0743
    cycle = 0

    while True:
        try:
            cycle += 1
            for label, duration, gen in SCENARIO_PHASES:
                print(f"\n>>> Cycle {cycle} - Phase: {label} ({duration}s)")
                phase_start = time.time()
                while time.time() - phase_start < duration:
                    distance_km += random.uniform(0.005, 0.05)
                    elapsed = int(time.time() - start_time)
                    dur_str = f"{elapsed // 3600:02d}:{(elapsed % 3600) // 60:02d}:{elapsed % 60:02d}"

                    base = gen()
                    data = {
                        "gps_lat": round(lat_base + random.uniform(-0.003, 0.003), 6),
                        "gps_lng": round(lng_base + random.uniform(-0.003, 0.003), 6),
                        "battery_power": round(base["battery_voltage"] * base["battery_current"] / 1000, 2),
                        "motor_speed": round(random.uniform(800, 3000), 0),
                        "motor_torque": round(random.uniform(50.0, 220.0), 1),
                        "controller_mode": "Drive",
                        "controller_efficiency": round(random.uniform(82.0, 96.0), 1),
                        "boat_distance_km": round(distance_km, 2),
                        "boat_activity_duration": dur_str,
                        "source": f"scenario_{label.split()[0].lower()}",
                        **base,
                    }
                    publish_data(mqtt_client, data, also_http=also_http)
                    time.sleep(1)
        except KeyboardInterrupt:
            print("\nArret demande.")
            break


def main() -> None:
    parser = argparse.ArgumentParser(description="Bridge serie/MQTT/WebSocket")
    parser.add_argument(
        "--fake",
        action="store_true",
        help="Mode test : genere des donnees simulees au lieu de lire le port serie",
    )
    parser.add_argument(
        "--http",
        action="store_true",
        help="Force le POST HTTP au backend (active par defaut en mode serie)",
    )
    parser.add_argument(
        "--no-http",
        action="store_true",
        help="Desactive le POST HTTP au backend (mode MQTT pur)",
    )
    parser.add_argument(
        "--scenario",
        action="store_true",
        help="Mode test couleurs : cycle NORMAL/WARNING/ALERT/RECOVERY (implique --fake --http)",
    )
    args = parser.parse_args()
    if args.scenario:
        args.fake = True
        args.http = True

    threading.Thread(target=start_ws_server, daemon=True).start()
    time.sleep(0.5)

    mqtt_client = connect_mqtt()

    if args.scenario:
        run_scenario_mode(mqtt_client, also_http=args.http)
    elif args.fake:
        run_fake_mode(mqtt_client, also_http=args.http)
    else:
        run_serial_mode(mqtt_client, also_http=not args.no_http)


if __name__ == "__main__":
    main()
