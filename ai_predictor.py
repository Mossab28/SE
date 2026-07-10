from __future__ import annotations

import json
import os
import threading
import time
import urllib.request
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

import paho.mqtt.client as mqtt
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# ── Config ────────────────────────────────────────────────────────────────────
# Capacite calibree a partir d'un run reel (2026-07-03, 32 min, SOC 95%->90%,
# energie integree = 320 Wh sur une branche => ~64 Wh/%SOC/branche => ~128 Wh/%SOC
# pour le pack complet (2 batteries en parallele) => ~12800 Wh. Remplace la valeur
# arbitraire precedente (5000 Wh). Voir ai_predictor.py::_live_discharge_estimate
# pour l'estimation dynamique qui recalibre en direct pendant la course.
BATTERY_CAPACITY_WH = float(os.getenv("BATTERY_CAPACITY_WH", "12800"))
RACE_TARGET_HOURS = float(os.getenv("RACE_TARGET_HOURS", "1.0"))
# Fenetre glissante pour la regression de decharge SOC en direct
SOC_LIVE_WINDOW_S = float(os.getenv("SOC_LIVE_WINDOW_S", "600"))
SOC_LIVE_MIN_SAMPLES = 20
SOC_LIVE_MIN_DELTA_PCT = 0.3  # SOC quantifie en entiers : eviter le bruit sous ce seuil
MONACO_LAT = 43.736834
MONACO_LNG = 7.430180
MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "nereides/telemetry")
WEATHER_REFRESH_S = 60

# ── Shared state ──────────────────────────────────────────────────────────────
_lock = threading.Lock()
_telemetry: dict[str, Any] = {}
_weather: dict[str, Any] = {}
_predictions: dict[str, Any] = {"status": "waiting"}
_batt_hist: deque[tuple[float, float]] = deque(maxlen=60)
_mot_hist: deque[tuple[float, float]] = deque(maxlen=60)
_soc_hist: deque[tuple[float, float]] = deque(maxlen=1800)  # ~30min a 1 sample/s
_PRIORITY = {"ok": 0, "warn": 1, "alert": 2}


# ── Weather ───────────────────────────────────────────────────────────────────
def _fetch_weather() -> dict[str, Any]:
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={MONACO_LAT}&longitude={MONACO_LNG}"
        "&current=temperature_2m,relative_humidity_2m,surface_pressure,"
        "wind_speed_10m,wind_direction_10m"
        "&wind_speed_unit=ms&timezone=Europe%2FParis"
    )
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read())
        c = data.get("current", {})
        return {
            "temperature_c": c.get("temperature_2m"),
            "humidity_pct": c.get("relative_humidity_2m"),
            "pressure_hpa": c.get("surface_pressure"),
            "wind_speed_ms": c.get("wind_speed_10m"),
            "wind_direction_deg": c.get("wind_direction_10m"),
        }
    except Exception as exc:
        print(f"[weather] {exc}")
        with _lock:
            return _weather.copy()


def _weather_loop() -> None:
    global _weather
    while True:
        w = _fetch_weather()
        with _lock:
            _weather = w
        print(f"[weather] Monaco: {w}")
        time.sleep(WEATHER_REFRESH_S)


# ── Prediction models ─────────────────────────────────────────────────────────
def _slope(samples: list[tuple[float, float]]) -> float:
    """Least-squares slope (dy/dt) from (timestamp, value) pairs."""
    n = len(samples)
    if n < 2:
        return 0.0
    t0 = samples[0][0]
    xs = [s[0] - t0 for s in samples]
    ys = [s[1] for s in samples]
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    den = sum((xs[i] - mx) ** 2 for i in range(n))
    return num / den if den else 0.0


def _thermal_alert(
    hist: deque[tuple[float, float]],
    current: float | None,
    threshold: float,
    window_s: float = 30.0,
) -> dict | None:
    """Predict time to thermal threshold using linear regression on recent samples."""
    if current is None or len(hist) < 10:
        return None
    now = time.time()
    samples = [(t, v) for t, v in hist if now - t <= window_s]
    if len(samples) < 5:
        return None
    rate = _slope(samples)   # °C/s
    if rate <= 0.005:
        return None
    secs = (threshold - current) / rate
    if secs <= 0 or secs > 600:
        return None
    return {
        "threshold_c": threshold,
        "seconds_left": int(secs),
        "rate_c_per_min": round(rate * 60, 2),
    }


def _live_discharge_estimate(soc_hist: deque[tuple[float, float]], current_soc: float) -> dict | None:
    """Estime le temps de batterie restant a partir du declin REEL du SOC observe
    pendant la navigation en cours (regression lineaire), plutot que d'une formule
    theorique. C'est la methode la plus fiable une fois assez de donnees accumulees :
    elle capture implicitement l'etat reel de la batterie, la meteo, le regime moteur
    effectif, etc. sans avoir a les modeliser individuellement."""
    if len(soc_hist) < SOC_LIVE_MIN_SAMPLES:
        return None
    now = time.time()
    samples = [(t, v) for t, v in soc_hist if now - t <= SOC_LIVE_WINDOW_S]
    if len(samples) < SOC_LIVE_MIN_SAMPLES:
        return None
    span_s = samples[-1][0] - samples[0][0]
    delta_pct = samples[0][1] - samples[-1][1]
    if span_s < 60 or delta_pct < SOC_LIVE_MIN_DELTA_PCT:
        return None  # pas assez de declin mesurable sur la fenetre (SOC quantifie en %)

    rate_pct_per_s = -_slope(samples)  # negatif car le SOC decroit
    if rate_pct_per_s <= 0:
        return None

    hours = (current_soc / rate_pct_per_s) / 3600
    # Confiance : proportionnelle a la couverture de la fenetre cible (max 30min)
    confidence = round(min(1.0, span_s / SOC_LIVE_WINDOW_S), 2)
    return {
        "time_remaining_s": int(hours * 3600),
        "rate_pct_per_hour": round(rate_pct_per_s * 3600, 2),
        "window_s": int(span_s),
        "samples": len(samples),
        "confidence": confidence,
    }


def _compute(tel: dict, wx: dict) -> dict:
    now = time.time()
    pred: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "weather": wx,
    }

    # Le bateau (ecran.py) n'envoie jamais d'agregat "battery_soc"/"battery_power" :
    # seulement battery1_soc/battery2_soc et les tensions/courants par branche.
    # On derive l'agregat ici (meme logique que backend.py::flatten_nested), sinon
    # soc reste None en permanence et la prediction ne se declenche jamais.
    socs = [s for s in (tel.get("battery1_soc"), tel.get("battery2_soc")) if s is not None]
    soc = (sum(socs) / len(socs)) if socs else tel.get("battery_soc")

    v1, i1 = tel.get("battery1_voltage"), tel.get("battery1_current")
    v2, i2 = tel.get("battery2_voltage"), tel.get("battery2_current")
    power_w = 0.0
    if v1 is not None and i1 is not None:
        power_w += abs(v1 * i1)
    if v2 is not None and i2 is not None:
        power_w += abs(v2 * i2)
    if power_w == 0.0:
        power_w = (tel.get("battery_power") or 0.0) * 1000.0

    batt_t = max(
        (t for t in (tel.get("battery1_temp"), tel.get("battery2_temp"), tel.get("battery_temperature")) if t is not None),
        default=None,
    )
    mot_t = tel.get("motor_temperature")
    speed = tel.get("gps_speed_kmh") or 0.0

    if batt_t is not None:
        _batt_hist.append((now, batt_t))
    if mot_t is not None:
        _mot_hist.append((now, mot_t))
    if soc is not None:
        _soc_hist.append((now, soc))

    # ── Endurance model ───────────────────────────────────────────────────────
    # Physics: time = energy_remaining / power_consumed
    # Corrections: battery temp efficiency loss + wind drag penalty
    endurance = None
    if soc is not None and power_w > 20.0:
        # Li-ion loses ~1.8% capacity per degree above 35°C
        temp_factor = 1.0
        if batt_t is not None and batt_t > 35.0:
            temp_factor -= 0.018 * (batt_t - 35.0)
        temp_factor = max(0.5, temp_factor)

        # Wind drag: P_drag ∝ v² — headwind increases power need
        wind_ms = wx.get("wind_speed_ms") or 0.0
        wind_factor = 1.0 + 0.002 * wind_ms ** 2

        energy_wh = (soc / 100.0) * BATTERY_CAPACITY_WH * temp_factor
        effective_w = power_w * wind_factor
        hours_physics = energy_wh / effective_w

        # Estimation live : declin REEL du SOC mesure pendant la navigation en cours.
        # Plus fiable des que suffisamment de donnees sont accumulees (capture l'etat
        # reel de la batterie sans avoir a modeliser temperature/vent/rendement).
        live = _live_discharge_estimate(_soc_hist, soc)
        if live is not None:
            confidence = live["confidence"]
            hours_live = live["time_remaining_s"] / 3600
            # Blend progressif : au demarrage on fait confiance au modele physique
            # calibre, puis on bascule vers la mesure live au fur et a mesure
            # qu'elle couvre une fenetre significative (jusqu'a 30 min).
            hours = confidence * hours_live + (1 - confidence) * hours_physics
            method = "live" if confidence >= 0.8 else "blend"
        else:
            hours = hours_physics
            method = "physics"

        endurance = {
            "time_remaining_s": int(hours * 3600),
            "range_km": round(hours * speed, 1) if speed > 0.5 else None,
            "energy_remaining_wh": round(energy_wh),
            "temp_factor": round(temp_factor, 3),
            "wind_factor": round(wind_factor, 3),
            "method": method,
            "physics_time_remaining_s": int(hours_physics * 3600),
            "live_discharge": live,
        }
    pred["endurance"] = endurance

    # ── Recommended speed (optimal for RACE_TARGET_HOURS endurance) ───────────
    # Model: P ∝ v²  →  v_opt = v_current × sqrt(P_target / P_current)
    recommended_speed = None
    if endurance and speed > 0.5 and power_w > 20.0:
        energy_wh = endurance["energy_remaining_wh"]
        target_power_w = energy_wh / RACE_TARGET_HOURS
        if target_power_w < power_w:
            # Reduce speed to make battery last RACE_TARGET_HOURS
            speed_factor = (target_power_w / power_w) ** 0.5
            recommended_speed = round(max(3.0, speed * speed_factor), 1)
        else:
            # Current draw is sustainable — keep current speed
            recommended_speed = round(speed, 1)
    pred["recommended_speed_kmh"] = recommended_speed

    # ── Thermal trajectory alerts ─────────────────────────────────────────────
    pred["battery_thermal_alert"] = _thermal_alert(_batt_hist, batt_t, threshold=45.0)
    pred["motor_thermal_alert"] = _thermal_alert(_mot_hist, mot_t, threshold=85.0)

    # ── Adaptive recommendations ──────────────────────────────────────────────
    recs: list[str] = []
    priority = "ok"

    def _up(p: str) -> None:
        nonlocal priority
        if _PRIORITY.get(p, 0) > _PRIORITY.get(priority, 0):
            priority = p

    if soc is not None:
        if soc < 10:
            recs.append("CRITIQUE : SOC < 10% — retour au port immédiat")
            _up("alert")
        elif soc < 20:
            recs.append("Réduire puissance à 60% — autonomie critique (SOC < 20%)")
            _up("alert")
        elif soc < 35:
            recs.append("Réduire puissance à 80% — SOC faible")
            _up("warn")

    if pred["battery_thermal_alert"]:
        m = pred["battery_thermal_alert"]["seconds_left"] // 60
        recs.append(f"Surchauffe batterie dans ~{m} min — réduire la charge")
        _up("warn")

    if pred["motor_thermal_alert"]:
        m = pred["motor_thermal_alert"]["seconds_left"] // 60
        recs.append(f"Surchauffe moteur dans ~{m} min — réduire la vitesse")
        _up("warn")

    safety = tel.get("controller_safety", "").lower()
    if safety in {"fault", "critical"}:
        recs.append("DÉFAUT contrôleur — passer en puissance minimale")
        _up("alert")

    mot_p = tel.get("motor_pressure")
    if mot_p is not None and mot_p < 1.5:
        recs.append("Pression refroidissement faible — surveiller moteur")
        _up("warn")

    wind_ms = wx.get("wind_speed_ms") or 0.0
    if wind_ms > 12:
        recs.append(f"Vent fort ({wind_ms:.0f} m/s) — navigation prudente, autonomie réduite")
        _up("warn")
    elif wind_ms > 7:
        extra = int(0.002 * wind_ms ** 2 * 100)
        recs.append(f"Vent modéré ({wind_ms:.0f} m/s) — consommation +{extra}% estimée")

    if not recs:
        recs.append("Système nominal — conditions optimales")

    pred["recommendations"] = recs
    pred["priority"] = priority
    return pred


# ── MQTT consumer ─────────────────────────────────────────────────────────────
def _on_message(client, userdata, msg):
    global _predictions
    try:
        raw = json.loads(msg.payload)
    except Exception:
        return
    with _lock:
        _telemetry.update(raw)
        _predictions = _compute(_telemetry, _weather)
        pred = _predictions
    # Publish recommended speed to nereides/predictions for Telegraf→InfluxDB→Grafana
    rec = pred.get("recommended_speed_kmh")
    if rec is not None:
        payload = json.dumps({
            "timestamp": pred["timestamp"],
            "recommended_speed_kmh": rec,
        })
        try:
            client.publish("nereides/predictions", payload, qos=0)
        except Exception:
            pass


def _mqtt_loop() -> None:
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_message = _on_message
    while True:
        try:
            client.connect(MQTT_HOST, MQTT_PORT)
            client.subscribe(MQTT_TOPIC, qos=1)
            print(f"[mqtt] {MQTT_HOST}:{MQTT_PORT} → {MQTT_TOPIC}")
            client.loop_forever()
        except Exception as exc:
            print(f"[mqtt] {exc} — retry in 5s")
            time.sleep(5)


# ── FastAPI ───────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    threading.Thread(target=_mqtt_loop, daemon=True).start()
    threading.Thread(target=_weather_loop, daemon=True).start()
    yield


app = FastAPI(title="Nereides AI Predictor", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/predictions")
def get_predictions() -> dict:
    with _lock:
        result = _predictions.copy()
        # Always include latest weather, even when waiting for boat telemetry
        if _weather:
            result["weather"] = _weather.copy()
        return result


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
