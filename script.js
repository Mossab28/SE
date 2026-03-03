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
};

const statusConfig = {
  power: { text: "En attente", tone: "neutral" },
  cooling: { text: "En attente", tone: "neutral" },
  controller: { text: "En attente", tone: "neutral" },
  comms: { text: "En attente", tone: "neutral" },
};

function renderFields() {
  document.querySelectorAll("[data-field]").forEach((node) => {
    const key = node.dataset.field;
    node.textContent = fields[key] ?? "--";
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
    const { text, tone } = statusConfig[key];
    element.textContent = text;
    element.className = `badge ${tone}`;
  });
}

function stampUpdate() {
  const formatter = new Intl.DateTimeFormat("fr-FR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  document.getElementById("last-update").textContent = formatter.format(new Date());
}

function initialisePlaceholderState() {
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

window.dashboardBridge = {
  updateTelemetry(nextFields = {}) {
    Object.assign(fields, nextFields);
    renderFields();
    stampUpdate();
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

initialisePlaceholderState();

appendEvent("Interface chargee. API/WebSocket/MQTT a connecter ulterieurement.");
