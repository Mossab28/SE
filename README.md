# Nereides — Systeme de Telemetrie Bateau

Projet de systeme embarque pour l'association Nereides de l'UTT. Supervision en temps reel d'un bateau : GPS, capteurs, batterie, moteur.

## Architecture

```
Capteurs + ESP32  ──USB Serie──▶  Mini PC (Windows)  ──MQTT/4G──▶  VPS
                                                                    ├── Mosquitto (broker)
                                                                    ├── Telegraf → InfluxDB (persistance)
                                                                    ├── Grafana (historique)
                                                                    └── Backend FastAPI → WebSocket → Frontend (temps reel)
```

## Structure du repo

```
SE/
├── esp32/                      # Code Arduino ESP32
│   └── gps_serial.ino          # Lecture GPS + envoi serie JSON
├── mini-pc/                    # Scripts pour le mini PC embarque
│   ├── serial_to_mqtt.py       # Lecture serie USB → publication MQTT
│   ├── .env.example            # Config (port serie, MQTT host)
│   └── requirements.txt        # pyserial, paho-mqtt, python-dotenv
├── vps/                        # Configs Docker pour le VPS
│   ├── docker-compose.yml      # Mosquitto + Telegraf + InfluxDB + Grafana
│   ├── mosquitto.conf          # Config broker MQTT
│   └── telegraf.conf           # Bridge MQTT → InfluxDB
├── backend.py                  # FastAPI : MQTT subscriber + WebSocket broadcast
├── simulateur.py               # Generateur de donnees de test (dev local)
├── index.html                  # Dashboard frontend
├── script.js                   # Logique temps reel (WebSocket)
├── styles.css                  # Styles du dashboard
└── requirements.txt            # Dependances backend
```

## Stack technique

| Composant | Technologie |
|-----------|-------------|
| Microcontroleur | ESP32 (Arduino/C++) |
| Capteurs | GPS Neo-6M (+ extensions futures) |
| Mini PC | Windows 11 AMD, Python |
| Communication embarquee | USB Serie (115200 baud) |
| Communication distante | MQTT via 4G (QoS 1) |
| Broker MQTT | Mosquitto (Docker sur VPS) |
| Bridge MQTT → DB | Telegraf |
| Base de donnees | InfluxDB 2.7 |
| Dashboards | Grafana 12.x |
| Backend temps reel | FastAPI + WebSocket |
| Frontend | Vanilla JS (GitHub Pages) |

## Quick Start

### 1. ESP32

Flasher `esp32/gps_serial.ino` avec Arduino IDE. Brancher le GPS Neo-6M sur les pins RX=16, TX=17.
     
git clone https://github.com/Mossab28/SE.git
cd SE/mini-pc
pip install -r requirements.txt
# Configurer le .env (port serie, adresse MQTT)
cp .env.example .env
# Editer .env avec le bon port COM
python serial_to_mqtt.py
```

### 3. VPS

```bash
ssh mossab@212.227.88.180
cd ~/telemetry
docker compose up -d
```

Services accessibles :
- **Grafana** : http://212.227.88.180/grafana/
- **InfluxDB** : http://212.227.88.180/influxdb/
- **MQTT** : 212.227.88.180:1884 (via Nginx stream proxy)

### 4. Test local (sans bateau)

```bash
# Terminal 1 : backend
pip install -r requirements.txt
uvicorn backend:app --host 0.0.0.0 --port 8000

# Terminal 2 : simulateur
python simulateur.py

# Ouvrir http://localhost:8080
```

## Format des trames MQTT

Topic : `nereides/telemetry`

Le firmware embarque envoie desormais un **format imbrique** (batteries en parallele + controleur moteur + GPS). Le backend l'aplatit automatiquement vers les champs du dashboard (`flatten_nested` dans `backend.py`).

```json
{
  "Batterie1": { "SOC": 92.0, "Tension": 48.8, "Current": 27.6 },
  "Batterie2": { "SOC": 91.0, "Tension": 48.9, "Current": 31.1 },
  "CM": {
    "RPM": 1792, "Current": 58.7, "Tension": 48.9, "ErrorCode": 0,
    "TempMoteur": 50.3, "TempCM": 47.3, "ThrottleV": 0.9,
    "Commande": "Forward", "FNB": "F", "Feedback": "Forward"
  },
  "GPS": { "vitesse": 5.5, "latitude": 48.267340, "longitude": 4.074356, "Satellites": 8 }
}
```

Agregation cote backend (batteries **en parallele**) :
- `battery_voltage` = moyenne des tensions (bus partage)
- `battery_current` = **somme** des courants B1 + B2
- `battery_soc` = moyenne des SOC ; `battery_power` = V x I / 1000
- `GPS.vitesse` (noeuds) x 1.852 -> `gps_speed_kmh`
- `CM.ErrorCode` = 0 -> securite `Nominal`, sinon `Fault`

> L'ancien format **plat** (`gps_lat`, `battery_voltage`, ...) reste accepte : `flatten_nested` le laisse passer tel quel.

## Credentials

| Service | User | Password |
|---------|------|----------|
| Grafana | mossab | mossab123 |
| InfluxDB | mossab | mossab123influx |
| InfluxDB Token | — | mon-token-telemetry-2024 |
| InfluxDB Org/Bucket | — | bateau / telemetry |

## Mise a jour du mini PC

```bash
cd SE && git pull
```

## Association

**Nereides** — Association de l'Universite de Technologie de Troyes (UTT)
