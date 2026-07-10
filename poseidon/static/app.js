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

const UK_CREAM = "#f2e8cf";
function svgUrl(svg) {
  return `url('data:image/svg+xml,${encodeURIComponent(svg)}')`;
}

/* Great-Wave sprite: solid curl body, face streaks, pearl-scalloped crest
   foam, claws under the lip, foam piles at both bases. */
function ukWaveSVG(p) {
  return `<svg viewBox="0 0 320 260" width="100%" height="100%">
  <path d="M16,250 C6,190 14,104 54,60 C94,20 158,10 206,34 C246,54 260,98 244,132 C235,152 216,162 199,159 C187,157 180,147 183,136 C172,127 165,112 164,96 C146,110 126,134 106,166 C94,190 88,220 88,250 Z" fill="${p.body}" stroke="${p.line}" stroke-width="3"/>
  <g fill="none" stroke-linecap="round">
    <path d="M92,244 C100,196 122,152 160,118" stroke="${p.streak}" stroke-width="14"/>
    <path d="M116,248 C126,210 146,176 178,148" stroke="${p.streak}" stroke-width="10"/>
    <path d="M64,240 C68,186 88,138 124,100" stroke="${p.pale}" stroke-width="8"/>
    <path d="M96,74 C140,42 188,44 216,74" stroke="${p.streak}" stroke-width="12"/>
    <path d="M110,60 C150,36 190,38 214,58" stroke="${p.pale}" stroke-width="6"/>
  </g>
  <g fill="none" stroke="${p.foam}" stroke-linecap="round">
    <path d="M36,118 C50,58 104,20 160,18 C206,20 240,48 246,92 C247,114 234,132 214,138" stroke-width="15"/>
    <path d="M36,118 C50,58 104,20 160,18 C206,20 240,48 246,92 C247,114 234,132 214,138" stroke-width="22" stroke-dasharray="0,32"/>
  </g>
  <g fill="${p.foam}">
    <path d="M212,142 q10,20 2,32 q-6,-18 -10,-24 z"/><path d="M196,148 q8,20 -2,30 q-5,-17 -8,-22 z"/>
    <path d="M180,146 q6,17 -3,26 q-4,-15 -6,-19 z"/><path d="M166,138 q5,15 -3,23 q-3,-13 -5,-16 z"/>
    <path d="M228,128 q12,14 8,28 q-8,-14 -13,-19 z"/>
    <circle cx="34" cy="242" r="14"/><circle cx="54" cy="234" r="11"/><circle cx="70" cy="244" r="13"/><circle cx="20" cy="252" r="10"/>
    <circle cx="90" cy="248" r="10"/><circle cx="106" cy="242" r="8"/>
    <circle cx="206" cy="242" r="16"/><circle cx="228" cy="234" r="12"/><circle cx="248" cy="244" r="14"/><circle cx="268" cy="252" r="10"/>
    <circle cx="188" cy="250" r="10"/><circle cx="222" cy="252" r="9"/>
  </g>
  <g fill="${p.shadow}">
    <circle cx="46" cy="252" r="9"/><circle cx="80" cy="254" r="8"/><circle cx="216" cy="250" r="9"/><circle cx="252" cy="254" r="8"/>
  </g></svg>`;
}

const UK_DEEP = { body: "#1e4f9c", line: "#16345f", streak: "#3a70bd", pale: "#9db8d9", foam: "#f4f6f8", shadow: "#c5d2e0" };
const UK_PALE = { body: "#4a74ad", line: "#33608f", streak: "#6d92bb", pale: "#a9c0dc", foam: "#f4f6f8", shadow: "#cbd7e4" };

/* Swirl cloud in the classic style: puffy top, flat base, negative-space spirals. */
function ukCloudSVG() {
  return `<svg viewBox="0 0 220 110" width="100%" height="100%">
  <g fill="#ffffff">
    <circle cx="52" cy="62" r="24"/><circle cx="88" cy="46" r="29"/><circle cx="128" cy="50" r="26"/><circle cx="162" cy="64" r="19"/>
    <rect x="30" y="62" width="150" height="22" rx="11"/>
  </g>
  <g fill="none" stroke="#ece0c4" stroke-width="5" stroke-linecap="round">
    <path d="M70,64 C70,52 82,46 92,52 C100,57 100,68 92,72 C86,75 79,72 78,66 C77,61 82,58 86,60"/>
    <path d="M124,66 C123,54 135,47 145,53 C152,58 152,68 145,72 C139,74 133,71 133,65"/>
  </g>
  <path d="M180,66 C196,58 208,62 212,72 C206,68 196,68 188,74 C184,77 180,72 180,66 Z" fill="#ffffff"/></svg>`;
}

function ukFuji() {
  return `<svg viewBox="0 0 220 170" width="100%" height="100%"><path d="M0,170 L82,38 Q95,20 108,38 L190,170 Z" fill="#5c719c"/><path d="M64,68 L82,38 Q95,20 108,38 L126,68 L114,60 L104,70 L94,58 L84,69 L74,60 Z" fill="${UK_CREAM}"/></svg>`;
}

function ukiyoScene() {
  const sway = () =>
    `animation-duration:${(5 + Math.random() * 4).toFixed(1)}s;animation-delay:${(-Math.random() * 8).toFixed(1)}s`;
  const flip = () => (Math.random() < 0.4 ? "transform:scaleX(-1)" : "");

  let waves = "";
  // back row: smaller, paler
  [
    [5, 120], [22, 145], [40, 112], [58, 138], [76, 118], [91, 132],
  ].forEach(([left, w]) => {
    waves += `<div class="uk-wave back" style="left:${left}%;width:${w}px;height:${Math.round(w * 0.81)}px;${sway()}"><div style="width:100%;height:100%;${flip()}">${ukWaveSVG(UK_PALE)}</div></div>`;
  });
  // front row: bigger, deeper
  [
    [-2, 205], [17, 172], [36, 225], [57, 182], [75, 215], [90, 178],
  ].forEach(([left, w]) => {
    waves += `<div class="uk-wave front" style="left:${left}%;width:${w}px;height:${Math.round(w * 0.81)}px;${sway()}"><div style="width:100%;height:100%;${flip()}">${ukWaveSVG(UK_DEEP)}</div></div>`;
  });

  let clouds = "";
  [
    [6, 6, 170], [38, 13, 130], [66, 11, 200], [88, 19, 110],
  ].forEach(([left, top, w]) => {
    clouds += `<div class="uk-cloud" style="left:${left}%;top:${top}%;width:${w}px;height:${Math.round(w * 0.5)}px;${sway()}">${ukCloudSVG()}</div>`;
  });

  let petals = "";
  for (let i = 0; i < 8; i++) {
    const left = (4 + Math.random() * 88).toFixed(0);
    const dur = (16 + Math.random() * 14).toFixed(1);
    const delay = (-Math.random() * 20).toFixed(1);
    const s = (10 + Math.random() * 8).toFixed(0);
    petals += `<span class="petal" style="left:${left}%;animation-duration:${dur}s;animation-delay:${delay}s"><svg width="${s}" height="${s}" viewBox="0 0 16 16"><path d="M8,1 C11,4 14,6 13,10 C12,14 8,15 8,15 C8,15 4,14 3,10 C2,6 5,4 8,1 Z" fill="#eaa8ba"/></svg></span>`;
  }

  return `<div class="uk-sun"></div>${clouds}<div class="uk-fuji">${ukFuji()}</div>
    <div class="uk-sea"></div>${waves}${petals}`;
}

/* ---- wasteland ---- */
function mesaTile() {
  return svgUrl(`<svg xmlns="http://www.w3.org/2000/svg" width="900" height="220" viewBox="0 0 900 220"><g fill="#d8a468"><path d="M60,220 L64,118 Q66,104 84,102 L150,100 Q166,102 170,116 L176,220 Z"/><path d="M176,220 L178,150 Q180,140 192,139 L226,138 Q236,140 238,148 L242,220 Z"/><path d="M560,220 L566,96 Q568,82 588,80 L668,78 Q686,80 690,94 L698,220 Z"/><path d="M508,220 L510,164 Q511,156 521,155 L549,154 Q557,156 558,162 L560,220 Z"/></g></svg>`);
}

function duneTile2(fill, crest, poles) {
  const pole = (x, lean) =>
    `<g stroke="#4a2c12" stroke-width="5" opacity="0.85"><path d="M${x},128 L${x + lean},34"/><path d="M${x + lean - 26},48 L${x + lean + 26},44" stroke-width="4"/></g>`;
  const wires = poles
    ? `${pole(250, 6)}${pole(620, -8)}<path d="M282,50 Q436,86 586,44 M-38,60 Q100,84 250,48 M638,42 Q760,74 838,58" stroke="#4a2c12" stroke-width="2" fill="none" opacity="0.7"/>`
    : "";
  return svgUrl(`<svg xmlns="http://www.w3.org/2000/svg" width="800" height="260" viewBox="0 0 800 260">${wires}<path d="M0,176 Q120,92 262,124 L270,128 Q300,140 340,152 Q480,190 570,148 Q690,102 800,156 L800,260 L0,260 Z" fill="${fill}"/><path d="M0,176 Q120,92 262,124 M340,152 Q480,190 570,148 Q690,102 800,156" fill="none" stroke="${crest}" stroke-width="3" opacity="0.7"/><g stroke="${crest}" stroke-width="2" fill="none" opacity="0.4"><path d="M120,180 q40,-8 74,2"/><path d="M420,196 q50,-10 88,0"/><path d="M620,180 q40,-10 72,-2"/></g></svg>`);
}

function dustTile(n, color, w, h) {
  let c = "";
  for (let i = 0; i < n; i++) {
    c += `<circle cx="${(Math.random() * w).toFixed(0)}" cy="${(Math.random() * h).toFixed(0)}" r="${(0.8 + Math.random() * 1.6).toFixed(1)}" opacity="${(0.2 + Math.random() * 0.5).toFixed(2)}"/>`;
  }
  return svgUrl(`<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" fill="${color}">${c}</svg>`);
}

function caravanSVG() {
  return `<svg viewBox="0 0 380 180" width="100%" height="100%">
  <path d="M16,92 C12,54 28,40 44,38 L108,38 C124,40 138,54 136,92 Z" fill="#d9c49c"/>
  <path d="M46,38 C42,56 40,74 41,92 M76,38 C74,56 73,74 74,92 M106,38 C108,56 109,74 110,92" stroke="#a98f63" stroke-width="2" fill="none"/>
  <rect x="8" y="90" width="140" height="20" rx="3" fill="#38220f"/>
  <path d="M148,94 L166,96 L166,102 L148,104 Z" fill="#38220f"/>
  <g fill="none" stroke="#38220f">
    <g class="wheel"><circle cx="46" cy="134" r="28" stroke-width="6"/><path d="M46,106 L46,162 M18,134 L74,134 M26,114 L66,154 M26,154 L66,114" stroke-width="3"/><circle cx="46" cy="134" r="5" fill="#38220f"/></g>
    <g class="wheel"><circle cx="122" cy="140" r="22" stroke-width="6"/><path d="M122,118 L122,162 M100,140 L144,140 M107,125 L137,155 M107,155 L137,125" stroke-width="3"/><circle cx="122" cy="140" r="4" fill="#38220f"/></g>
  </g>
  <g class="cdust" fill="#c9a670"><circle cx="14" cy="150" r="7"/><circle cx="2" cy="142" r="5"/><circle cx="-8" cy="152" r="4"/></g>
  <g fill="#38220f">
    <circle cx="157" cy="63" r="7"/><rect x="147" y="53" width="20" height="4" rx="2"/><rect x="152" y="45" width="11" height="9" rx="2"/>
    <path d="M150,70 C156,68 161,70 163,76 L166,92 L149,94 L148,78 Z"/>
    <path d="M161,76 L180,85 L179,90 L159,82 Z"/>
    <path d="M150,94 L163,93 L169,104 L158,107 L152,104 Z"/>
  </g>
  <path d="M150,100 L215,97" stroke="#38220f" stroke-width="4"/>
  <path d="M180,86 C240,60 288,48 316,44" stroke="#5a3b1d" stroke-width="2" fill="none"/>
  <g fill="#38220f">
    <ellipse cx="250" cy="82" rx="46" ry="24"/>
    <path d="M282,68 L302,42 L316,49 L292,90 Z"/>
    <path d="M306,50 C301,42 307,32 316,34 L331,40 C339,43 343,51 340,57 C338,62 332,63 328,61 L312,54 C309,53 307,52 306,50 Z"/>
    <path d="M303,38 L305,26 L312,35 Z M311,36 L315,25 L320,34 Z"/>
    <path d="M208,72 C195,76 188,92 193,112 C187,94 193,78 205,73 Z"/>
    <g class="leg lg1"><path d="M208,94 L219,95 L218,121 L222,124 L220,156 L212,156 L214,125 L207,120 Z"/></g>
    <g class="leg lg2"><path d="M220,95 L231,96 L230,122 L234,125 L232,156 L224,156 L226,126 L220,121 Z"/></g>
    <g class="leg lg2b"><path d="M268,96 L278,97 L277,122 L281,125 L279,156 L271,156 L273,126 L267,121 Z"/></g>
    <g class="leg lg1b"><path d="M280,97 L290,98 L289,123 L293,126 L291,156 L283,156 L285,127 L279,122 Z"/></g>
  </g></svg>`;
}

function banditSVG() {
  return `<svg viewBox="0 0 320 180" width="100%" height="100%">
  <g fill="#2e1c0c">
    <ellipse cx="128" cy="92" rx="50" ry="23" transform="rotate(-5 128 92)"/>
    <path d="M164,80 L186,52 L200,59 L178,100 Z"/>
    <path d="M190,60 C185,52 191,42 200,44 L215,50 C223,53 227,61 224,67 C222,72 216,73 212,71 L196,64 C193,63 191,62 190,60 Z"/>
    <path d="M187,48 L189,36 L196,45 Z M195,46 L199,35 L204,44 Z"/>
    <path d="M84,80 C71,82 62,98 66,118 C60,100 68,84 81,81 Z"/>
    <g class="leg gl1"><path d="M96,104 L107,105 L96,126 L100,130 L88,154 L81,151 L92,129 L88,124 Z"/></g>
    <g class="leg gl2"><path d="M108,106 L119,107 L110,128 L114,132 L104,155 L97,152 L106,131 L102,126 Z"/></g>
    <g class="leg gl2b"><path d="M146,106 L156,107 L162,126 L167,128 L178,150 L171,153 L160,131 L154,126 Z"/></g>
    <g class="leg gl1b"><path d="M158,106 L168,107 L176,125 L181,127 L191,148 L184,151 L174,130 L168,125 Z"/></g>
    <circle cx="126" cy="33" r="7"/><rect x="112" y="24" width="28" height="4" rx="2"/><rect x="120" y="14" width="12" height="11" rx="2"/>
    <path d="M119,40 C125,38 131,40 133,46 L137,66 L118,68 L116,47 Z"/>
    <path d="M132,45 L162,39 L162,45 L134,51 Z"/>
    <path d="M118,68 L137,66 L143,82 L137,86 L132,80 L128,88 L122,84 Z"/>
    <path d="M116,31 L100,37 L115,40 Z" fill="#7a1f14"/>
    <path d="M162,37 L175,37 L175,42 L168,42 L168,48 L162,48 Z"/>
  </g>
  <g class="flash">
    <circle cx="188" cy="43" r="15" fill="#ffe9a8" opacity="0.6"/>
    <path d="M176,39 L201,28 L188,40 L207,42 L188,46 L200,56 L179,45 L182,42 Z" fill="#ffd76a" stroke="#fff8e0" stroke-width="1.5"/>
    <path d="M181,42 L194,40 L184,45 Z" fill="#fff"/>
  </g></svg>`;
}

function wastelandScene() {
  return `<div class="ws-sun"></div>
    <div class="ws-dust"></div><div class="ws-dust d2"></div>
    <div class="ws-mesas"></div>
    <div class="ws-band ws-back"></div><div class="ws-band ws-mid"></div>
    <div class="bandit">${banditSVG()}</div>
    <div class="caravan">${caravanSVG()}</div>
    <div class="ws-band ws-front"></div>
    <div class="wind"><i></i><i></i><i></i><i></i></div>`;
}

const SCENES = { base: baseScene, trek: trekScene, ukiyo: ukiyoScene, wasteland: wastelandScene };

const SCENE_SETUP = {
  wasteland(scene) {
    scene.querySelector(".ws-dust").style.backgroundImage = dustTile(34, "#9a6f3c", 480, 360);
    scene.querySelector(".ws-dust.d2").style.backgroundImage = dustTile(24, "#b58a52", 340, 260);
    scene.querySelector(".ws-mesas").style.backgroundImage = mesaTile();
    scene.querySelector(".ws-back").style.backgroundImage = duneTile2("#cd9c5c", "#e8c896", false);
    scene.querySelector(".ws-mid").style.backgroundImage = duneTile2("#a06b31", "#c99a5f", true);
    scene.querySelector(".ws-front").style.backgroundImage = duneTile2("#6e4218", "#9c6b35", false);
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
    scheduleTumbleweed(50000 + Math.random() * 60000);
  }, delay));
}

/* The chase: bandit rides up behind the caravan, fires, the caravan bolts
   (wind picks up, legs and wheels double-time) and outruns him. */
function scheduleChase(delay) {
  skinTimers.push(setTimeout(() => {
    const scene = $("scene");
    scene.classList.add("chase");
    skinTimers.push(setTimeout(() => scene.classList.add("fleeing"), 4200));
    skinTimers.push(setTimeout(() => {
      scene.classList.remove("chase", "fleeing");
    }, 13500));
    scheduleChase(45000 + Math.random() * 40000);
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
  if (name === "wasteland") {
    scheduleTumbleweed(25000);
    scheduleChase(8000);
  }
  localStorage.setItem(SKIN_KEY, name);
  $("skin-select").value = name;
}

$("skin-select").onchange = (e) => applySkin(e.target.value);

applySkin(localStorage.getItem(SKIN_KEY) || "base");
init();
