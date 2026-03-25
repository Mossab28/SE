# Design — Systeme de Telemetrie Bateau Nereides

**Date** : 2026-03-25
**Projet** : Association Nereides — UTT
**Auteur** : Mossab

## Contexte

Systeme embarque de supervision en temps reel pour un bateau. Les capteurs envoient des donnees a un ESP32 qui les transmet via USB serie a un mini PC embarque. Le mini PC pousse les donnees en MQTT vers un VPS qui assure la persistance (InfluxDB), la visualisation historique (Grafana) et l'affichage temps reel (frontend vanilla JS via WebSocket).

## Architecture

```
Capteurs → ESP32 → USB Serie → Mini PC (Windows 11) → MQTT (4G) → VPS
                                                                    ├── Mosquitto (broker MQTT)
                                                                    ├── Telegraf (bridge MQTT → InfluxDB)
                                                                    ├── InfluxDB (persistance)
                                                                    ├── Grafana (dashboards historiques)
                                                                    ├── Backend FastAPI (MQTT subscriber → WebSocket)
                                                                    └── Frontend vanilla JS (GitHub Pages, temps reel)
```

## Composants

### 1. ESP32 (Arduino/C++)

- Lit les capteurs (GPS Neo-6M pour commencer, puis extension aux autres)
- Librairie : TinyGPS++ pour le GPS
- Envoie des trames JSON sur USB serie toutes les 1s (GPS Neo-6M output = 1Hz par defaut)
- Si pas de fix GPS (0 satellites) : envoie quand meme la trame avec `gps_lat: null, gps_lng: null`
- Format de trame :
  ```json
  {
    "gps_lat": 48.267340,
    "gps_lng": 4.074356,
    "gps_speed_kmh": 12.5,
    "gps_satellites": 8
  }
  ```
- Extensible : ajout de champs pour batterie, moteur, temperature, etc.

### 2. Mini PC (Windows 11, AMD)

- **Script Python** (`mini-pc/serial_to_mqtt.py`) :
  - Lit le port serie USB (pyserial)
  - Parse les trames JSON de l'ESP32
  - Ajoute `timestamp` (ISO8601) et `source: "esp32_bateau"` a la trame
  - Publie sur le broker MQTT du VPS (topic `nereides/telemetry`, QoS 1)
- **Config** : port serie et broker MQTT configures via variables d'environnement ou fichier `.env`
  - `SERIAL_PORT` (ex: `COM3`)
  - `MQTT_HOST` (ex: `212.227.88.180`)
  - `MQTT_PORT` (ex: `1883`)
- **Reconnexion** : si le port serie ou MQTT se deconnecte, retry automatique toutes les 2s
- **Pas de buffer offline** : si la 4G tombe, les trames sont perdues (acceptable pour le MVP)
- **Dependances** : `pyserial`, `paho-mqtt`, `python-dotenv`
- **Synchronisation** : repo git clone, mise a jour via `git pull`
- **Connexion** : 4G via routeur embarque, toujours connecte

### 3. VPS (212.227.88.180) — Docker

Services Docker dans `~/telemetry/docker-compose.yml` :

#### Mosquitto (broker MQTT)
- Port 1883 expose via Nginx stream proxy (TCP, pas HTTP)
- Config : `allow_anonymous true` pour le MVP (pas d'auth)
- Topic principal : `nereides/telemetry`

```
# mosquitto.conf
listener 1883
allow_anonymous true
```

#### Telegraf (bridge MQTT → InfluxDB)
- Souscrit au topic MQTT `nereides/telemetry`
- Parse le JSON
- Ecrit dans InfluxDB bucket `telemetry`, org `bateau`

```toml
# telegraf.conf (extrait)
[[inputs.mqtt_consumer]]
  servers = ["tcp://mosquitto:1883"]
  topics = ["nereides/telemetry"]
  data_format = "json"
  json_time_key = "timestamp"
  json_time_format = "2006-01-02T15:04:05Z"

[[outputs.influxdb_v2]]
  urls = ["http://influxdb:8086"]
  token = "mon-token-telemetry-2024"
  organization = "bateau"
  bucket = "telemetry"
```

#### InfluxDB
- Deja en place (bucket `telemetry`, org `bateau`)

#### Grafana
- Deja en place (accessible via `http://212.227.88.180/grafana/`)

#### Backend FastAPI
- Conserve le `POST /telemetry` pour le simulateur local (tests)
- Ajoute un subscriber MQTT qui ecoute `nereides/telemetry`
- Les deux sources (POST et MQTT) alimentent le meme broadcast WebSocket
- Endpoint `/ws` pour le frontend

#### docker-compose.yml (services a ajouter)

```yaml
  mosquitto:
    image: eclipse-mosquitto:2
    container_name: mosquitto
    restart: unless-stopped
    ports:
      - "1883:1883"
    volumes:
      - ./mosquitto.conf:/mosquitto/config/mosquitto.conf

  telegraf:
    image: telegraf:latest
    container_name: telegraf
    restart: unless-stopped
    volumes:
      - ./telegraf.conf:/etc/telegraf/telegraf.conf:ro
    depends_on:
      - mosquitto
      - influxdb

  backend:
    build: .
    container_name: backend-telemetry
    restart: unless-stopped
    ports:
      - "8001:8000"
    environment:
      INFLUX_URL: http://influxdb:8086
      INFLUX_TOKEN: mon-token-telemetry-2024
      INFLUX_ORG: bateau
      INFLUX_BUCKET: telemetry
      MQTT_HOST: mosquitto
      MQTT_PORT: 1883
      MQTT_TOPIC: nereides/telemetry
    depends_on:
      - mosquitto
      - influxdb
```

### 4. Frontend vanilla JS (GitHub Pages)

- Dashboard existant (index.html + script.js + styles.css)
- WebSocket URL configuree pour pointer vers le VPS : `ws://212.227.88.180/ws`
- Ajoute les champs GPS au dashboard : latitude, longitude, vitesse, satellites (affichage numerique)
- Detection de donnees stale : si aucune trame recue depuis 5s, affiche "Connexion perdue"

## Flux de donnees

```
GPS Neo-6M
    │ UART (9600 baud, 1Hz)
    ▼
ESP32
    │ USB Serie (115200 baud, JSON toutes les 1s)
    ▼
Mini PC Windows (Python)
    │ Ajoute timestamp + source
    │ MQTT publish QoS 1 (topic: nereides/telemetry)
    │ via 4G (~50-80ms latence)
    ▼
VPS — Mosquitto (broker MQTT)
    ├──▶ Telegraf ──▶ InfluxDB (persistance)
    ├──▶ Backend FastAPI ──▶ WebSocket ──▶ Frontend JS (temps reel)
    └──▶ Grafana (requetes InfluxDB, dashboards historiques)
```

## Contraintes

- **Latence** : ~1s end-to-end (GPS 1Hz + 4G ~50-80ms + processing)
- **Connexion** : 4G permanente via routeur embarque
- **Extensibilite** : commencer avec le GPS, ajouter batterie/moteur/temperature ensuite
- **Simplicite** : le mini PC pull le repo git pour se mettre a jour
- **Topic MQTT** : un seul topic `nereides/telemetry` avec toutes les donnees dans un JSON (simple, suffisant pour le MVP)

## Format de trame MQTT

Topic : `nereides/telemetry`

```json
{
  "timestamp": "2026-03-25T14:30:00Z",
  "source": "esp32_bateau",
  "gps_lat": 48.267340,
  "gps_lng": 4.074356,
  "gps_speed_kmh": 12.5,
  "gps_satellites": 8
}
```

- `timestamp` et `source` sont ajoutes par le script mini PC (pas par l'ESP32)
- Si pas de fix GPS : `gps_lat: null, gps_lng: null`
- Extensible avec les champs existants du simulateur :
  - `battery_temperature`, `battery_voltage`, `battery_current`, `battery_power`
  - `motor_temperature`, `motor_pressure`, `motor_speed`, `motor_torque`
  - `controller_mode`, `controller_power_request`, `controller_efficiency`, `controller_safety`
  - `boat_distance_km`, `boat_activity_duration`

## Infrastructure VPS existante (ne pas toucher)

- `mossab-portfolio-app-1` (port 3001)
- `auris-training` (port 5002)
- `portf-app-1` (port 5030)
- Nginx reverse proxy (carchat.online, lakhdarberache.fr, mossabmirandeney.fr, uber-clone)

## Nginx — proxy MQTT

MQTT est du TCP, pas HTTP. Il faut utiliser le module `stream` de Nginx :

```nginx
# /etc/nginx/nginx.conf (ajouter en dehors du bloc http)
stream {
    server {
        listen 1884;
        proxy_pass 127.0.0.1:1883;
    }
}
```

Le mini PC se connecte a `212.227.88.180:1884` (expose par le firewall UFW).
Alternative : ouvrir directement le port 1883 dans UFW sans passer par Nginx.
