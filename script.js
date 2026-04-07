const fields = {
  battery_soc: "--",
  battery_temperature: "--",
  battery_current: "--",
  controller_temperature: "--",
  controller_current: "--",
  controller_safety: "--",
  gps_speed_kmh: "--",
};

const statusConfig = {
  power: { text: "En attente", tone: "neutral" },
  cooling: { text: "En attente", tone: "neutral" },
  controller: { text: "En attente", tone: "neutral" },
  comms: { text: "En attente", tone: "neutral" },
};

const RANDOM_TONES = ["tone-ok", "tone-warn", "tone-alert"];

const DEMO_PAYLOAD = {
  connected: true,
  statuses: {
    power: { text: "Operationnelle", tone: "ok" },
    cooling: { text: "Nominal", tone: "ok" },
    controller: { text: "Nominal", tone: "ok" },
    comms: { text: "Operationnelle", tone: "ok" },
  },
  fields: {
    gps_speed_kmh: 12.8,
    controller_safety: "Nominal",
    battery_soc: 78,
    battery_temperature: 34.6,
    battery_current: 18.4,
    controller_temperature: 41.2,
    controller_current: 15.7,
  },
};

let socket = null;
let reconnectTimer = null;
let pollTimer = null;
let ageTimer = null;
let lastTelemetryAt = null;
let hasLiveTelemetry = false;
const temporaryToneMap = {};

const backendHost = "212.227.88.180";
const backendHttpUrl = `http://${backendHost}/backend`;
const backendWsUrl = `ws://${backendHost}/ws`;

function setText(id, value) {
  const node = document.getElementById(id);
  if (node) {
    node.textContent = value;
  }
}

function appendEvent(message) {
  const eventList = document.getElementById("event-list");
  if (!eventList) {
    return;
  }

  const item = document.createElement("li");
  item.textContent = message;
  eventList.prepend(item);

  while (eventList.children.length > 5) {
    eventList.removeChild(eventList.lastElementChild);
  }
}

function getTemporaryTone(key) {
  if (!temporaryToneMap[key]) {
    const index = Math.floor(Math.random() * RANDOM_TONES.length);
    temporaryToneMap[key] = RANDOM_TONES[index];
  }

  return temporaryToneMap[key];
}

function formatValue(key, value) {
  if (value === null || value === undefined || value === "") {
    return "--";
  }

  if (typeof value === "number") {
    if (key === "controller_safety") {
      return String(value);
    }

    if (Number.isInteger(value)) {
      return String(value);
    }

    return value.toFixed(1);
  }

  return String(value);
}

function derivePilotFields(raw = {}) {
  const batterySoc =
    raw.battery_soc ??
    (typeof raw.battery_voltage === "number"
      ? Math.max(0, Math.min(100, Math.round(((raw.battery_voltage - 44) / (54 - 44)) * 100)))
      : null);

  const controllerTemperature = raw.controller_temperature ?? raw.cm_temperature ?? raw.motor_temperature ?? null;
  const controllerCurrent = raw.controller_current ?? raw.cm_current ?? raw.controller_power_request ?? null;
  const controllerSafety = raw.controller_safety ?? raw.cm_fnb ?? "--";

  return {
    gps_speed_kmh: raw.gps_speed_kmh ?? raw.gps_speed ?? 0,
    controller_safety: controllerSafety,
    battery_soc: batterySoc,
    battery_temperature: raw.battery_temperature ?? null,
    battery_current: raw.battery_current ?? null,
    controller_temperature: controllerTemperature,
    controller_current: controllerCurrent,
  };
}

function hasUsableFieldData(nextFields) {
  return Object.values(nextFields).some((value) => value !== null && value !== undefined && value !== "--");
}

function updatePilotCards() {
  document.querySelectorAll("[data-field]").forEach((node) => {
    const key = node.dataset.field;
    node.textContent = formatValue(key, fields[key]);
  });

  document.querySelectorAll("[data-tone-target]").forEach((node) => {
    const key = node.dataset.toneTarget;
    node.classList.remove("tone-ok", "tone-warn", "tone-alert");
    node.classList.add(getTemporaryTone(key));
  });
}

function renderStatuses() {
  const mappings = {
    power: document.getElementById("status-power"),
    cooling: document.getElementById("status-cooling"),
    controller: document.getElementById("status-controller"),
    comms: document.getElementById("status-comms"),
  };

  Object.entries(mappings).forEach(([key, element]) => {
    if (!element) {
      return;
    }

    const { text, tone } = statusConfig[key];
    element.textContent = text;
    element.className = `badge ${tone}`;
  });
}

function stampUpdate() {
  if (!lastTelemetryAt) {
    setText("last-update", "--:--:--");
    return;
  }

  const formatter = new Intl.DateTimeFormat("fr-FR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

  setText("last-update", formatter.format(lastTelemetryAt));
}

function setConnectionState(connected) {
  setText("link-state", connected ? "Connectee" : "Non connectee");
  setText("mission-state", connected ? "Pilotage actif" : "Mode demo");
  setText("alert-state", "Nominal");

  statusConfig.comms = connected
    ? { text: "Operationnelle", tone: "ok" }
    : { text: "En attente", tone: "neutral" };

  renderStatuses();
}

function applyPayload(payload) {
  const nextFields = derivePilotFields(payload.fields || {});
  const hasMeaningfulFields = hasUsableFieldData(nextFields);

  if (hasMeaningfulFields) {
    Object.assign(fields, nextFields);
    hasLiveTelemetry = true;
    lastTelemetryAt = new Date();
  }

  if (payload.statuses?.power) {
    statusConfig.power = payload.statuses.power;
  }

  if (payload.statuses?.cooling) {
    statusConfig.cooling = payload.statuses.cooling;
  }

  if (payload.statuses?.controller) {
    statusConfig.controller = payload.statuses.controller;
  }

  if (typeof payload.connected === "boolean") {
    setConnectionState(hasLiveTelemetry ? payload.connected : false);
  }

  if (payload.event) {
    appendEvent(payload.event);
  }

  updatePilotCards();
  renderStatuses();
  stampUpdate();
}

function scheduleReconnect() {
  clearTimeout(reconnectTimer);
  reconnectTimer = window.setTimeout(connectRealtime, 2000);
}

function connectRealtime() {
  socket = new WebSocket(backendWsUrl);

  socket.addEventListener("open", () => {
    setConnectionState(true);
    appendEvent("Canal temps reel connecte.");
  });

  socket.addEventListener("message", (event) => {
    try {
      applyPayload(JSON.parse(event.data));
    } catch (error) {
      appendEvent("Message recu dans un format invalide.");
    }
  });

  socket.addEventListener("close", () => {
    setConnectionState(false);
    appendEvent("Connexion backend perdue. Nouvelle tentative.");
    scheduleReconnect();
  });

  socket.addEventListener("error", () => {
    if (socket) {
      socket.close();
    }
  });
}

async function pollLatestTelemetry() {
  try {
    const response = await fetch(`${backendHttpUrl}/latest`, { cache: "no-store" });
    if (!response.ok) {
      throw new Error("Backend HTTP indisponible");
    }

    const payload = await response.json();
    applyPayload(payload);
  } catch (error) {
    if (!hasLiveTelemetry) {
      setConnectionState(false);
    }
  }
}

function checkStaleness() {
  if (!lastTelemetryAt) {
    return;
  }

  const elapsedSeconds = (Date.now() - lastTelemetryAt.getTime()) / 1000;
  if (elapsedSeconds > 5) {
    setConnectionState(false);
  }
}

function initialise() {
  updatePilotCards();
  renderStatuses();
  stampUpdate();
  applyPayload(DEMO_PAYLOAD);
  hasLiveTelemetry = false;
}

initialise();
connectRealtime();
pollLatestTelemetry();
pollTimer = window.setInterval(pollLatestTelemetry, 1000);
ageTimer = window.setInterval(checkStaleness, 1000);
