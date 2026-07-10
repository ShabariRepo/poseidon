/* Poseidon UI — vanilla JS, no build step. */
const $ = (id) => document.getElementById(id);
const state = { sessionId: null, busy: false, presets: {}, thinkingEl: null };

/* ---------- boot ---------- */
async function init() {
  const s = await fetch("/api/state").then((r) => r.json());
  state.presets = s.presets;
  $("workdir").textContent = s.workdir;
  fillPresets(s);
  if (!s.configured) openSettings(s);
  const sess = await fetch("/api/sessions", { method: "POST" }).then((r) => r.json());
  state.sessionId = sess.session_id;
  openEvents();
  loadFiles(".");
  $("chat-input").focus();
}

/* ---------- events (SSE) ---------- */
function openEvents() {
  const es = new EventSource(`/api/events?session_id=${state.sessionId}`);
  es.onmessage = (e) => handleEvent(JSON.parse(e.data));
  es.onerror = () => {}; // EventSource auto-reconnects
}

function handleEvent(ev) {
  switch (ev.type) {
    case "turn_started":
      setThinking(true);
      break;
    case "assistant_message":
      setThinking(false);
      addMsg("assistant", ev.content);
      setThinking(state.busy);
      break;
    case "tool_call":
      setThinking(false);
      addToolChip(ev);
      logActivity(`→ ${ev.name}`, describeArgs(ev), "");
      setThinking(true);
      break;
    case "tool_result":
      logActivity(`← ${ev.name}`, ev.summary, ev.ok ? "ok" : "err");
      if (!ev.ok) addToolChip({ name: ev.name, error: ev.summary });
      break;
    case "approval_required":
      setThinking(false);
      renderApproval(ev);
      break;
    case "cost_update":
      updateCost(ev);
      break;
    case "error":
      setThinking(false);
      addMsg("error", ev.message);
      break;
    case "turn_complete":
      state.busy = false;
      setThinking(false);
      $("send-btn").disabled = false;
      loadFiles(currentPath); // refresh files pane after work
      break;
  }
}

/* ---------- chat ---------- */
$("chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("chat-input");
  const text = input.value.trim();
  if (!text || state.busy) return;
  addMsg("user", text);
  input.value = "";
  input.style.height = "auto";
  state.busy = true;
  $("send-btn").disabled = true;
  const r = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: state.sessionId, message: text }),
  });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    addMsg("error", err.detail || `request failed (${r.status})`);
    state.busy = false;
    $("send-btn").disabled = false;
  }
});

$("chat-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    $("chat-form").requestSubmit();
  }
});
$("chat-input").addEventListener("input", (e) => {
  e.target.style.height = "auto";
  e.target.style.height = Math.min(e.target.scrollHeight, 140) + "px";
});

function addMsg(kind, text) {
  const div = document.createElement("div");
  div.className = `msg ${kind}`;
  div.textContent = text;
  $("messages").appendChild(div);
  scrollChat();
}

function addToolChip(ev) {
  const div = document.createElement("div");
  div.className = "tool-chip";
  div.textContent = ev.error
    ? `⚠ ${ev.name}: ${ev.error}`
    : `🔧 ${ev.name} ${describeArgs(ev)}`;
  $("messages").appendChild(div);
  scrollChat();
}

function setThinking(on) {
  if (on && !state.thinkingEl) {
    const div = document.createElement("div");
    div.className = "thinking";
    div.textContent = "working";
    $("messages").appendChild(div);
    state.thinkingEl = div;
    scrollChat();
  } else if (!on && state.thinkingEl) {
    state.thinkingEl.remove();
    state.thinkingEl = null;
  }
}

function describeArgs(ev) {
  const a = ev.args || {};
  return a.path || a.command || a.url || "";
}

function scrollChat() {
  $("messages").scrollTop = $("messages").scrollHeight;
}

/* ---------- approvals ---------- */
function renderApproval(ev) {
  const card = document.createElement("div");
  card.className = "approval";
  const title = { write_file: "wants to write", edit_file: "wants to edit", run_command: "wants to run" }[ev.tool] || `wants: ${ev.tool}`;
  card.innerHTML = `
    <h4>Poseidon ${title} <code></code></h4>
    <pre></pre>
    <div class="actions">
      <button class="ok-btn">Approve</button>
      <button class="ghost always-btn">Always allow</button>
      <button class="deny deny-btn">Deny</button>
    </div>`;
  card.querySelector("code").textContent = ev.subject;
  card.querySelector("pre").textContent = ev.detail || ev.subject;
  const resolve = async (approved, always) => {
    await fetch(`/api/approvals/${ev.id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ approved, always }),
    });
    card.classList.add("resolved");
    card.querySelector(".actions").innerHTML =
      `<span class="verdict">${approved ? (always ? "✓ approved — always allow saved" : "✓ approved") : "✗ denied"}</span>`;
    setThinking(true);
  };
  card.querySelector(".ok-btn").onclick = () => resolve(true, false);
  card.querySelector(".always-btn").onclick = () => resolve(true, true);
  card.querySelector(".deny-btn").onclick = () => resolve(false, false);
  $("messages").appendChild(card);
  scrollChat();
}

/* ---------- workspace: activity ---------- */
function logActivity(label, detail, cls) {
  const feed = $("activity-feed");
  feed.querySelector(".feed-empty")?.remove();
  const row = document.createElement("div");
  row.className = "feed-item";
  const t = new Date().toLocaleTimeString();
  row.innerHTML = `<span class="t"></span><span class="${cls}"></span><span></span>`;
  row.children[0].textContent = t;
  row.children[1].textContent = label;
  row.children[2].textContent = detail || "";
  feed.appendChild(row);
  feed.parentElement.scrollTop = feed.parentElement.scrollHeight;
}

/* ---------- workspace: files ---------- */
let currentPath = ".";
async function loadFiles(path) {
  const r = await fetch(`/api/files?path=${encodeURIComponent(path)}`);
  if (!r.ok) return;
  const data = await r.json();
  currentPath = data.path;
  $("file-view").hidden = true;
  renderBreadcrumb(data.path);
  const list = $("file-list");
  list.innerHTML = "";
  for (const e of data.entries) {
    const row = document.createElement("div");
    row.className = "file-row";
    const name = document.createElement("span");
    name.textContent = (e.dir ? "📁 " : "📄 ") + e.name;
    const size = document.createElement("span");
    size.className = "size";
    size.textContent = e.dir ? "" : fmtSize(e.size);
    row.append(name, size);
    const childPath = data.path === "." ? e.name : `${data.path}/${e.name}`;
    row.onclick = () => (e.dir ? loadFiles(childPath) : viewFile(childPath));
    list.appendChild(row);
  }
}

function renderBreadcrumb(path) {
  const bc = $("file-breadcrumb");
  bc.innerHTML = "";
  const root = document.createElement("a");
  root.textContent = "workdir";
  root.onclick = () => loadFiles(".");
  bc.appendChild(root);
  if (path !== ".") {
    let acc = "";
    for (const part of path.split("/")) {
      acc = acc ? `${acc}/${part}` : part;
      bc.appendChild(document.createTextNode(" / "));
      const a = document.createElement("a");
      a.textContent = part;
      const target = acc;
      a.onclick = () => loadFiles(target);
      bc.appendChild(a);
    }
  }
}

async function viewFile(path) {
  const r = await fetch(`/api/file?path=${encodeURIComponent(path)}`);
  if (!r.ok) return;
  const data = await r.json();
  const view = $("file-view");
  view.textContent = data.content;
  view.hidden = false;
}

function fmtSize(n) {
  if (n == null) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1048576) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1048576).toFixed(1)} MB`;
}

/* ---------- cost meter ---------- */
function updateCost(ev) {
  const el = $("cost");
  el.textContent = `$${ev.cost.toFixed(4)}`;
  el.title = `Session cost — ${ev.tokens_in.toLocaleString()} in / ${ev.tokens_out.toLocaleString()} out${ev.priced ? "" : " (model unpriced, cost incomplete)"}`;
  el.classList.toggle("unpriced", !ev.priced);
}

/* ---------- tabs ---------- */
for (const tab of document.querySelectorAll(".tab")) {
  tab.onclick = () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".tab-body").forEach((b) => b.classList.remove("active"));
    tab.classList.add("active");
    $(`tab-${tab.dataset.tab}`).classList.add("active");
    if (tab.dataset.tab === "files") loadFiles(currentPath);
  };
}

/* ---------- settings & about ---------- */
function fillPresets(s) {
  const sel = $("preset-select");
  sel.innerHTML = "";
  for (const [key, p] of Object.entries(s.presets)) {
    const opt = document.createElement("option");
    opt.value = key;
    opt.textContent = p.label;
    sel.appendChild(opt);
  }
  sel.onchange = () => {
    const p = s.presets[sel.value];
    $("cfg-base-url").value = p.base_url || "";
    $("cfg-model").value = p.model || "";
    $("cfg-api-key").value = "";
  };
  if (s.provider) {
    $("cfg-base-url").value = s.provider.base_url;
    $("cfg-model").value = s.provider.model;
  } else {
    sel.value = "ollama";
    sel.onchange();
  }
}

function openSettings() {
  $("settings-modal").showModal();
}
$("settings-btn").onclick = openSettings;
$("cfg-cancel").onclick = () => $("settings-modal").close();
$("cfg-save").onclick = async (e) => {
  e.preventDefault();
  const body = {
    base_url: $("cfg-base-url").value,
    api_key: $("cfg-api-key").value,
    model: $("cfg-model").value,
  };
  const r = await fetch("/api/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (r.ok) $("settings-modal").close();
  else alert("Base URL and model are required.");
};

$("about-link").onclick = (e) => {
  e.preventDefault();
  $("about-modal").showModal();
};
$("about-close").onclick = () => $("about-modal").close();

init();
