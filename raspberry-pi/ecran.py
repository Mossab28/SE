import serial
import time
import paho.mqtt.client as mqtt
import json
import csv
from datetime import datetime
import socket
import threading
import RPi.GPIO as GPIO #Importe la bibliothèque pour contrôler les GPIOs
import requests
import queue
import os
import asyncio
import websockets
def gui_available():
	return os.environ.get("DISPLAY") is not None
fenetre = None


last_update = {}

#valeurs à afficher sur l'ecran; en rajouter sous le meme format au besoin !
labels={}
afficher_ecran = [
	["GPS/vitesse", 0],
	["CM/FNB", "-"],
	["batterie/SOC", "-"], #["composant/grandeur",0], comme sur l'esp; 0 est la valeur de cette grandeur
	["batterie/TempMax", "-"],
	#["batterie/Voltage", "-"],
	["batterie/Current", "-"],
	#["CM/RPM", "-"],
	["CM/TempMoteur", "-"],
	["CM/TempCM", "-"],
	["CM/Current", "-"]
	]
#config affichage ecran
def quitter_ecran(): #pour fermer l'écran proprement qd on coupe le programme
	stop_event.set()
	GPIO.cleanup()
	try:
		if ser:
			ser.close()
	except:
		pass
	fenetre.destroy()

portrait = True #pour choisir orientation ecran
def start_gui(): #pour lancer l'affichage de la fenetre graphique
	global fenetre, labels
	from tkinter import Tk, Label
	fenetre = Tk()

	fenetre.update_idletasks()
	fenetre.update()
	time.sleep(0.5)  #pour le laisser charger avec plein ecran

	fenetre.attributes('-fullscreen', True)
	if portrait:
		os.system("xrandr --output HDMI-A-1 --rotate right")
	else:
		os.system("xrandr --output HDMI-A-1 --rotate normal")


	px_par_mm = fenetre.winfo_fpixels("1m")
	for i in afficher_ecran: #generer le dictionnaire label et les labels
		print(i)
		labels[i[0]] = Label(fenetre, text=i[0].replace("/", " ") + " : " +str(i[1]), font=(None,int(8*px_par_mm),'bold'))
		labels[i[0]].pack()
	fenetre.protocol("WM_DELETE_WINDOW", quitter_ecran)
	fenetre.mainloop()


stop_event = threading.Event()  #cree la variable globale pour l'arret au cas ou


def gui_watcher(): #permet de détecter le branchement / la présence d'un écran
	gui_running = False

	while not stop_event.is_set():
		if gui_available() and not gui_running:
			print("Écran détecté: lancement GUI")
			threading.Thread(target=start_gui, daemon=True).start()
			gui_running = True

		if not gui_available() and gui_running:
			print("Écran perdu: arrêt GUI")
			if fenetre:
				fenetre.quit()
			gui_running = False

	time.sleep(2)


#config pour l'envoie sur le google sheet
url_app_script = "https://script.google.com/macros/s/AKfycbwesdgfdhqKK8Dd7ZjY2wosHhbjBCJYVWAxcdTd1WhH3ftWcUitUXAOaH5MHsKVyG1EqQ/exec"

def send_data_google(payload): #pour envoyer sur le google sheet
	try:
		response = requests.post(url_app_script, json=payload)
		print("envoie google ok")
	except Exception as e:
		print("Erreur envoi google:", e)


#config gpio pour la led
GPIO.setmode(GPIO.BOARD) #Définit le mode de numérotation (Board)
GPIO.setwarnings(False) #On désactive les messages d'alerte

LED = 7 #Définit le numéro du port GPIO qui alimente la led
GPIO.setup(LED, GPIO.OUT) #Active le contrôle du GPIO

LED_connexion = 11 #Définit le numéro du port GPIO qui alimente la led
GPIO.setup(LED_connexion, GPIO.OUT) #Active le contrôle du GPIO



# Configuration du port série (UART avec l'ESP)
SERIAL_PORT = "/dev/serial0"
BAUDRATE = 115200
ser = None

#Config broker MQTT (hivemq ici, plan gratuit, donc sans stockage)
BROKER = "broker.hivemq.com"
PORT = 8883
USERNAME = "Nereides26"
PASSWORD = "Tuyere52" #j'crois ca sert a rien ici, c'est sans stockage


#--MQTT--
mqtt_connected = False

def on_connect(client, userdata, flags, rc, properties=None):
	global mqtt_connected
	mqtt_connected = True
	print("MQTT connecté")

def on_disconnect(client, userdata, rc, properties=None, packet_from_broker=None):
	global mqtt_connected
	mqtt_connected = False
	print("MQTT déconnecté")

client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.username_pw_set(USERNAME, PASSWORD)
client.tls_set(ca_certs="/etc/ssl/certs/ca-certificates.crt")
client.on_connect = on_connect
client.on_disconnect = on_disconnect

Wifi_connected = True
def network_ok(): #check si on a de la connexion internet
	global Wifi_connected
	try:
		socket.create_connection(("8.8.8.8", 53), timeout=2)
		GPIO.output(LED_connexion, GPIO.HIGH)
		Wifi_connected = True
		return True
	except OSError:
		GPIO.output(LED_connexion, GPIO.LOW)
		Wifi_connected = False
		return False


"""
#permet de relancer la co si besoin
mqtt_loop_started = False
def mqtt_thread(): #pour se connecter au broker MQTT
	global mqtt_connected, mqtt_loop_started, Wifi_connected
	while True:
		if network_ok():
			if not mqtt_connected:
				try:
					if not mqtt_loop_started:
						client.loop_start()
						mqtt_loop_started = True
					client.connect_async(BROKER, PORT, 60)
				except Exception as e:
					print("MQTT erreur:", e)
		else:
			mqtt_connected = False
			GPIO.output(LED_connexion, GPIO.LOW)
			Wifi_connected = False
		time.sleep(5) #attend 5 s, sans rien faire; ne bloque pas le prog, car lance depuis un thread

threading.Thread(target=mqtt_thread, daemon=True).start() #ligne qui lance la fonction ci-dessus pour la co en "arriere plan" du programme (comme ca, ca n'impacte pas le reste du prog, avec les sleep)!
"""

# Configuration CSV
csv_file = open("/home/nereides/data_telemetrie.csv", mode="a", newline="", buffering=1)
csv_writer = csv.writer(csv_file)
if csv_file.tell() == 0:
	csv_writer.writerow(["Timestamp", "Composant", "Grandeur mesurée", "Valeur"])



# ── Config MQTT VPS (Grafana + Dashboard site) ──
VPS_BROKER = "212.227.88.180"
VPS_PORT = 1883
VPS_TOPIC = "nereides/telemetry"
# Topic dedie aux triggers d'affichage a distance (POST /trigger sur le backend VPS),
# relayes ici vers l'ecran pilote local (ws://localhost:8765).
VPS_DISPLAY_TOPIC = "nereides/display"

FIELD_MAP = {
	("batterie", "temperature"): "battery_temperature",
	("batterie", "TempMax"): "battery_temperature",
	("batterie", "TempMin"): "battery_temp_min",
	("batterie", "Voltage"): "battery_voltage",
	("batterie", "Tension"): "battery_voltage",
	("batterie", "Current"): "battery_current",
	("batterie", "SOC"): "battery_soc",
	# Deux batteries en parallele suivies individuellement (interface pilote)
	("Batterie1", "SOC"): "battery1_soc",
	("Batterie1", "Tension"): "battery1_voltage",
	("Batterie1", "Current"): "battery1_current",
	("Batterie1", "temperature"): "battery1_temp",
	("Batterie1", "TempMax"): "battery1_temp",
	("Batterie1", "Temp"): "battery1_temp",
	("Batterie2", "SOC"): "battery2_soc",
	("Batterie2", "Tension"): "battery2_voltage",
	("Batterie2", "Current"): "battery2_current",
	("Batterie2", "temperature"): "battery2_temp",
	("Batterie2", "TempMax"): "battery2_temp",
	("Batterie2", "Temp"): "battery2_temp",
	# Thermistance generique (CAN 0x400) : temperature panneaux solaires
	("Thermistance", "temp"): "solar_temperature",
	("CM", "TempMoteur"): "motor_temperature",
	("CM", "TempCM"): "controller_temperature",
	("CM", "RPM"): "motor_speed",
	("CM", "Current"): "motor_current",
	("CM", "Tension"): "motor_voltage",
	("CM", "ErrorCode"): "controller_error_code",
	("CM", "Commande"): "controller_mode",
	("CM", "Feedback"): "controller_feedback",
	("CM", "FNB"): "controller_fnb",
	("CM", "ThrottleV"): "controller_throttle",
	("GPS", "latitude"): "gps_lat",
	("GPS", "longitude"): "gps_lng",
	("GPS", "vitesse"): "gps_speed_kmh",
	("GPS", "Satellites"): "gps_satellites",
	("CM", "latitude"): "gps_lat",
	("CM", "longitude"): "gps_lng",
	("CM", "Satellites"): "gps_satellites",
	("Boat", "Speed"): "gps_speed_kmh",
	("boat", "speed"): "gps_speed_kmh",
}

vps_mqtt_connected = False

def on_vps_connect(client, userdata, flags, rc, properties=None):
	global vps_mqtt_connected
	vps_mqtt_connected = True
	print("VPS MQTT connecte")
	client.subscribe(VPS_DISPLAY_TOPIC, qos=1)

def on_vps_disconnect(client, userdata, rc, properties=None, packet_from_broker=None):
	global vps_mqtt_connected
	vps_mqtt_connected = False
	print("VPS MQTT deconnecte")

def on_vps_message(client, userdata, msg):
	"""Relaie les triggers d'affichage (topic nereides/display) vers l'ecran pilote local."""
	try:
		data = json.loads(msg.payload)
		if ws_loop is not None:
			asyncio.run_coroutine_threadsafe(ws_broadcast(data), ws_loop)
	except Exception as e:
		print("VPS MQTT message erreur:", e)

vps_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
vps_client.on_connect = on_vps_connect
vps_client.on_disconnect = on_vps_disconnect
vps_client.on_message = on_vps_message

def vps_mqtt_thread():
	global vps_mqtt_connected
	vps_loop_started = False
	while not stop_event.is_set():
		if network_ok():
			if not vps_mqtt_connected:
				try:
					if not vps_loop_started:
						vps_client.loop_start()
						vps_loop_started = True
					vps_client.connect_async(VPS_BROKER, VPS_PORT, 60)
				except Exception as e:
					print("VPS MQTT erreur:", e)
		time.sleep(5)

threading.Thread(target=vps_mqtt_thread, daemon=True).start()

def flatten_and_map(payload):
	flat = {
		"timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
		"source": "raspberry_pi"
	}
	for component, mesures in payload.items():
		if isinstance(mesures, dict):
			for donnee, valeur in mesures.items():
				key = FIELD_MAP.get((component, donnee), f"{component}_{donnee}".lower())
				flat[key] = valeur

	# controller_safety est un statut texte (Nominal/Fault), derive ici du code
	# d'erreur brut plutot que d'envoyer l'entier directement dans ce champ.
	if "controller_error_code" in flat:
		try:
			flat["controller_safety"] = "Nominal" if int(flat["controller_error_code"]) == 0 else "Fault"
		except (TypeError, ValueError):
			pass

	return flat

def send_to_vps(payload):
	if vps_mqtt_connected:
		try:
			flat = flatten_and_map(payload)
			vps_client.publish(VPS_TOPIC, json.dumps(flat), qos=1)
			print("VPS MQTT envoye")
		except Exception as e:
			print("VPS MQTT publish erreur:", e)


# Queue pour l'envoi vers Google Sheets
google_queue = queue.Queue()
#et notre boucle principale (main=principale tkt j'ai valide le02); ici s'execute la recolte et transfert de notre precieuse data
def google_worker():
    while not stop_event.is_set():
        try:
            payload = google_queue.get(timeout=1)
            send_data_google(payload)
            google_queue.task_done()
        except queue.Empty:
            continue

threading.Thread(target=google_worker, daemon=True).start()



# ── WebSocket local pour l interface pilote ──
ws_clients = set()

async def ws_handler(websocket):
    ws_clients.add(websocket)
    try:
        await websocket.wait_closed()
    finally:
        ws_clients.discard(websocket)

async def ws_broadcast(data):
    if ws_clients:
        msg = json.dumps(data)
        await asyncio.gather(
            *[client.send(msg) for client in ws_clients],
            return_exceptions=True
        )

ws_loop = None

async def ws_server():
    global ws_loop
    ws_loop = asyncio.get_event_loop()
    async with websockets.serve(ws_handler, "0.0.0.0", 8765):
        await asyncio.Future()

def start_ws_server():
    asyncio.run(ws_server())

threading.Thread(target=start_ws_server, daemon=True).start()

led_last_toggle = 0
LED_INTERVAL = 0.05  # 50 ms pour clignoter la LED


def process_payload(payload):
    """Traite une trame deja decodee (JSON), qu'elle vienne du serie (ESP)
    ou du GPS telephone : LED, CSV, ecran, diffusion pilote locale (toujours),
    puis envois distants (Google + VPS) si internet disponible."""
    global led_last_toggle
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for component, mesures in payload.items():
        for donnee, valeur in mesures.items():
            now = time.time()
            if now - led_last_toggle > LED_INTERVAL:
                GPIO.output(LED, GPIO.HIGH)
                led_last_toggle = now
            GPIO.output(LED, GPIO.LOW)

            csv_writer.writerow([timestamp, component, donnee, valeur])
            csv_file.flush()

            key = f"{component}/{donnee}"
            for item in afficher_ecran:
                if item[0] == key:
                    item[1] = valeur
                    break

            if fenetre and key in labels:
                fenetre.after(0, lambda k=key, v=valeur: labels[k].config(
                    text=f"{k} : {v}"))

    # Interface pilote LOCALE : TOUJOURS diffusee, meme sans
    # internet (le pilote a bord ne doit pas dependre du reseau).
    if ws_loop and ws_clients:
        flat_ws = flatten_and_map(payload)
        asyncio.run_coroutine_threadsafe(ws_broadcast(flat_ws), ws_loop)

    # Envois DISTANTS : uniquement si internet disponible.
    if Wifi_connected:
        google_queue.put(payload)          # Google Sheets
        send_to_vps(payload)               # VPS (Grafana + dashboard)


# ── GPS de secours via le telephone (hotspot du bord) ──
# Le telephone (S25) sert de point d'acces internet au bateau ; son IP est
# donc fixe et connue (10.165.102.138, passerelle standard d'un hotspot Android).
# Un script Termux sur le telephone expose sa position sur cette IP en JSON :
# {"latitude":..,"longitude":..,"speed_kmh":..,"satellites":..}
PHONE_GPS_URL = "http://127.0.0.1:8081/gps"
PHONE_GPS_POLL_INTERVAL = 1.5  # secondes


def phone_gps_thread():
    while not stop_event.is_set():
        try:
            r = requests.get(PHONE_GPS_URL, timeout=2)
            if r.ok:
                d = r.json()
                payload = {
                    "GPS": {
                        "vitesse": d.get("speed_kmh"),
                        "latitude": d.get("latitude"),
                        "longitude": d.get("longitude"),
                        "Satellites": d.get("satellites", 0),
                    }
                }
                print("Reçu (GPS telephone):", payload)
                process_payload(payload)
        except Exception as e:
            print("GPS telephone indisponible:", e)
        time.sleep(PHONE_GPS_POLL_INTERVAL)


threading.Thread(target=phone_gps_thread, daemon=True).start()


def main_loop_optimized():
    global ser
    uart_buffer = ""

    while not stop_event.is_set():
        # Vérifie port série
        if ser is None or not ser.is_open:
            try:
                ser = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=0)
                print("Port série connecté !")
            except:
                print("Port série non disponible, réessai dans 2s...")
                ser = None
                time.sleep(2)
                continue

        # Lecture non-bloquante
        try:
            if ser.in_waiting:
                uart_buffer += ser.read(ser.in_waiting).decode('utf-8', errors='ignore')
                while '\n' in uart_buffer:
                    line, uart_buffer = uart_buffer.split('\n', 1)
                    line = line.strip()
                    if not line:
                        continue

                    print("Reçu:", line)
                    try:
                        payload = json.loads(line)
                        process_payload(payload)
                    except json.JSONDecodeError:
                        print("JSON invalide, ignoré:", line)

        except serial.SerialException:
            print("Port série perdu, tentative de reconnexion...")
            if ser:
                ser.close()
            ser = None

        time.sleep(0.001)  # petit sleep pour CPU friendly

# Lancer le main loop optimisé
threading.Thread(target=main_loop_optimized, daemon=True).start()
#threading.Thread(target=gui_watcher, daemon=True).start() #lancer pour la recherche de l'ecran

while not stop_event.is_set():
    time.sleep(1)
