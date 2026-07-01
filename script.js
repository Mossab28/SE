const fields = {
  battery_temperature: "--",
  battery_temp_min: "--",
  battery_voltage: "--",
  battery_current: "--",
  battery_power: "--",
  battery_soc: "--",
  battery1_soc: "--",
  battery1_voltage: "--",
  battery1_current: "--",
  battery2_soc: "--",
  battery2_voltage: "--",
  battery2_current: "--",
  motor_temperature: "--",
  motor_pressure: "--",
  motor_speed: "--",
  motor_torque: "--",
  motor_current: "--",
  motor_voltage: "--",
  controller_mode: "--",
  controller_temperature: "--",
  controller_power_request: "--",
  controller_efficiency: "--",
  controller_safety: "--",
  controller_fnb: "--",
  controller_feedback: "--",
  controller_error_code: "--",
  controller_throttle: "--",
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
  battery_soc: { min: 0, max: 100, warnBelow: 30, alertBelow: 15 },
  battery1_soc: { min: 0, max: 100, warnBelow: 30, alertBelow: 15 },
  battery2_soc: { min: 0, max: 100, warnBelow: 30, alertBelow: 15 },
  battery1_voltage: { min: 40, max: 55, warnBelow: 46, alertBelow: 44 },
  battery2_voltage: { min: 40, max: 55, warnBelow: 46, alertBelow: 44 },
  battery1_current: { min: 0, max: 120, warnAbove: 90, alertAbove: 110 },
  battery2_current: { min: 0, max: 120, warnAbove: 90, alertAbove: 110 },
  motor_temperature: { min: 0, max: 100, warnAbove: 75, alertAbove: 85 },
  motor_pressure: { min: 0, max: 4, warnBelow: 2, alertBelow: 1.5 },
  motor_speed: { min: 0, max: 3500, warnAbove: 2800, alertAbove: 3200 },
  motor_torque: { min: 0, max: 250, warnAbove: 180, alertAbove: 220 },
  controller_power_request: { min: 0, max: 100, warnAbove: 75, alertAbove: 90 },
  controller_efficiency: { min: 70, max: 100, warnBelow: 88, alertBelow: 82 },
  controller_temperature: { min: 0, max: 100, warnAbove: 70, alertAbove: 85 },
  controller_throttle: { min: 0, max: 5, warnAbove: 4.5, alertAbove: 4.8 },
};

const metricLabels = {
  battery_temperature: { title: "Temperature batteries", unit: "degC" },
  battery_voltage: { title: "Voltage pack", unit: "V" },
  battery_current: { title: "Courant pack", unit: "A" },
  battery_power: { title: "Puissance batterie", unit: "kW" },
  battery_soc: { title: "SOC pack", unit: "%" },
  battery1_soc: { title: "SOC batterie 1", unit: "%" },
  battery2_soc: { title: "SOC batterie 2", unit: "%" },
  battery1_current: { title: "Courant batterie 1", unit: "A" },
  battery2_current: { title: "Courant batterie 2", unit: "A" },
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

// ── Chart state (must be declared before initSpeedChart is called) ────────────
const MAX_CHART_POINTS = 120;
const _chartLabels = [];
const _actualSpeeds = [];
const _recommendedSpeeds = [];
let _speedChart = null;
let _lastRecommended = null;
const backendHost = window.location.host || "nereides.pwn-ai.fr";
const wsProto = window.location.protocol === "https:" ? "wss:" : "ws:";
const backendHttpUrl = `${window.location.protocol}//${backendHost}/backend`;
const backendWsUrl = `${wsProto}//${backendHost}/backend/ws`;

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
    // Feed actual speed into the chart on every telemetry frame
    const v = parseFloat(nextFields.gps_speed_kmh);
    if (!isNaN(v)) pushChartPoint(v, _lastRecommended);
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
initSpeedChart();
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

// ── Speed Chart ───────────────────────────────────────────────────────────────
function initSpeedChart() {
  const canvas = document.getElementById("speed-chart");
  if (!canvas || !window.Chart) return;
  _speedChart = new Chart(canvas.getContext("2d"), {
    type: "line",
    data: {
      labels: _chartLabels,
      datasets: [
        {
          label: "Vitesse reelle",
          data: _actualSpeeds,
          borderColor: "#4a9eff",
          backgroundColor: "rgba(74,158,255,0.08)",
          fill: true,
          tension: 0.35,
          pointRadius: 0,
          borderWidth: 2,
        },
        {
          label: "Vitesse preconisee IA",
          data: _recommendedSpeeds,
          borderColor: "#f5a623",
          backgroundColor: "transparent",
          borderDash: [6, 3],
          tension: 0.15,
          pointRadius: 0,
          borderWidth: 2,
        },
      ],
    },
    options: {
      animation: false,
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      scales: {
        x: {
          ticks: { color: "#6b7f8c", maxTicksLimit: 8, font: { size: 11 } },
          grid: { color: "rgba(255,255,255,0.04)" },
        },
        y: {
          min: 0,
          ticks: { color: "#6b7f8c", font: { size: 11 } },
          grid: { color: "rgba(255,255,255,0.06)" },
          title: { display: true, text: "km/h", color: "#6b7f8c", font: { size: 11 } },
        },
      },
      plugins: {
        legend: {
          labels: { color: "#a0b3bf", font: { size: 12 }, boxWidth: 18 },
        },
      },
    },
  });
}

function pushChartPoint(actualSpeed, recommendedSpeed) {
  const now = new Date();
  const label = now.toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  _chartLabels.push(label);
  _actualSpeeds.push(typeof actualSpeed === "number" ? actualSpeed : null);
  _recommendedSpeeds.push(recommendedSpeed !== undefined ? recommendedSpeed : _lastRecommended);

  if (_chartLabels.length > MAX_CHART_POINTS) {
    _chartLabels.shift();
    _actualSpeeds.shift();
    _recommendedSpeeds.shift();
  }
  if (_speedChart) _speedChart.update("none");
}

// ── AI Predictions ────────────────────────────────────────────────────────────
function fmtSeconds(s) {
  if (s == null || s < 0) return "--:--:--";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
}

function renderWeather(wx) {
  if (!wx) return;
  document.getElementById("w-temp").textContent =
    wx.temperature_c != null ? wx.temperature_c.toFixed(1) : "--";
  document.getElementById("w-wind").textContent =
    wx.wind_speed_ms != null ? wx.wind_speed_ms.toFixed(1) : "--";
  document.getElementById("w-humid").textContent =
    wx.humidity_pct != null ? wx.humidity_pct : "--";
  document.getElementById("w-pressure").textContent =
    wx.pressure_hpa != null ? Math.round(wx.pressure_hpa) : "--";
}

function renderPredictions(data) {
  if (!data) return;

  // Weather renders regardless of boat status
  renderWeather(data.weather);

  if (data.status === "waiting" || data.status === "unavailable") return;

  // Priority badge
  const badge = document.getElementById("ai-priority-badge");
  if (badge) {
    const map = { ok: ["Nominal", "ok"], warn: ["Attention", "warn"], alert: ["Alerte", "alert"] };
    const [text, tone] = map[data.priority] || ["--", "neutral"];
    badge.textContent = text;
    badge.className = `badge ${tone}`;
  }

  // Sync recommended speed for chart
  if (data.recommended_speed_kmh != null) {
    _lastRecommended = data.recommended_speed_kmh;
  }

  // Endurance
  const end = data.endurance;
  document.getElementById("ai-endurance").textContent =
    end ? fmtSeconds(end.time_remaining_s) : "--:--:--";
  document.getElementById("ai-range").textContent =
    end?.range_km != null ? end.range_km.toFixed(1) : "--";
  document.getElementById("ai-energy").textContent =
    end?.energy_remaining_wh != null ? end.energy_remaining_wh : "--";

  // Thermal alerts
  const thermalEl = document.getElementById("ai-thermal");
  if (thermalEl) {
    const alerts = [];
    if (data.battery_thermal_alert) {
      const a = data.battery_thermal_alert;
      alerts.push(
        `<p class="ai-thermal-warn">Batterie : seuil ${a.threshold_c}degC dans ${fmtSeconds(a.seconds_left)} (${a.rate_c_per_min} degC/min)</p>`
      );
    }
    if (data.motor_thermal_alert) {
      const a = data.motor_thermal_alert;
      alerts.push(
        `<p class="ai-thermal-warn">Moteur : seuil ${a.threshold_c}degC dans ${fmtSeconds(a.seconds_left)} (${a.rate_c_per_min} degC/min)</p>`
      );
    }
    thermalEl.innerHTML =
      alerts.length > 0
        ? alerts.join("")
        : '<p class="ai-thermal-ok">Aucune alerte thermique prevue</p>';
  }

  // Recommendations
  const recsEl = document.getElementById("ai-recs");
  if (recsEl && Array.isArray(data.recommendations)) {
    recsEl.innerHTML = data.recommendations
      .map((r) => `<li>${r}</li>`)
      .join("");
  }
}

const VPS_PREDICTIONS_URL = "https://nereides.pwn-ai.fr/backend/predictions";

async function pollPredictions() {
  const urls = [
    `${backendHttpUrl}/predictions`,
    VPS_PREDICTIONS_URL,
  ];
  for (const url of [...new Set(urls)]) {
    try {
      const resp = await fetch(url, { cache: "no-store" });
      if (resp.ok) {
        const data = await resp.json();
        console.log("[IA] predictions reçues:", data?.weather, "status:", data?.status);
        renderPredictions(data);
        return;
      }
      console.warn("[IA] predictions HTTP", resp.status, url);
    } catch (err) {
      console.warn("[IA] predictions fetch error:", url, err.message);
    }
  }
}

window.setInterval(pollPredictions, 5000);
pollPredictions();
