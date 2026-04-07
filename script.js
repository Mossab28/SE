const fields = {
  battery_temperature: "--",
  battery_voltage: "--",
  battery_current: "--",
  battery_power: "--",
  motor_temperature: "--",
  motor_pressure: "--",
  motor_speed: "--",
  motor_torque: "--",
  controller_mode: "--",
  controller_power_request: "--",
  controller_efficiency: "--",
  controller_safety: "--",
  boat_distance_km: "--",
  boat_activity_duration: "--",
  gps_lat: "--",
  gps_lng: "--",
  gps_speed_kmh: "--",
  gps_satellites: "--",
};

const statusConfig = {
  power: { text: "En attente", tone: "neutral" },
  cooling: { text: "En attente", tone: "neutral" },
  controller: { text: "En attente", tone: "neutral" },
  comms: { text: "En attente", tone: "neutral" },
};

const barConfig = {
  battery_temperature: { min: 0, max: 50, warnAbove: 38, alertAbove: 45 },
  battery_voltage: { min: 40, max: 55, warnBelow: 46, alertBelow: 44 },
  battery_current: { min: 0, max: 180, warnAbove: 140, alertAbove: 160 },
  battery_power: { min: 0, max: 10, warnAbove: 7, alertAbove: 8.5 },
  motor_temperature: { min: 0, max: 100, warnAbove: 75, alertAbove: 85 },
  motor_pressure: { min: 0, max: 4, warnBelow: 2, alertBelow: 1.5 },
  motor_speed: { min: 0, max: 3500, warnAbove: 2800, alertAbove: 3200 },
  motor_torque: { min: 0, max: 250, warnAbove: 180, alertAbove: 220 },
  controller_power_request: { min: 0, max: 100, warnAbove: 75, alertAbove: 90 },
  controller_efficiency: { min: 70, max: 100, warnBelow: 88, alertBelow: 82 },
};

const metricLabels = {
  battery_temperature: { title: "Temperature batteries", unit: "degC" },
  battery_voltage: { title: "Voltage batterie", unit: "V" },
  battery_current: { title: "Courant batterie", unit: "A" },
  battery_power: { title: "Puissance batterie", unit: "kW" },
  motor_temperature: { title: "Temperature moteur", unit: "degC" },
  motor_pressure: { title: "Pression moteur", unit: "bar" },
  motor_speed: { title: "Vitesse moteur", unit: "rpm" },
  motor_torque: { title: "Couple moteur", unit: "Nm" },
  controller_power_request: { title: "Consigne puissance", unit: "%" },
  controller_efficiency: { title: "Rendement controleur", unit: "%" },
};

let socket;
let reconnectTimer;
let pollTimer;
let ageTimer;
let lastTelemetryAt = null;
const gaugeState = {};
let map;
let boatMarker;
let boatTrail;
const backendHost = "212.227.88.180";
const backendHttpUrl = `http://${backendHost}/backend`;
const backendWsUrl = `ws://${backendHost}/ws`;

function createGaugeMarkup() {
  return `
    <svg viewBox="0 0 210 118" aria-hidden="true">
      <path d="M 35 98 A 70 70 0 0 1 57 47" fill="none" stroke="#c64026" stroke-width="28"></path>
      <path d="M 57 47 A 70 70 0 0 1 86 31" fill="none" stroke="#d18a00" stroke-width="28"></path>
      <path d="M 86 31 A 70 70 0 0 1 124 31" fill="none" stroke="#d7bf1f" stroke-width="28"></path>
      <path d="M 124 31 A 70 70 0 0 1 175 98" fill="none" stroke="#17724f" stroke-width="28"></path>
      <circle cx="105" cy="98" r="12" fill="#1d252b"></circle>
      <line class="gauge-needle" x1="105" y1="98" x2="105" y2="34" stroke="#1d252b" stroke-width="6" stroke-linecap="round"></line>
    </svg>
  `;
}

function renderFields() {
  document.querySelectorAll("[data-field]").forEach((node) => {
    const key = node.dataset.field;
    node.textContent = fields[key] ?? "--";
  });

  renderBars();
}

function renderStatuses() {
  const mappings = {
    power: document.getElementById("status-power"),
    cooling: document.getElementById("status-cooling"),
    controller: document.getElementById("status-controller"),
    comms: document.getElementById("status-comms"),
  };

  Object.entries(mappings).forEach(([key, element]) => {
    const { text, tone } = statusConfig[key];
    element.textContent = text;
    element.className = `badge ${tone}`;
  });
}

function resolveTone(value, config) {
  if (typeof value !== "number" || Number.isNaN(value) || !config) {
    return "tone-ok";
  }

  if (config.alertAbove !== undefined && value >= config.alertAbove) {
    return "tone-alert";
  }

  if (config.alertBelow !== undefined && value <= config.alertBelow) {
    return "tone-alert";
  }

  if (config.warnAbove !== undefined && value >= config.warnAbove) {
    return "tone-warn";
  }

  if (config.warnBelow !== undefined && value <= config.warnBelow) {
    return "tone-warn";
  }

  return "tone-ok";
}

function normaliseWidth(value, config) {
  if (typeof value !== "number" || Number.isNaN(value) || !config) {
    return 100;
  }

  const ratio = ((value - config.min) / (config.max - config.min)) * 100;
  return Math.max(6, Math.min(100, ratio));
}

function renderBars() {
  document.querySelectorAll("[data-bar]").forEach((node) => {
    const key = node.dataset.bar;
    const rawValue = fields[key];
    const numericValue = typeof rawValue === "string" ? Number.parseFloat(rawValue) : rawValue;
    const config = barConfig[key];

    if (!config) {
      node.style.width = "100%";
      node.className = rawValue === "Warning" ? "tone-warn" : "tone-ok";
      if (rawValue === "Fault" || rawValue === "Critical") {
        node.className = "tone-alert";
      }
      return;
    }

    node.style.width = `${normaliseWidth(numericValue, config)}%`;
    node.className = resolveTone(numericValue, config);
  });

  document.querySelectorAll("[data-gauge]").forEach((node) => {
    const key = node.dataset.gauge;
    const rawValue = fields[key];
    const numericValue = typeof rawValue === "string" ? Number.parseFloat(rawValue) : rawValue;
    const config = barConfig[key];
    const percent = normaliseWidth(numericValue, config);
    const angle = -90 + (percent / 100) * 180;
    const previousAngle = gaugeState[key] ?? angle;
    const smoothedAngle = previousAngle + (angle - previousAngle) * 0.45;
    gaugeState[key] = smoothedAngle;
    const needle = node.querySelector(".gauge-needle");
    if (needle) {
      needle.style.transform = `rotate(${smoothedAngle}deg)`;
    }
  });

  renderWatchList();
}

function getAlertState(value, config) {
  if (typeof value !== "number" || Number.isNaN(value) || !config) {
    return null;
  }

  if (
    (config.alertAbove !== undefined && value >= config.alertAbove) ||
    (config.alertBelow !== undefined && value <= config.alertBelow)
  ) {
    return "critical";
  }

  if (
    (config.warnAbove !== undefined && value >= config.warnAbove) ||
    (config.warnBelow !== undefined && value <= config.warnBelow)
  ) {
    return "warning";
  }

  return null;
}

function renderWatchList() {
  const watchList = document.getElementById("watch-list");
  const alerts = [];

  Object.entries(barConfig).forEach(([key, config]) => {
    const rawValue = fields[key];
    const numericValue = typeof rawValue === "string" ? Number.parseFloat(rawValue) : rawValue;
    const state = getAlertState(numericValue, config);

    if (state !== "critical") {
      return;
    }

    alerts.push({
      state,
      value: numericValue,
      label: metricLabels[key]?.title ?? key,
      unit: metricLabels[key]?.unit ?? "",
    });
  });

  alerts.sort((a, b) => {
    if (a.state !== b.state) {
      return a.state === "critical" ? -1 : 1;
    }
    return b.value - a.value;
  });

  watchList.innerHTML = "";

  if (!alerts.length) {
    watchList.innerHTML = `
      <div class="watch-item watch-item-neutral">
        <div>
          <strong>Aucun point critique actif</strong>
          <p>Seules les valeurs critiques instantanees apparaitront ici automatiquement.</p>
        </div>
        <span class="watch-badge">Stable</span>
      </div>
    `;
    return;
  }

  alerts.forEach((alert) => {
    const item = document.createElement("div");
    item.className = `watch-item ${alert.state === "critical" ? "watch-item-critical" : "watch-item-warning"}`;
    item.innerHTML = `
      <div>
        <strong>${alert.label}</strong>
        <p>Valeur actuelle : ${alert.value} ${alert.unit}</p>
      </div>
      <span class="watch-badge">Critique</span>
    `;
    watchList.appendChild(item);
  });
}

function stampUpdate() {
  if (!lastTelemetryAt) {
    document.getElementById("last-update").textContent = "--:--:--";
    return;
  }

  const formatter = new Intl.DateTimeFormat("fr-FR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

  const elapsedSeconds = Math.max(0, Math.round((Date.now() - lastTelemetryAt.getTime()) / 1000));
  const suffix = elapsedSeconds <= 1 ? "a l'instant" : `il y a ${elapsedSeconds}s`;
  document.getElementById("last-update").textContent = `${formatter.format(lastTelemetryAt)} (${suffix})`;
}

function initialisePlaceholderState() {
  document.querySelectorAll("[data-gauge]").forEach((node) => {
    node.innerHTML = createGaugeMarkup();
  });
  renderFields();
  renderStatuses();
  stampUpdate();
}

function appendEvent(message) {
  const eventList = document.getElementById("event-list");
  const item = document.createElement("li");
  item.textContent = message;
  eventList.prepend(item);

  while (eventList.children.length > 6) {
    eventList.removeChild(eventList.lastElementChild);
  }
}

function setConnectionState(connected) {
  document.getElementById("link-state").textContent = connected ? "Connectee" : "Non connectee";
  document.getElementById("mission-state").textContent = connected
    ? "Flux telemetrique actif"
    : "En attente de telemetrie";
  document.getElementById("alert-state").textContent = connected
    ? "Surveillance nominale"
    : "Aucune alerte active";

  statusConfig.comms = connected
    ? { text: "Operationnelle", tone: "ok" }
    : { text: "En attente", tone: "neutral" };

  renderStatuses();
  stampUpdate();
}

function markTelemetryUpdate() {
  lastTelemetryAt = new Date();
  stampUpdate();
}

window.dashboardBridge = {
  updateTelemetry(nextFields = {}) {
    Object.assign(fields, nextFields);
    renderFields();
    updateMap();
    markTelemetryUpdate();
  },
  updateStatuses(nextStatuses = {}) {
    Object.entries(nextStatuses).forEach(([key, value]) => {
      if (statusConfig[key]) {
        statusConfig[key] = value;
      }
    });
    renderStatuses();
    stampUpdate();
  },
  pushEvent(message) {
    appendEvent(message);
    stampUpdate();
  },
  setConnectionState,
};

function initMap() {
  const defaultPos = [48.3, 3.5];
  map = L.map("map").setView(defaultPos, 13);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    attribution: "&copy; OpenStreetMap",
    maxZoom: 19,
  }).addTo(map);

  boatMarker = L.marker(defaultPos).addTo(map).bindPopup("Bateau Nereides");
  boatTrail = L.polyline([], { color: "#006d7e", weight: 3, opacity: 0.7 }).addTo(map);
}

function updateMap() {
  const lat = parseFloat(fields.gps_lat);
  const lng = parseFloat(fields.gps_lng);
  if (isNaN(lat) || isNaN(lng) || (lat === 0 && lng === 0)) return;

  const pos = [lat, lng];
  boatMarker.setLatLng(pos);
  boatTrail.addLatLng(pos);
  map.setView(pos);
}

initialisePlaceholderState();
initMap();

appendEvent("Interface chargee. API/WebSocket/MQTT a connecter ulterieurement.");

function handleRealtimeMessage(payload) {
  if (payload.fields) {
    window.dashboardBridge.updateTelemetry(payload.fields);
  }

  if (payload.statuses) {
    window.dashboardBridge.updateStatuses(payload.statuses);
  }

  if (payload.event) {
    window.dashboardBridge.pushEvent(payload.event);
  }

  if (typeof payload.connected === "boolean") {
    window.dashboardBridge.setConnectionState(payload.connected);
  }
}

function scheduleReconnect() {
  clearTimeout(reconnectTimer);
  reconnectTimer = window.setTimeout(connectRealtime, 2000);
}

function checkStaleness() {
  if (lastTelemetryAt) {
    const elapsed = (Date.now() - lastTelemetryAt.getTime()) / 1000;
    if (elapsed > 5) {
      window.dashboardBridge.setConnectionState(false);
      window.dashboardBridge.pushEvent("Donnees stale — aucune trame depuis 5s.");
    }
  }
}

function connectRealtime() {
  socket = new WebSocket(backendWsUrl);

  socket.addEventListener("open", () => {
    window.dashboardBridge.setConnectionState(true);
    window.dashboardBridge.pushEvent("Canal temps reel connecte au backend local.");
  });

  socket.addEventListener("message", (event) => {
    try {
      handleRealtimeMessage(JSON.parse(event.data));
    } catch (error) {
      window.dashboardBridge.pushEvent("Message temps reel recu dans un format invalide.");
    }
  });

  socket.addEventListener("close", () => {
    window.dashboardBridge.setConnectionState(false);
    window.dashboardBridge.pushEvent("Connexion backend perdue. Nouvelle tentative en cours.");
    scheduleReconnect();
  });

  socket.addEventListener("error", () => {
    socket.close();
  });
}

async function pollLatestTelemetry() {
  try {
    const response = await fetch(`${backendHttpUrl}/latest`, { cache: "no-store" });
    if (!response.ok) {
      throw new Error("Backend HTTP indisponible");
    }

    const payload = await response.json();
    handleRealtimeMessage(payload);
  } catch (error) {
    window.dashboardBridge.setConnectionState(false);
  }
}

function startPolling() {
  clearInterval(pollTimer);
  pollTimer = window.setInterval(pollLatestTelemetry, 500);
  pollLatestTelemetry();
}

function startAgeTicker() {
  clearInterval(ageTimer);
  ageTimer = window.setInterval(() => {
    stampUpdate();
    checkStaleness();
  }, 1000);
}

connectRealtime();
startPolling();
startAgeTicker();
