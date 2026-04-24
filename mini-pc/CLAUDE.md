# Contexte Mini PC - Bateau Nereides

## Le projet

Système de télémétrie temps réel pour un bateau électrique (association Nereides, UTT).
La chaîne complète : **ESP32 (GPS) → USB Serial → Mini PC → MQTT (4G) → VPS → Dashboard web**

## Architecture déployée

```
[ESP32 + GPS Neo-6M]
        │ USB Serial (115200 baud, texte brut)
        ▼
[Mini PC Windows 11]  ← TU ES ICI
        │ MQTT publish via 4G
        ▼
[VPS 212.227.88.180]
   ├── Mosquitto (port 1883)
   ├── Telegraf → InfluxDB
   ├── FastAPI backend → WebSocket
   └── Grafana (/grafana/)
        │
        ▼
[Dashboard web] (hébergé sur le VPS via Nginx)
```

## Ce qui est déjà fait

- Le VPS tourne : Mosquitto, InfluxDB, Grafana, Telegraf, Backend (Docker Compose)
- Le dashboard web est hébergé sur le VPS (Nginx reverse proxy)
- Le firmware ESP32 est dans `../esp32/gps_serial.ino`
- Le script bridge `serial_to_mqtt.py` est prêt dans ce dossier

## Ce qu'il faut faire sur ce mini PC

### 1. Installer les dépendances Python

```bash
cd mini-pc
pip install -r requirements.txt
```

Dépendances : `pyserial`, `paho-mqtt`, `python-dotenv`

### 2. Configurer le .env

Copier `.env.example` en `.env` et ajuster :

```env
SERIAL_PORT=COM3        # ← adapter au port USB de l'ESP32 (vérifier dans Gestionnaire de périphériques)
SERIAL_BAUD=115200
MQTT_HOST=212.227.88.180
MQTT_PORT=1883
MQTT_TOPIC=nereides/telemetry
```

Pour trouver le bon port COM : Gestionnaire de périphériques → Ports (COM & LPT) → chercher "USB Serial" ou "CP210x" ou "CH340".

### 3. Flasher l'ESP32

Le firmware est dans `../esp32/gps_serial.ino`. Il faut :
- Arduino IDE ou PlatformIO
- Installer la bibliothèque **TinyGPS++**
- Board : ESP32 Dev Module
- Le GPS Neo-6M est branché sur UART1 (RX=GPIO16, TX=GPIO17)
- Upload via USB

### 4. Lancer le bridge

```bash
python serial_to_mqtt.py
```

Le script :
- Lit les trames texte de l'ESP32 sur le port série et les convertit en JSON
- Ajoute `timestamp` et `source: "esp32_bateau"`
- Publie sur MQTT topic `nereides/telemetry` vers le VPS
- Se reconnecte automatiquement si le port série ou MQTT est perdu

### 5. Vérifier que ça marche

- Le script affiche `Publie: {...}` à chaque trame envoyée
- Le dashboard web doit afficher les données GPS en temps réel
- Grafana : http://212.227.88.180/grafana/ (mossab / mossab123)

## Format des trames texte (ESP32 → Serial)

L'ESP32 envoie du **texte brut** (pas du JSON) via Serial :

```
------ Données GPS ------
Latitude  : 48.267340
Longitude : 3.723456
Satellites: 8
Vitesse   : 12.5 km/h
-------------------------
```

Le bridge parse ce texte et publie en JSON sur MQTT :
```json
{
  "gps_lat": 48.267340,
  "gps_lng": 3.723456,
  "gps_satellites": 8,
  "gps_speed_kmh": 12.5,
  "timestamp": "2026-03-25T14:30:00+00:00",
  "source": "esp32_bateau"
}
```

## Dépannage

- **Port COM introuvable** : vérifier le driver USB (CP210x ou CH340 selon le modèle ESP32)
- **MQTT connexion refusée** : vérifier que le mini PC a bien accès internet (4G) et que le port 1883 est ouvert
- **JSON invalide** : le script ignore les lignes non-JSON (logs ESP32, lignes vides)
- **GPS sans fix** : le Neo-6M peut mettre 30s-2min pour obtenir un fix à froid (ciel dégagé nécessaire)
