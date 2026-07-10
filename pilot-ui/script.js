const fields = {
  battery1_soc: "--",
  battery1_temp: "--",
  battery1_current: "--",
  battery2_soc: "--",
  battery2_temp: "--",
  battery2_current: "--",
  controller_temperature: "--",
  controller_current: "--",
  motor_power: "--",
  controller_safety: "--",
  gps_speed_kmh: "--",
  gps_speed_kmh_exact: "--",
  gps_lat: null,
  gps_lng: null,
  gps_satellites: null,
  solar_temperature: "--",
};

// Seuils d'alerte : la case passe orange (warn) puis rouge (alert)
const TONE_RULES = {
  battery1_temp: { warn: 48, alert: 53 },
  battery2_temp: { warn: 48, alert: 53 },
  controller_temperature: { warn: 70, alert: 85 },
  solar_temperature: { warn: 65, alert: 80 },
};

const statusConfig = {
  power: { text: "En attente", tone: "neutral" },
  cooling: { text: "En attente", tone: "neutral" },
  controller: { text: "En attente", tone: "neutral" },
  comms: { text: "En attente", tone: "neutral" },
};

const RANDOM_TONES = ["tone-ok", "tone-warn", "tone-alert"];

let socket = null;
let reconnectTimer = null;
let ageTimer = null;
let lastTelemetryAt = null;
let hasLiveTelemetry = false;
const temporaryToneMap = {};

// WebSocket local (ecran.py sur le meme Raspberry Pi)
const WS_URL = "ws://localhost:8765";
let displayOverlayTimer = null;

function showDisplayOverlay(payload) {
  const overlay = document.getElementById("display-overlay");
  const imageNode = document.getElementById("display-overlay-image");
  const textNode = document.getElementById("display-overlay-text");
  if (!overlay || !imageNode || !textNode) {
    return;
  }

  if (payload.image_url) {
    imageNode.src = payload.image_url;
    imageNode.hidden = false;
  } else {
    imageNode.hidden = true;
    imageNode.removeAttribute("src");
  }

  textNode.textContent = payload.text || "";
  overlay.hidden = false;

  clearTimeout(displayOverlayTimer);
  // Duree bornee (1s a 30s) : l'UI pilote est critique, l'overlay DOIT se refermer tout seul.
  const durationMs = Math.min(30, Math.max(1, Number(payload.duration_s) || 5)) * 1000;
  displayOverlayTimer = window.setTimeout(function() {
    overlay.hidden = true;
  }, durationMs);
}


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

// Ton réel selon les seuils (ou "" si pas de règle / pas de valeur numérique)
function toneFor(key) {
  const rule = TONE_RULES[key];
  const v = parseFloat(fields[key]);
  if (!rule || Number.isNaN(v)) {
    return "";
  }
  if (v >= rule.alert) {
    return "tone-alert";
  }
  if (rule.warn !== undefined && v >= rule.warn) {
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

function derivePilotFields(raw) {
  const batterySoc =
    raw.battery_soc ??
    (typeof raw.battery_voltage === "number"
      ? Math.max(0, Math.min(100, Math.round(((raw.battery_voltage - 44) / (54 - 44)) * 100)))
      : null);

  const controllerTemperature = raw.controller_temperature ?? raw.cm_temperature ?? raw.motor_temperature ?? null;
  const controllerCurrent = raw.controller_current ?? raw.motor_current ?? raw.cm_current ?? null;
  const controllerSafety = raw.controller_safety ?? raw.controller_fnb ?? "--";
  // Puissance moteur = tension x courant (W)
  const mv = raw.motor_voltage ?? raw.cm_voltage ?? null;
  const mi = raw.motor_current ?? raw.controller_current ?? null;
  const motorPower = (typeof mv === "number" && typeof mi === "number")
    ? Math.round(mv * mi)
    : null;

  const rawSpeedKmh = raw.gps_speed_kmh ?? raw.gps_speed ?? null;

  return {
    gps_speed_kmh: (rawSpeedKmh ?? 0) * 0.539957,
    gps_speed_kmh_exact: rawSpeedKmh,
    solar_temperature: raw.solar_temperature ?? null,
    controller_safety: controllerSafety,
    // Batterie 1 (branche parallele)
    battery1_soc: raw.battery1_soc ?? null,
    battery1_temp: raw.battery1_temp ?? null,
    battery1_current: raw.battery1_current ?? null,
    // Batterie 2 (branche parallele)
    battery2_soc: raw.battery2_soc ?? null,
    battery2_temp: raw.battery2_temp ?? null,
    battery2_current: raw.battery2_current ?? null,
    controller_temperature: controllerTemperature,
    controller_current: controllerCurrent,
    motor_power: motorPower,
    gps_lat: raw.gps_lat ?? null,
    gps_lng: raw.gps_lng ?? null,
    gps_satellites: raw.gps_satellites ?? null,
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

  // Vitesse exacte en km/h (2 decimales), affichee en petit a cote des noeuds
  document.querySelectorAll("[data-field-precise]").forEach((node) => {
    const key = node.dataset.fieldPrecise;
    const v = fields[key];
    node.textContent = typeof v === "number" ? `${v.toFixed(2)} km/h` : "-- km/h";
  });

  document.querySelectorAll("[data-tone-target]").forEach((node) => {
    const key = node.dataset.toneTarget;
    node.classList.remove("tone-ok", "tone-warn", "tone-alert");
    const tone = toneFor(key);
    if (tone) {
      node.classList.add(tone);
    }
  });

  // Alerte par case : orange (warn) / rouge (alert) selon les seuils
  document.querySelectorAll("[data-alert]").forEach((node) => {
    const tone = toneFor(node.dataset.alert);
    node.classList.toggle("cell-warn", tone === "tone-warn");
    node.classList.toggle("cell-hot", tone === "tone-alert");
  });

  updateGpsStatus();
}

// Statut du fix GPS, affiche a la place de l'ancien "Pilotage actif"
function updateGpsStatus() {
  const sat = fields.gps_satellites;
  const satText = typeof sat === "number" ? `${sat} sat` : "";
  let text;
  if (!hasLiveTelemetry) {
    text = "En attente de donnees";
  } else if (typeof fields.gps_lat === "number" && typeof fields.gps_lng === "number") {
    text = satText ? `Fix acquis (${satText})` : "Fix acquis";
  } else {
    text = satText ? `Recherche fix... (${satText})` : "Recherche fix...";
  }
  setText("mission-state", text);
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
    element.className = "badge " + tone;
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
  setText("alert-state", "Nominal");

  statusConfig.comms = connected
    ? { text: "Operationnelle", tone: "ok" }
    : { text: "En attente", tone: "neutral" };

  renderStatuses();
  updateGpsStatus();
}

function applyPayload(payload) {
  const nextFields = derivePilotFields(payload.fields || {});
  const hasMeaningfulFields = hasUsableFieldData(nextFields);

  if (hasMeaningfulFields) {
    Object.keys(nextFields).forEach(function(k) {
      if (nextFields[k] !== null && nextFields[k] !== undefined && nextFields[k] !== "--") {
        fields[k] = nextFields[k];
      }
    });
    hasLiveTelemetry = true;
    lastTelemetryAt = new Date();
  }

  if (payload.statuses) {
    if (payload.statuses.power) statusConfig.power = payload.statuses.power;
    if (payload.statuses.cooling) statusConfig.cooling = payload.statuses.cooling;
    if (payload.statuses.controller) statusConfig.controller = payload.statuses.controller;
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
  socket = new WebSocket(WS_URL);

  socket.addEventListener("open", function() {
    setConnectionState(true);
    appendEvent("WebSocket local connecte.");
  });

  socket.addEventListener("message", function(event) {
    try {
      var raw = JSON.parse(event.data);
      if (raw.type === "display") {
        showDisplayOverlay(raw);
        return;
      }
      // ecran.py envoie du JSON plat, on le wrappe dans le format attendu
      applyPayload({
        connected: true,
        fields: raw,
        statuses: {
          power: { text: "Operationnelle", tone: "ok" },
          cooling: { text: "Nominal", tone: "ok" },
          controller: { text: "Nominal", tone: "ok" },
          comms: { text: "Operationnelle", tone: "ok" },
        },
      });
    } catch (error) {
      appendEvent("Message recu dans un format invalide.");
    }
  });

  socket.addEventListener("close", function() {
    setConnectionState(false);
    appendEvent("WebSocket perdu. Reconnexion...");
    scheduleReconnect();
  });

  socket.addEventListener("error", function() {
    if (socket) {
      socket.close();
    }
  });
}

function checkStaleness() {
  if (!lastTelemetryAt) {
    return;
  }

  var elapsedSeconds = (Date.now() - lastTelemetryAt.getTime()) / 1000;
  if (elapsedSeconds > 30) {
    setConnectionState(false);
  }
}

function initialise() {
  updatePilotCards();
  renderStatuses();
  stampUpdate();
}

initialise();
connectRealtime();
ageTimer = window.setInterval(checkStaleness, 1000);
