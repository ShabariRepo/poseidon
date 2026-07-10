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
      if (!ev.agent) addToolChip(ev);
      logActivity(`→ ${agentLabel(ev)}${ev.name}`, describeArgs(ev), ev.agent ? "sub" : "");
      setThinking(true);
      break;
    case "tool_result":
      logActivity(`← ${agentLabel(ev)}${ev.name}`, ev.summary, ev.ok ? "ok" : "err");
      if (!ev.ok && !ev.agent) addToolChip({ name: ev.name, error: ev.summary });
      break;
    case "subagent_started":
      addToolChip({ name: `subagent ${ev.agent}`, args: { task: ev.task } });
      logActivity(`⑂ ${ev.agent} started`, ev.task, "sub");
      break;
    case "subagent_complete":
      logActivity(`⑂ ${ev.agent} done`, ev.result, "ok");
      break;
    case "tasks_update":
      renderTasks(ev.tasks);
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
  return a.path || a.command || a.url || a.task || a.prompt || "";
}

function agentLabel(ev) {
  return ev.agent ? `[${ev.agent}] ` : "";
}

function scrollChat() {
  $("messages").scrollTop = $("messages").scrollHeight;
}

/* ---------- approvals ---------- */
function renderApproval(ev) {
  const card = document.createElement("div");
  card.className = "approval";
  const title = {
    write_file: "wants to write",
    edit_file: "wants to edit",
    run_command: "wants to run",
    schedule_task: "wants to schedule",
  }[ev.tool] || `wants: ${ev.tool}`;
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

/* ---------- workspace: tasks ---------- */
function renderTasks(tasks) {
  const list = $("task-list");
  list.innerHTML = "";
  if (!tasks.length) {
    list.innerHTML = '<div class="feed-empty">No tasks right now.</div>';
    return;
  }
  const dots = { pending: "○", in_progress: "◉", done: "✓" };
  for (const t of tasks) {
    const row = document.createElement("div");
    row.className = `task-row ${t.status}`;
    const dot = document.createElement("span");
    dot.className = "dot";
    dot.textContent = dots[t.status] || "○";
    const title = document.createElement("span");
    title.className = "title";
    title.textContent = t.title;
    row.append(dot, title);
    list.appendChild(row);
  }
}

/* ---------- workspace: schedules ---------- */
async function loadSchedules() {
  const r = await fetch("/api/schedules");
  if (!r.ok) return;
  const { schedules } = await r.json();
  const list = $("schedule-list");
  list.innerHTML = "";
  if (!schedules.length) {
    list.innerHTML =
      '<div class="feed-empty">No scheduled tasks yet — ask Poseidon to do something "every morning" or "in an hour".</div>';
    return;
  }
  for (const s of schedules) {
    const card = document.createElement("div");
    card.className = "schedule-card";
    const when =
      s.kind === "every" ? `every ${parseFloat(s.value)} min`
      : s.kind === "daily" ? `daily at ${s.value}`
      : `once at ${s.value}`;
    card.innerHTML = `
      <button class="ghost cancel">Cancel</button>
      <span class="when"></span> — <span class="prompt"></span>
      <div class="meta"></div>
      <div class="last" hidden></div>`;
    card.querySelector(".when").textContent = when;
    card.querySelector(".prompt").textContent = s.prompt;
    card.querySelector(".meta").textContent =
      `next: ${s.next_run || "—"}${s.last_run ? ` · last: ${s.last_run}` : ""}`;
    if (s.last_result) {
      const last = card.querySelector(".last");
      last.hidden = false;
      last.textContent = `↳ ${s.last_result}`;
    }
    card.querySelector(".cancel").onclick = async () => {
      await fetch(`/api/schedules/${s.id}`, { method: "DELETE" });
      loadSchedules();
    };
    list.appendChild(card);
  }
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
    if (tab.dataset.tab === "schedules") loadSchedules();
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

/* ================= skins ================= */
const SKIN_KEY = "poseidon-skin";
let skinTimers = [];

function clearSkinFx() {
  skinTimers.forEach(clearTimeout);
  skinTimers = [];
}

/* ---- scene builders ---- */
function baseScene() {
  return `<div class="waves">
    <svg class="wave wave-back" viewBox="0 0 1440 320" preserveAspectRatio="none">
      <path d="M0,192 C180,140 320,240 520,210 C720,180 860,90 1080,120 C1260,145 1360,200 1440,180 L1440,320 L0,320 Z"/>
    </svg>
    <svg class="wave wave-front" viewBox="0 0 1440 320" preserveAspectRatio="none">
      <path d="M0,240 C220,190 380,280 600,250 C820,220 960,150 1160,180 C1310,202 1390,240 1440,230 L1440,320 L0,320 Z"/>
    </svg></div>`;
}

function starsSVG(n, rmax, cls) {
  let c = "";
  for (let i = 0; i < n; i++) {
    const tw = Math.random() < 0.18
      ? ` class="tw" style="animation-delay:${(Math.random() * 4).toFixed(1)}s"`
      : "";
    c += `<circle cx="${(Math.random() * 1600).toFixed(0)}" cy="${(Math.random() * 900).toFixed(0)}" r="${(rmax * (0.4 + Math.random() * 0.6)).toFixed(2)}" opacity="${(0.35 + Math.random() * 0.65).toFixed(2)}"${tw}/>`;
  }
  return `<svg class="star-layer ${cls}" viewBox="0 0 1600 900" preserveAspectRatio="xMidYMid slice" fill="#fff">${c}</svg>`;
}

function jumpSVG() {
  let c = "";
  for (let i = 0; i < 70; i++) {
    const a = Math.random() * Math.PI * 2;
    const r1 = 60 + Math.random() * 220;
    const r2 = r1 + 160 + Math.random() * 420;
    c += `<line x1="${(800 + r1 * Math.cos(a)).toFixed(0)}" y1="${(450 + r1 * Math.sin(a)).toFixed(0)}" x2="${(800 + r2 * Math.cos(a)).toFixed(0)}" y2="${(450 + r2 * Math.sin(a)).toFixed(0)}" opacity="${(0.3 + Math.random() * 0.6).toFixed(2)}" stroke-width="${(1 + Math.random() * 1.6).toFixed(1)}"/>`;
  }
  return `<svg viewBox="0 0 1600 900" preserveAspectRatio="xMidYMid slice" stroke="#dfeeff" width="100%" height="100%">${c}</svg>`;
}

function trekScene() {
  return `<div class="nebula n1"></div><div class="nebula n2"></div>
    ${starsSVG(150, 0.8, "l1")}${starsSVG(90, 1.2, "l2")}${starsSVG(40, 1.8, "l3")}
    <div class="shooting-star"></div><div class="shooting-star s2"></div>
    <div class="hyperjump">${jumpSVG()}</div>`;
}

const UK_CREAM = "#f5ecd7";
function svgUrl(svg) {
  return `url('data:image/svg+xml,${encodeURIComponent(svg)}')`;
}

function ukWaveTile(fill) {
  return svgUrl(`<svg xmlns="http://www.w3.org/2000/svg" width="600" height="240" viewBox="0 0 600 240"><path d="M0,150 Q50,92 112,96 Q164,99 188,136 Q202,158 192,184 Q244,122 322,107 Q392,94 432,132 Q456,156 446,186 Q498,128 562,120 Q586,117 600,126 L600,240 L0,240 Z" fill="${fill}"/><g fill="none" stroke="${UK_CREAM}" stroke-linecap="round"><path d="M0,150 Q50,92 112,96 Q164,99 188,136" stroke-width="5"/><path d="M192,184 Q244,122 322,107 Q392,94 432,132" stroke-width="5"/><path d="M446,186 Q498,128 562,120 Q586,117 600,126" stroke-width="5"/><path d="M188,136 q20,-30 46,-20 q24,9 20,32 q-3,18 -21,17 q-14,-1 -13,-15 q1,-11 12,-10" stroke-width="6"/><path d="M432,132 q20,-30 46,-20 q24,9 20,32 q-3,18 -21,17 q-14,-1 -13,-15 q1,-11 12,-10" stroke-width="6"/><path d="M0,150 Q50,92 112,96 Q164,99 188,136 M192,184 Q244,122 322,107 Q392,94 432,132 M446,186 Q498,128 562,120 Q586,117 600,126" stroke-width="11" stroke-dasharray="0,26"/></g></svg>`);
}

function ukCloudTile() {
  return svgUrl(`<svg xmlns="http://www.w3.org/2000/svg" width="800" height="120" viewBox="0 0 800 120"><g fill="#f8f1de" stroke="#4a5a7d" stroke-width="1.5" opacity="0.9"><rect x="40" y="56" width="200" height="17" rx="8.5"/><rect x="82" y="36" width="128" height="17" rx="8.5"/><rect x="62" y="76" width="148" height="17" rx="8.5"/><rect x="470" y="46" width="228" height="17" rx="8.5"/><rect x="522" y="26" width="138" height="17" rx="8.5"/><rect x="500" y="66" width="168" height="17" rx="8.5"/></g></svg>`);
}

function ukiyoScene() {
  return `<div class="uk-sun"></div><div class="uk-clouds"></div>
    <div class="uk-band uk-back"></div><div class="uk-band uk-mid"></div><div class="uk-band uk-front"></div>`;
}

function duneTile(fill, derrick) {
  const rig = derrick
    ? `<g fill="${fill}"><path d="M604,150 l15,-58 h8 l15,58 z"/><rect x="596" y="94" width="54" height="6"/><path d="M611,100 l24,44 M635,100 l-24,44" stroke="${fill}" stroke-width="3"/></g>`
    : "";
  return svgUrl(`<svg xmlns="http://www.w3.org/2000/svg" width="800" height="260" viewBox="0 0 800 260"><path d="M0,150 Q160,70 340,130 Q520,190 800,110 L800,260 L0,260 Z" fill="${fill}"/>${rig}</svg>`);
}

function dustTile(n, color, w, h) {
  let c = "";
  for (let i = 0; i < n; i++) {
    c += `<circle cx="${(Math.random() * w).toFixed(0)}" cy="${(Math.random() * h).toFixed(0)}" r="${(0.8 + Math.random() * 1.6).toFixed(1)}" opacity="${(0.2 + Math.random() * 0.5).toFixed(2)}"/>`;
  }
  return svgUrl(`<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" fill="${color}">${c}</svg>`);
}

function wastelandScene() {
  return `<div class="ws-sun"></div>
    <div class="ws-dust"></div><div class="ws-dust d2"></div>
    <div class="ws-band ws-back"></div><div class="ws-band ws-mid"></div><div class="ws-band ws-front"></div>`;
}

const SCENES = { base: baseScene, trek: trekScene, ukiyo: ukiyoScene, wasteland: wastelandScene };

const SCENE_SETUP = {
  ukiyo(scene) {
    scene.querySelector(".uk-clouds").style.backgroundImage = ukCloudTile();
    scene.querySelector(".uk-back").style.backgroundImage = ukWaveTile("#7a9cc4");
    scene.querySelector(".uk-mid").style.backgroundImage = ukWaveTile("#3e6494");
    scene.querySelector(".uk-front").style.backgroundImage = ukWaveTile("#22406e");
  },
  wasteland(scene) {
    scene.querySelector(".ws-dust").style.backgroundImage = dustTile(34, "#9a6f3c", 480, 360);
    scene.querySelector(".ws-dust.d2").style.backgroundImage = dustTile(24, "#b58a52", 340, 260);
    scene.querySelector(".ws-back").style.backgroundImage = duneTile("#c99a5d", false);
    scene.querySelector(".ws-mid").style.backgroundImage = duneTile("#a06b31", false);
    scene.querySelector(".ws-front").style.backgroundImage = duneTile("#6e4218", true);
  },
};

/* ---- occasional effects ---- */
function scheduleHyperjump(delay) {
  skinTimers.push(setTimeout(() => {
    const scene = $("scene");
    scene.classList.add("jumping");
    skinTimers.push(setTimeout(() => scene.classList.remove("jumping"), 1600));
    scheduleHyperjump(35000 + Math.random() * 40000);
  }, delay));
}

function spawnTumbleweed() {
  const el = document.createElement("div");
  el.className = "tumbleweed";
  el.innerHTML = `<svg viewBox="0 0 64 64" fill="none" stroke="#6b4a26" stroke-width="2"><ellipse cx="32" cy="32" rx="27" ry="25"/><ellipse cx="32" cy="32" rx="19" ry="22" transform="rotate(40 32 32)"/><ellipse cx="32" cy="32" rx="12" ry="16" transform="rotate(-30 32 32)"/><path d="M10,40 Q32,20 54,38 M14,22 Q34,40 52,24 M28,6 Q30,32 36,58"/></svg>`;
  $("scene").appendChild(el);
  skinTimers.push(setTimeout(() => el.remove(), 9500));
}

function scheduleTumbleweed(delay) {
  skinTimers.push(setTimeout(() => {
    spawnTumbleweed();
    scheduleTumbleweed(40000 + Math.random() * 50000);
  }, delay));
}

function applySkin(name) {
  if (!SCENES[name]) name = "base";
  clearSkinFx();
  document.documentElement.dataset.skin = name;
  const scene = $("scene");
  scene.classList.remove("jumping");
  scene.innerHTML = SCENES[name]();
  SCENE_SETUP[name]?.(scene);
  if (name === "trek") scheduleHyperjump(9000);
  if (name === "wasteland") scheduleTumbleweed(7000);
  localStorage.setItem(SKIN_KEY, name);
  $("skin-select").value = name;
}

$("skin-select").onchange = (e) => applySkin(e.target.value);

applySkin(localStorage.getItem(SKIN_KEY) || "base");
init();
