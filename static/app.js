const stateEl = document.querySelector("#state");
const logEl = document.querySelector("#log");
const exchangeEl = document.querySelector("#exchange");
const draftsEl = document.querySelector("#drafts");
const monitorsEl = document.querySelector("#monitors");
const chipsEl = document.querySelector("#chips");
const hintEl = document.querySelector("#hint");
const commandEl = document.querySelector("#command");

const view = {
  log: [],
  pending: [],
  monitors: [],
  transcript: "",
  reply: "",
  capabilities: {},
  state: "idle",
  detail: "",
};

function line(parent, text, className) {
  const node = document.createElement("div");
  if (className) node.className = className;
  node.textContent = text;
  parent.appendChild(node);
  return node;
}

function render() {
  stateEl.textContent = view.detail ? `${view.state} — ${view.detail}` : view.state;
  stateEl.dataset.kind = view.state;
  const micNote = view.capabilities.mic ? "" : ` ${view.capabilities.mic_error || "No microphone."}`;
  hintEl.textContent = `Hold ${view.capabilities.ptt_key || "f9"} or the button. Mail allowlist: ${(view.capabilities.email_allowlist || []).join(", ") || "none"}.${micNote}`;

  chipsEl.replaceChildren();
  const flags = [
    ["Gemini", view.capabilities.gemini],
    ["Mic", view.capabilities.mic],
    ["Speech", view.capabilities.tts],
    ["Push-to-talk", view.capabilities.ptt],
    ["Gmail file", view.capabilities.gmail_secret],
    ["Gmail", view.capabilities.gmail],
    ["Browser", view.capabilities.browser],
  ];
  for (const [label, on] of flags) {
    const chip = document.createElement("span");
    chip.className = `chip ${on ? "on" : "off"}`;
    chip.textContent = `${label} ${on ? "ready" : "missing"}`;
    chipsEl.appendChild(chip);
  }

  logEl.replaceChildren();
  for (const entry of view.log) {
    const row = document.createElement("div");
    row.className = `log-line ${entry.level === "error" ? "error" : ""}`;
    const time = document.createElement("span");
    time.className = "time";
    time.textContent = `${entry.time}  `;
    row.appendChild(time);
    row.appendChild(document.createTextNode(entry.message));
    logEl.appendChild(row);
  }
  logEl.scrollTop = logEl.scrollHeight;

  exchangeEl.replaceChildren();
  line(exchangeEl, view.transcript ? `You: ${view.transcript}` : "You: —");
  line(exchangeEl, view.reply ? `Agent: ${view.reply}` : "Agent: —");

  draftsEl.replaceChildren();
  if (!view.pending.length) line(draftsEl, "None.");
  for (const draft of view.pending) {
    const box = document.createElement("div");
    box.className = "draft";
    line(box, `To: ${draft.to}`);
    line(box, `Subject: ${draft.subject}`);
    line(box, draft.body);
    const row = document.createElement("div");
    row.className = "row";
    const approve = document.createElement("button");
    approve.type = "button";
    approve.textContent = "Approve send";
    approve.addEventListener("click", () => approveSend(draft));
    const drop = document.createElement("button");
    drop.type = "button";
    drop.textContent = "Dismiss";
    drop.addEventListener("click", () => post("/api/gmail/dismiss", { draft_id: draft.id }));
    row.append(approve, drop);
    box.appendChild(row);
    draftsEl.appendChild(box);
  }

  syncModel();

  monitorsEl.replaceChildren();
  if (!view.monitors.length) line(monitorsEl, "No results yet.");
  for (const item of view.monitors) {
    const box = document.createElement("div");
    box.className = "monitor";
    const status = document.createElement("div");
    status.className = item.ok ? "ok" : "bad";
    status.textContent = `${item.name}  ${item.status || "down"}  ${item.title || ""}`;
    box.appendChild(status);
    line(box, item.url);
    monitorsEl.appendChild(box);
  }
}

function syncModel() {
  const select = document.querySelector("#model");
  if (!select) return;
  const choices = view.capabilities.model_choices || [];
  const key = choices.map((choice) => choice.id).join(",");
  if (select.dataset.built !== key) {
    select.replaceChildren();
    for (const choice of choices) {
      const option = document.createElement("option");
      option.value = choice.id;
      option.textContent = choice.label;
      select.appendChild(option);
    }
    select.dataset.built = key;
  }
  if (document.activeElement !== select && view.capabilities.gemini_model) {
    select.value = view.capabilities.gemini_model;
  }
}

function apply(message) {
  if (message.type === "snapshot") {
    view.log = message.log || [];
    view.pending = message.pending || [];
    view.monitors = message.monitors || [];
    view.transcript = message.transcript || "";
    view.reply = message.reply || "";
    view.capabilities = message.capabilities || {};
    view.state = message.state || "idle";
    view.detail = message.detail || "";
  } else if (message.type === "state") {
    view.state = message.state;
    view.detail = message.detail || "";
  } else if (message.type === "log") {
    view.log.push(message.entry);
  } else if (message.type === "exchange") {
    view.transcript = message.transcript || "";
    view.reply = message.reply || "";
  } else if (message.type === "pending") {
    view.pending = message.pending || [];
  } else if (message.type === "monitors") {
    view.monitors = message.monitors || [];
  } else if (message.type === "capabilities") {
    view.capabilities = message.capabilities || {};
  }
  render();
}

function connect() {
  const socket = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  socket.addEventListener("message", (event) => apply(JSON.parse(event.data)));
  socket.addEventListener("close", () => setTimeout(connect, 1500));
  window.agentSocket = socket;
}

async function post(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    view.log.push({ time: "", level: "error", message: payload.error || response.statusText });
    render();
  }
  return payload;
}

async function approveSend(draft) {
  const ok = window.confirm(`Send this draft to ${draft.to}?`);
  if (!ok) return;
  await post("/api/gmail/approve", { draft_id: draft.id });
}

document.querySelector("#send").addEventListener("click", async () => {
  const text = commandEl.value.trim();
  if (!text) return;
  commandEl.value = "";
  const socket = window.agentSocket;
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: "command", text }));
  } else {
    await post("/api/command", { text });
  }
});

const hold = document.querySelector("#hold");
function ptt(phase) {
  const socket = window.agentSocket;
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: "ptt", phase }));
  }
}
hold.addEventListener("pointerdown", (event) => {
  event.preventDefault();
  hold.setPointerCapture(event.pointerId);
  hold.classList.add("hot");
  ptt("down");
});
function releaseHold() {
  if (!hold.classList.contains("hot")) return;
  hold.classList.remove("hot");
  ptt("up");
}
hold.addEventListener("pointerup", releaseHold);
hold.addEventListener("pointercancel", releaseHold);

document.querySelector("#model").addEventListener("change", (event) => {
  post("/api/model", { model: event.target.value });
});
document.querySelector("#refresh").addEventListener("click", () => post("/api/monitors/refresh"));
document.querySelector("#connect").addEventListener("click", () => post("/api/gmail/connect"));

connect();
render();
