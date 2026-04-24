# Migration Mini PC - Mise en service du bridge GPS

**Date** : 24 avril 2026
**Contexte** : Le convertisseur USB-Serie est arrive. Le mini PC doit servir de bridge entre l'ESP32 (GPS) et le VPS via MQTT sur 4G.

## Etape 1 : Verifier Python

Ouvrir PowerShell et verifier que Python est installe :

```powershell
python --version
```

Si Python n'est pas installe, le telecharger depuis https://www.python.org/downloads/ (cocher "Add to PATH" pendant l'installation).

## Etape 2 : Installer les dependances

```powershell
cd C:\Users\SE\Desktop\SE\mini-pc
pip install -r requirements.txt
```

Les dependances sont : `pyserial`, `paho-mqtt`, `python-dotenv`.

## Etape 3 : Brancher le convertisseur USB-Serie

1. Brancher le convertisseur USB-Serie sur un port USB du mini PC
2. Connecter les fils entre le convertisseur et l'ESP32 :
   - **TX du convertisseur** → **RX de l'ESP32** (GPIO16)
   - **RX du convertisseur** → **TX de l'ESP32** (GPIO17)
   - **GND** → **GND**
   - **VCC/5V** (si alimentation via convertisseur)
3. Ouvrir le **Gestionnaire de peripheriques** → **Ports (COM & LPT)**
4. Noter le port COM affiche (ex: `COM3`, `COM4`...)
   - Le nom sera du type "USB-SERIAL CH340" ou "CP210x USB to UART"

Si le port n'apparait pas, installer le driver :
- CH340 : https://www.wch-ic.com/downloads/CH341SER_EXE.html
- CP210x : https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers

## Etape 4 : Creer le fichier .env

Copier `.env.example` en `.env` dans le dossier `mini-pc/` :

```powershell
copy .env.example .env
```

Editer `.env` avec le bon port COM :

```env
SERIAL_PORT=COM3
SERIAL_BAUD=115200
MQTT_HOST=212.227.88.180
MQTT_PORT=1883
MQTT_TOPIC=nereides/telemetry
```

**IMPORTANT** : remplacer `COM3` par le port COM identifie a l'etape 3.

## Etape 5 : Tester le bridge

```powershell
cd C:\Users\SE\Desktop\SE
python mini-pc/serial_to_mqtt.py
```

Tu dois voir :
```
Serie connectee sur COM3
MQTT connecte a 212.227.88.180:1883
Bridge actif: COM3 -> MQTT 212.227.88.180:1883/nereides/telemetry
```

Puis, quand le GPS a un fix :
```
Publie: {'gps_lat': 48.267, 'gps_lng': 3.723, 'gps_satellites': 8, 'gps_speed_kmh': 12.5, ...}
```

Si le GPS n'a pas de fix (interieur, pas de ciel degage), aucune trame ne sera publiee. Attendre 30s-2min en exterieur.

## Etape 6 : Lancement automatique

Double-cliquer sur `mini-pc/start_bridge.bat` pour lancer le bridge.

Pour le lancer au demarrage de Windows :
1. Appuyer `Win + R` → taper `shell:startup` → Entree
2. Copier un raccourci de `start_bridge.bat` dans ce dossier

## Verification

Une fois le bridge lance :
- **Dashboard terre** : les donnees GPS doivent apparaitre en temps reel
- **Grafana** : http://212.227.88.180/grafana/ (mossab / mossab123)
- **Console** : chaque trame affiche `Publie: {...}`

## Depannage

| Probleme | Solution |
|----------|----------|
| `Port COMx indisponible` | Verifier le branchement USB, reinstaller le driver CH340/CP210x |
| `MQTT indisponible` | Verifier la connexion 4G du mini PC, ping 212.227.88.180 |
| Pas de trames publiees | Le GPS n'a pas de fix — aller en exterieur, attendre 1-2 min |
| `ModuleNotFoundError` | Relancer `pip install -r requirements.txt` |
| Le port COM change | Windows peut changer le numero COM — reverifier dans le Gestionnaire de peripheriques et mettre a jour `.env` |
