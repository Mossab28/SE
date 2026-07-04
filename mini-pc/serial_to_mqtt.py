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
BACKEND_HTTP_URL = os.getenv("BACKEND_HTTP_URL", "https://nereides.pwn-ai.fr/backend/telemetry")


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


NESTED_KEYS = ("Batterie1", "Batterie2", "CM", "GPS")


def _num(d: dict, key: str):
    v = d.get(key)
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def flatten_nested(raw: dict) -> dict:
    """Aplati le format imbrique (Batterie1/2 // + CM + GPS) -> champs plats.

    Copie locale du flatten_nested du backend, pour alimenter le WebSocket pilote
    local avec des champs plats. Batteries en PARALLELE : tension = moyenne,
    courant = somme, SOC = moyenne. Retourne raw inchange si deja plat.
    """
    if not any(k in raw for k in NESTED_KEYS):
        return raw

    out: dict = {"source": raw.get("source", "minipc_bateau")}
    if raw.get("timestamp") is not None:
        out["timestamp"] = raw["timestamp"]

    b1, b2 = raw.get("Batterie1") or {}, raw.get("Batterie2") or {}
    if b1:
        out["battery1_soc"] = _num(b1, "SOC")
        out["battery1_voltage"] = _num(b1, "Tension")
        out["battery1_current"] = _num(b1, "Current")
    if b2:
        out["battery2_soc"] = _num(b2, "SOC")
        out["battery2_voltage"] = _num(b2, "Tension")
        out["battery2_current"] = _num(b2, "Current")

    socs = [x for x in (_num(b1, "SOC"), _num(b2, "SOC")) if x is not None]
    volts = [x for x in (_num(b1, "Tension"), _num(b2, "Tension")) if x is not None]
    currents = [x for x in (_num(b1, "Current"), _num(b2, "Current")) if x is not None]
    if socs:
        out["battery_soc"] = round(sum(socs) / len(socs), 1)
    if volts:
        out["battery_voltage"] = round(sum(volts) / len(volts), 2)
    if currents:
        out["battery_current"] = round(sum(currents), 2)
    if volts and currents:
        out["battery_power"] = round((out["battery_voltage"] * out["battery_current"]) / 1000, 2)

    cm = raw.get("CM") or {}
    if cm:
        out["motor_speed"] = _num(cm, "RPM")
        out["motor_current"] = _num(cm, "Current")
        out["motor_voltage"] = _num(cm, "Tension")
        out["motor_temperature"] = _num(cm, "TempMoteur")
        out["controller_temperature"] = _num(cm, "TempCM")
        out["controller_throttle"] = _num(cm, "ThrottleV")
        if cm.get("Commande") is not None:
            out["controller_mode"] = str(cm["Commande"])
        if cm.get("FNB") is not None:
            out["controller_fnb"] = str(cm["FNB"])
        if cm.get("Feedback") is not None:
            out["controller_feedback"] = str(cm["Feedback"])
        err = _num(cm, "ErrorCode")
        if err is not None:
            out["controller_error_code"] = int(err)
            out["controller_safety"] = "Nominal" if int(err) == 0 else "Fault"

    gps = raw.get("GPS") or {}
    if gps:
        out["gps_lat"] = _num(gps, "latitude")
        out["gps_lng"] = _num(gps, "longitude")
        sats = _num(gps, "Satellites")
        if sats is not None:
            out["gps_satellites"] = int(sats)
        vitesse = _num(gps, "vitesse")
        if vitesse is not None:
            out["gps_speed_kmh"] = round(vitesse, 1)  # firmware ESP envoie deja des km/h

    return {k: v for k, v in out.items() if v is not None}


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

            # Nouveau format : trame JSON imbriquee (Batterie1/Batterie2/CM/GPS)
            # publiee telle quelle ; le backend s'occupe de l'aplatir.
            if line.startswith("{") and line.endswith("}"):
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    print(f"JSON invalide ignore: {line[:80]}")
                    continue
                payload.setdefault(
                    "timestamp",
                    datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                )
                payload.setdefault("source", "minipc_bateau")
                # 1) MQTT + HTTP : trame imbriquee brute (le backend l'aplatit)
                if mqtt_client is not None:
                    mqtt_client.publish(MQTT_TOPIC, json.dumps(payload), qos=1)
                if also_http:
                    post_to_backend(payload)
                # 2) WebSocket pilote local : aplati ici (l'interface attend du plat)
                flat = flatten_nested(payload)
                broadcast_to_pilot(build_pilot_payload(flat))
                print(f"Publie (JSON): {payload}")
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


# ── Modele physique d'une course (pour tester l'estimation d'autonomie) ────────
# Profil de vitesse cible (temps_s, vitesse_km/h) - interpole lineairement.
# Course de 4 min : depart, 2 lignes droites separees par des virages, sprint final, arrivee.
RACE_SPEED_PROFILE = [
    (0, 0), (12, 26), (55, 26), (68, 12), (82, 24),
    (125, 24), (138, 10), (155, 28), (200, 30), (225, 5), (240, 0),
]
RACE_DURATION_S = 240

# Parametres physiques (bateau elec type Energy Boat Challenge)
RACE_MASS_KG = 300.0          # masse bateau + pilote
RACE_DRAG_K = 9.3             # coef trainee hydro : F_drag = K * v^2  (N, v en m/s)
RACE_ETA = 0.88               # rendement chaine moto-propulsion
RACE_HOTEL_W = 120.0          # consommation electronique au repos
RACE_ACCEL_MAX = 2.0          # m/s^2 max en acceleration
RACE_DECEL_MAX = 3.0          # m/s^2 max en freinage
BATTERY_CAPACITY_WH = 5000.0  # idem ai_predictor.py
RACE_PACK_R = 0.05            # resistance interne pack (ohm) -> sag tension
RACE_START_SOC = 88.0         # SOC initial (%)


def _race_target_speed(t: float) -> float:
    """Vitesse cible (m/s) interpolee depuis le profil, a l'instant t (s)."""
    pts = RACE_SPEED_PROFILE
    if t <= pts[0][0]:
        kmh = pts[0][1]
    elif t >= pts[-1][0]:
        kmh = pts[-1][1]
    else:
        kmh = pts[-1][1]
        for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
            if t0 <= t <= t1:
                frac = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
                kmh = v0 + frac * (v1 - v0)
                break
    return kmh / 3.6


def run_race_mode(mqtt_client: mqtt.Client, also_http: bool = True) -> None:
    import math

    target = f"WS :{WS_PORT}"
    if also_http:
        target += f" + HTTP {BACKEND_HTTP_URL}"
    if mqtt_client is not None:
        target += f" + MQTT {MQTT_HOST}:{MQTT_PORT}"
    print(f"Bridge en mode RACE -> {target}")
    print(f"Course de {RACE_DURATION_S}s, modele physique coherent (SOC, puissance, temp).")
    print("Ctrl+C pour arreter.\n")

    # Etat persistant entre les courses (le SOC continue de descendre)
    soc = RACE_START_SOC                  # %
    batt_temp = 29.0                      # degC
    motor_temp = 42.0                     # degC
    ctrl_temp = 38.0                      # degC
    distance_m = 0.0
    # Position GPS : depart Monaco (coherent avec ai_predictor)
    lat, lng = 43.736834, 7.430180
    heading = 90.0                        # cap initial (est)
    abs_start = time.time()
    race_num = 0

    while True:
        try:
            race_num += 1
            print(f"\n========== COURSE #{race_num} (SOC depart {soc:.1f}%) ==========")
            v = 0.0                        # vitesse reelle (m/s)
            t = 0.0                        # temps dans la course (s)
            dt = 1.0

            while t <= RACE_DURATION_S:
                # 1) Suivi de la vitesse cible avec limite d'acceleration
                v_target = _race_target_speed(t)
                dv = v_target - v
                accel = dv / dt
                accel = max(-RACE_DECEL_MAX, min(RACE_ACCEL_MAX, accel))
                v = max(0.0, v + accel * dt)

                # 2) Forces et puissance mecanique
                f_drag = RACE_DRAG_K * v * v          # trainee hydrodynamique
                f_acc = RACE_MASS_KG * accel          # inertie
                f_total = f_drag + f_acc
                p_mech = max(0.0, f_total * v)        # W (pas de regen)

                # 3) Puissance electrique (rendement + conso hotel)
                p_elec = p_mech / RACE_ETA + RACE_HOTEL_W

                # 4) Tension pack : courbe SOC + sag sous charge
                v_oc = 44.0 + (soc / 100.0) * 6.4     # 44V vide -> 50.4V plein
                # resoudre I a partir de P=V*I avec V=Voc - I*R  =>  R*I^2 - Voc*I + P = 0
                disc = v_oc * v_oc - 4 * RACE_PACK_R * p_elec
                if disc < 0:
                    current = p_elec / v_oc
                else:
                    current = (v_oc - math.sqrt(disc)) / (2 * RACE_PACK_R)
                voltage = v_oc - current * RACE_PACK_R

                # 5) Integration energie -> SOC
                energy_wh = p_elec * (dt / 3600.0)
                soc = max(0.0, soc - 100.0 * energy_wh / BATTERY_CAPACITY_WH)

                # 6) Thermique : modele 1er ordre. La temperature tend vers une cible
                # proportionnelle a la charge, avec inertie (constante de temps tau).
                # => montee douce sous effort, redescente au ralenti. Lisse pour la
                #    regression lineaire du predicteur d'alertes thermiques.
                batt_target = 28.0 + 0.0026 * p_elec        # ~41C a 5 kW
                motor_target = 30.0 + 0.0070 * p_mech        # ~72C a 6 kW meca
                ctrl_target = 28.0 + 0.0042 * p_elec         # ~54C a 6 kW
                batt_temp += (batt_target - batt_temp) * dt / 45.0
                motor_temp += (motor_target - motor_temp) * dt / 50.0
                ctrl_temp += (ctrl_target - ctrl_temp) * dt / 40.0

                # 7) Grandeurs moteur / controleur derivees
                motor_rpm = v * 3.6 * 100.0           # ~3000 RPM a 30 km/h
                motor_torque = min(240.0, max(0.0, f_total / 6.0))
                ctrl_efficiency = round(88.0 + 7.0 * (1.0 - min(1.0, p_elec / 7000.0)), 1)
                motor_pressure = round(2.0 + 1.4 * min(1.0, p_elec / 7000.0), 2)

                # 8) Mode controleur selon la dynamique
                if v < 0.5:
                    mode = "Standby"
                elif accel > 0.5:
                    mode = "Boost"
                else:
                    mode = "Drive"

                # 9) GPS : on avance selon le cap, virages pendant les phases lentes
                if v_target < 14 / 3.6:
                    heading += 6.0                    # virage serre quand on ralentit
                distance_m += v * dt
                dlat = (v * dt) * math.cos(math.radians(heading)) / 111111.0
                dlng = (v * dt) * math.sin(math.radians(heading)) / (111111.0 * math.cos(math.radians(lat)))
                lat += dlat
                lng += dlng

                elapsed = int(time.time() - abs_start)
                dur_str = f"{elapsed // 3600:02d}:{(elapsed % 3600) // 60:02d}:{elapsed % 60:02d}"

                data = {
                    "gps_lat": round(lat, 6),
                    "gps_lng": round(lng, 6),
                    "gps_speed_kmh": round(v * 3.6, 1),
                    "gps_satellites": random.randint(9, 14),
                    "battery_voltage": round(voltage, 2),
                    "battery_current": round(current, 2),
                    "battery_power": round(p_elec / 1000.0, 3),   # kW (ai_predictor *1000)
                    "battery_temperature": round(batt_temp, 1),
                    "battery_soc": round(soc, 1),
                    "motor_temperature": round(motor_temp, 1),
                    "motor_pressure": motor_pressure,
                    "motor_speed": round(motor_rpm, 0),
                    "motor_torque": round(motor_torque, 1),
                    "controller_temperature": round(ctrl_temp, 1),
                    "controller_current": round(current * 0.98, 2),
                    "controller_mode": mode,
                    "controller_safety": "Nominal",
                    "controller_efficiency": ctrl_efficiency,
                    "boat_distance_km": round(distance_m / 1000.0, 3),
                    "boat_activity_duration": dur_str,
                    "source": "race_simulator",
                }
                publish_data(mqtt_client, data, also_http=also_http)
                t += dt
                time.sleep(dt)

            print(f"--- Course #{race_num} terminee. Distance {distance_m/1000:.2f} km, SOC {soc:.1f}% ---")
            if soc < 5.0:
                print("Batterie quasi vide, reset SOC pour nouvelle session.")
                soc = RACE_START_SOC

        except KeyboardInterrupt:
            print("\nArret demande.")
            break
        except Exception as exc:
            print(f"Erreur race: {exc}")
            time.sleep(1)


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
    parser.add_argument(
        "--race",
        action="store_true",
        help="Mode course 4 min : modele physique coherent pour tester l'estimation d'autonomie (implique --http)",
    )
    args = parser.parse_args()
    if args.scenario:
        args.fake = True
        args.http = True
    if args.race:
        args.http = True

    threading.Thread(target=start_ws_server, daemon=True).start()
    time.sleep(0.5)

    mqtt_client = connect_mqtt()

    if args.race:
        run_race_mode(mqtt_client, also_http=args.http)
    elif args.scenario:
        run_scenario_mode(mqtt_client, also_http=args.http)
    elif args.fake:
        run_fake_mode(mqtt_client, also_http=args.http)
    else:
        run_serial_mode(mqtt_client, also_http=not args.no_http)


if __name__ == "__main__":
    main()
