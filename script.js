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

const toneRules = {
  gps_speed_kmh: { warnBelow: 1, alertBelow: 0.1 },
  battery_soc: { warnBelow: 35, alertBelow: 20 },
  battery_temperature: { warnAbove: 40, alertAbove: 46 },
  battery_current: { warnAbove: 120, alertAbove: 160 },
  controller_temperature: { warnAbove: 70, alertAbove: 82 },
  controller_current: { warnAbove: 20, alertAbove: 28 },
};

let socket = null;
let reconnectTimer = null;
let pollTimer = null;
let ageTimer = null;
let lastTelemetryAt = null;

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

function resolveTone(value, config) {
  if (typeof value !== "number" || Number.isNaN(value) || !config) {
    return "tone-neutral";
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

function updatePilotCards() {
  document.querySelectorAll("[data-field]").forEach((node) => {
    const key = node.dataset.field;
    node.textContent = formatValue(key, fields[key]);
  });

  document.querySelectorAll("[data-tone-target]").forEach((node) => {
    const key = node.dataset.toneTarget;
    const value = typeof fields[key] === "string" ? Number.parseFloat(fields[key]) : fields[key];
    node.classList.remove("tone-ok", "tone-warn", "tone-alert");

    if (key === "controller_safety") {
      const safety = String(fields[key] ?? "").toLowerCase();
      if (["fault", "critical", "defaut"].includes(safety)) {
        node.classList.add("tone-alert");
      } else if (["warning", "warn", "trip"].includes(safety)) {
        node.classList.add("tone-warn");
      } else if (safety && safety !== "--") {
        node.classList.add("tone-ok");
      }
      return;
    }

    const tone = resolveTone(value, toneRules[key]);
    if (tone !== "tone-neutral") {
      node.classList.add(tone);
    }
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
  setText("mission-state", connected ? "Flux pilote actif" : "En attente de telemetrie");
  setText("alert-state", connected ? "Lecture temps reel disponible" : "Aucune trame recente");

  statusConfig.comms = connected
    ? { text: "Operationnelle", tone: "ok" }
    : { text: "En attente", tone: "neutral" };

  renderStatuses();
}

function applyPayload(payload) {
  const nextFields = derivePilotFields(payload.fields || {});
  Object.assign(fields, nextFields);

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
    setConnectionState(payload.connected);
  }

  if (payload.event) {
    appendEvent(payload.event);
  }

  lastTelemetryAt = new Date();
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
    setConnectionState(false);
  }
}

function checkStaleness() {
  if (!lastTelemetryAt) {
    return;
  }

  const elapsedSeconds = (Date.now() - lastTelemetryAt.getTime()) / 1000;
  if (elapsedSeconds > 5) {
    setConnectionState(false);
    setText("alert-state", "Donnees stale depuis plus de 5 secondes");
  }
}

function initialise() {
  updatePilotCards();
  renderStatuses();
  stampUpdate();
  appendEvent("Interface pilote chargee pour viewport Raspberry Pi 480 x 800.");
}

initialise();
connectRealtime();
pollLatestTelemetry();
pollTimer = window.setInterval(pollLatestTelemetry, 1000);
ageTimer = window.setInterval(checkStaleness, 1000);
