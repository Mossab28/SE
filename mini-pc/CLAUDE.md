# Contexte Mini PC — Bateau Nereides (bridge télémétrie)

Instance Claude tournant **sur le mini-PC embarqué**. Ce mini-PC remplace le Raspberry Pi :
il lit la trame série de l'électronique du bateau et la relaie vers le VPS (MQTT) + une
interface pilote locale.

## Chaîne complète

```
[Électronique bateau : batteries ∥ + contrôleur moteur (CM) + GPS]
        │ USB Série (115200 baud) — trame JSON imbriquée, 1 ligne = 1 objet {...}
        ▼
[Mini PC]  ← TU ES ICI   (mini-pc/serial_to_mqtt.py)
        ├── MQTT TLS  → VPS 212.227.88.180:8883  (dashboard online)
        ├── HTTP POST → https://nereides.pwn-ai.fr/backend/telemetry
        └── WebSocket local :8765 → interface pilote (marche sans internet)
        ▼
[VPS] Mosquitto → Telegraf → InfluxDB / Backend FastAPI → WebSocket → Dashboard + Grafana
```

## ⚠️ CHANGEMENT RÉCENT — nouveau format de trame imbriqué

L'électronique n'envoie plus du texte GPS : elle envoie une **trame JSON imbriquée** sur le
port série, une par ligne. Le bridge la **relaie telle quelle** vers MQTT/HTTP ; c'est le
**backend (sur le VPS)** qui l'aplatit via `flatten_nested()` (`backend.py`).

Exemple de trame reçue sur le série :
```json
{
  "Batterie1": { "SOC": 92.0, "Tension": 48.8, "Current": 27.6 },
  "Batterie2": { "SOC": 91.0, "Tension": 48.9, "Current": 31.1 },
  "CM": { "RPM": 1792, "Current": 58.7, "Tension": 48.9, "ErrorCode": 0,
          "TempMoteur": 50.3, "TempCM": 47.3, "ThrottleV": 0.9,
          "Commande": "Forward", "FNB": "F", "Feedback": "Forward" },
  "GPS": { "vitesse": 5.5, "latitude": 48.267340, "longitude": 3.723456, "Satellites": 8 }
}
```

### Ce qui a changé dans le code (commit `feat: support nested telemetry format`)
- `mini-pc/serial_to_mqtt.py` (`run_serial_mode`) : détecte une ligne série `{...}`, la parse,
  ajoute `timestamp`+`source` si absents, publie **sans transformer** (fallback texte GPS conservé).
- `backend.py` (VPS) : `flatten_nested()` convertit l'imbriqué → champs plats. Branché sur MQTT
  **et** POST. **Rétro-compatible** : une trame déjà plate passe inchangée.
- Frontend (`index.html`/`script.js`/`styles.css`) : section « Batteries — pack parallèle »
  (pack agrégé + les 2 branches côte à côte) + champs Feedback/ErrorCode du CM.

### Mapping imbriqué → champs plats (fait côté backend, pas ici)
| Source | Champ plat | Note |
|--------|-----------|------|
| `Batterie1/2.SOC` | `battery1_soc` / `battery2_soc` | + `battery_soc` = moyenne |
| `Batterie1/2.Tension` | `battery1_voltage` / `battery2_voltage` | + `battery_voltage` = moyenne (bus partagé) |
| `Batterie1/2.Current` | `battery1_current` / `battery2_current` | + `battery_current` = **somme** (parallèle) |
| — | `battery_power` | = V_moy × I_somme / 1000 |
| `CM.RPM/Current/Tension` | `motor_speed` / `motor_current` / `motor_voltage` | |
| `CM.TempMoteur/TempCM` | `motor_temperature` / `controller_temperature` | |
| `CM.ThrottleV/Commande/FNB/Feedback` | `controller_throttle` / `controller_mode` / `controller_fnb` / `controller_feedback` | |
| `CM.ErrorCode` | `controller_error_code` | 0 → `controller_safety=Nominal`, sinon `Fault` |
| `GPS.vitesse` (nœuds) | `gps_speed_kmh` | × 1.852 |
| `GPS.latitude/longitude/Satellites` | `gps_lat` / `gps_lng` / `gps_satellites` | |

> **Batteries en PARALLÈLE** : elles se déchargent simultanément → tension partagée (moyenne),
> courants additionnés (somme), SOC moyenné. Chaque branche reste visible individuellement.

## Lancer le bridge

```bash
cd SE && git pull          # récupérer le dernier code
cd mini-pc
pip install -r requirements.txt
copy .env.example .env     # puis éditer : SERIAL_PORT = le bon port COM
python serial_to_mqtt.py   # mode réel (lit le série, publie)
```

Config `.env` importante :
- `SERIAL_PORT` = port COM de l'électronique (Gestionnaire de périphériques → Ports COM & LPT)
- `MQTT_HOST=212.227.88.180`, `MQTT_PORT=8883`, `MQTT_TLS=true` (TLS vers le VPS)
- `MQTT_TOPIC=nereides/telemetry`

### Modes de test (sans matériel)
- `python serial_to_mqtt.py --fake` : données simulées (format **plat**, pas de série)
- `python serial_to_mqtt.py --scenario` : cycle NORMAL/WARNING/ALERT/RECOVERY
- `python serial_to_mqtt.py --race` : course 4 min avec physique cohérente
- Ces modes n'exercent pas encore les 2 batteries imbriquées (données plates).

## Vérifier que ça marche
- Console : `Publie (JSON): {...}` à chaque trame réelle (ou `Publie: {...}` en mode fake).
- Dashboard online : https://nereides.pwn-ai.fr/ → section « Batteries — pack parallèle »
  doit montrer SOC/tension/courant du pack **et** des 2 branches.
- Grafana : http://212.227.88.180/grafana/ (mossab / mossab123).

## Dépannage
- **Port COM introuvable** : driver USB (CP210x / CH340) ; vérifier le câble.
- **`Publie (JSON)` absent mais trames reçues** : la ligne série n'est peut-être pas un JSON
  sur **une seule ligne** `{...}` — vérifier le firmware (pas de retour à la ligne au milieu).
- **Dashboard vide côté batteries** : s'assurer que le **backend du VPS** a bien la version
  avec `flatten_nested` (sinon l'imbriqué n'est pas aplati). Voir `backend.py`.
- **MQTT refusé** : le VPS écoute en TLS sur 8883 (`require_certificate false`) ; internet OK ?

## Accès Pi (legacy, si besoin) : `docs/RASPBERRY_PI_ACCESS.md` — user `nereides`.
