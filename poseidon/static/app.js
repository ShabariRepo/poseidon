/* Poseidon UI — vanilla JS, no build step. */
const $ = (id) => document.getElementById(id);

/* team server mode: member token from join link, sent on every request */
const TOKEN = new URLSearchParams(location.search).get("token") || localStorage.getItem("poseidon-token") || "";
if (TOKEN) {
  localStorage.setItem("poseidon-token", TOKEN);
  const _fetch = window.fetch.bind(window);
  window.fetch = (u, o = {}) => _fetch(u, { ...o, headers: { ...(o.headers || {}), "X-Poseidon-Token": TOKEN } });
}
const state = {
  projectId: null, memberId: null, sessionId: null, busy: false,
  presets: {}, engine: {}, rules: [], projects: [], members: [],
  thinkingEl: null, es: null, currentPath: ".", pipeTimer: null, sessionOwner: null,
};

const fmtTime = (ts) => (ts ? new Date(ts * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—");
const esc = (s) => { const d = document.createElement("span"); d.textContent = s ?? ""; return d.innerHTML; };

/* ---------- boot ---------- */
async function init() {
  const s = await fetch("/api/state").then((r) => r.json());
  Object.assign(state, { presets: s.presets, engine: s.engine, rules: s.approval_rules,
    projects: s.projects, members: s.members, approvalMode: s.approval_mode });
  $("workdir")?.remove();
  fillProjectSelect();
  fillMemberSelect();
  fillPresets(s);
  fillEngine();
  fillIntegrations(s);
  fillAccount(s);
  fillRules();
  if (!s.configured) openSettings();
  await newSession();
  loadFiles(".");
  loadBoard();
  $("chat-input").focus();
}

function fillProjectSelect() {
  const sel = $("project-select");
  sel.innerHTML = "";
  for (const p of state.projects) {
    const o = document.createElement("option");
    o.value = p.id;
    o.textContent = p.name;
    sel.appendChild(o);
  }
  const saved = localStorage.getItem("poseidon-project");
  state.projectId = state.projects.find((p) => p.id === saved) ? saved : state.projects[0]?.id;
  sel.value = state.projectId;
  sel.onchange = async () => {
    state.projectId = sel.value;
    localStorage.setItem("poseidon-project", sel.value);
    await newSession();
    loadFiles(".");
    refreshPipeline();
    refreshPaneData();
  };
}

function fillMemberSelect() {
  const sel = $("member-select");
  sel.innerHTML = "";
  for (const m of state.members) {
    const o = document.createElement("option");
    o.value = m.id;
    o.textContent = `👤 ${m.name}`;
    sel.appendChild(o);
  }
  const extra = document.createElement("option");
  extra.value = "__new";
  extra.textContent = "＋ add teammate…";
  sel.appendChild(extra);
  const saved = localStorage.getItem("poseidon-member");
  state.memberId = state.members.find((m) => m.id === saved) ? saved : state.members[0]?.id;
  sel.value = state.memberId;
  sel.onchange = async () => {
    if (sel.value === "__new") {
      const who = prompt("Teammate name — or their Bonito email to add from your team directory:");
      sel.value = state.memberId;
      if (!who) return;
      const payload = who.includes("@") ? { email: who } : { name: who };
      const r = await fetch("/api/members", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...payload, color: randColor() }) });
      if (!r.ok) return alert((await r.json().catch(() => ({}))).detail || "Could not add");
      const m = await r.json();
      state.members.push(m);
      fillMemberSelect();
      sel.value = m.id;
      state.memberId = m.id;
      localStorage.setItem("poseidon-member", m.id);
      return;
    }
    state.memberId = sel.value;
    localStorage.setItem("poseidon-member", sel.value);
  };
}

const randColor = () => `hsl(${Math.floor(Math.random() * 360)},55%,45%)`;

$("new-project-btn").onclick = async () => {
  const name = prompt("Project name:");
  if (!name) return;
  const wd = prompt("Folder for this project (blank = server default):") || "";
  const r = await fetch("/api/projects", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name, workdir: wd, member_id: state.memberId }) });
  if (!r.ok) return alert((await r.json()).detail || "failed");
  const p = await r.json();
  state.projects.push({ ...p, members: [] });
  fillProjectSelect();
  $("project-select").value = p.id;
  $("project-select").onchange();
};

/* ---------- sessions ---------- */
async function newSession() {
  const r = await fetch("/api/sessions", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ project_id: state.projectId, member_id: state.memberId }) });
  const { session_id } = await r.json();
  state.sessionId = session_id;
  state.sessionOwner = state.memberId;
  $("messages").innerHTML = "";
  $("session-title").textContent = "new session";
  clearActivityAndTasks();
  openEvents();
}

async function openSession(sid) {
  const s = await fetch(`/api/sessions/${sid}`).then((r) => (r.ok ? r.json() : null));
  if (!s) return;
  state.sessionId = sid;
  state.sessionOwner = s.member_id;
  $("messages").innerHTML = "";
  clearActivityAndTasks();
  for (const m of s.messages) addMsg(m.role === "user" ? "user" : "assistant", m.content);
  $("session-title").textContent = s.title || "untitled";
  if (s.progress) addProgressChip(s.progress);
  updateCost({ cost: s.cost, tokens_in: s.tokens_in, tokens_out: s.tokens_out, priced: !!s.priced });
  openEvents();
  $("session-drawer").hidden = true;
}

function clearActivityAndTasks() {
  $("activity-feed").innerHTML = '<div class="feed-empty">Tool calls will stream here — watch it work.</div>';
  $("task-list").innerHTML = '<div class="feed-empty">When Poseidon plans multi-step work, its checklist appears here.</div>';
}

$("new-session-btn").onclick = () => newSession();
$("sessions-btn").onclick = async () => {
  const drawer = $("session-drawer");
  if (!drawer.hidden) { drawer.hidden = true; return; }
  const { sessions } = await fetch(`/api/sessions?project_id=${state.projectId}`).then((r) => r.json());
  const list = $("session-list");
  list.innerHTML = sessions.length ? "" : '<div class="feed-empty">No sessions yet.</div>';
  for (const s of sessions) {
    const row = document.createElement("div");
    row.className = "session-row" + (s.id === state.sessionId ? " current" : "");
    row.innerHTML = `<span class="dot" style="background:${esc(s.member_color || "#888")}"></span>
      <div class="session-info"><div class="t">${esc(s.title || "untitled")}</div>
      <div class="p">${esc(s.progress || "")}</div>
      <div class="m">${esc(s.member_name || "?")} · ${fmtTime(s.updated)}</div></div>`;
    row.onclick = () => openSession(s.id);
    list.appendChild(row);
  }
  drawer.hidden = false;
};
$("drawer-close").onclick = () => ($("session-drawer").hidden = true);

/* ---------- events (SSE) ---------- */
function openEvents() {
  if (state.es) state.es.close();
  state.es = new EventSource(`/api/events?session_id=${state.sessionId}&project_id=${state.projectId}${TOKEN ? `&token=${TOKEN}` : ""}`);
  state.es.onmessage = (e) => handleEvent(JSON.parse(e.data));
}

function handleEvent(ev) {
  if (["run_started", "run_finished"].includes(ev.type)) schedulePipeline();
  const mine = ev.session_id === state.sessionId;
  switch (ev.type) {
    case "turn_started": if (mine) setThinking(true); break;
    case "assistant_delta": {
      if (!mine || ev.agent) break;
      setThinking(false);
      if (!state.streamEl) {
        state.streamEl = document.createElement("div");
        state.streamEl.className = "msg assistant streaming";
        $("messages").appendChild(state.streamEl);
      }
      state.streamEl.textContent += ev.chunk;
      scrollChat();
      break;
    }
    case "assistant_message":
      if (!mine) break;
      setThinking(false);
      if (!ev.agent && state.streamEl) {
        state.streamEl.textContent = ev.content;
        state.streamEl.classList.remove("streaming");
        state.streamEl = null;
      } else {
        addMsg("assistant", ev.content);
      }
      setThinking(state.busy);
      break;
    case "tool_call":
      setThinking(false);
      if (mine && !ev.agent) addToolChip(ev);
      logActivity(`→ ${agentLabel(ev)}${ev.name}`, describeArgs(ev), ev.agent ? "sub" : "");
      if (mine) setThinking(true);
      break;
    case "tool_result":
      logActivity(`← ${agentLabel(ev)}${ev.name}`, ev.summary, ev.ok ? "ok" : "err");
      if (mine && !ev.ok && !ev.agent) addToolChip({ name: ev.name, error: ev.summary });
      break;
    case "subagent_started":
      if (mine) addToolChip({ name: `subagent ${ev.agent}`, args: { task: ev.task } });
      logActivity(`⑂ ${ev.agent} started`, ev.task, "sub");
      break;
    case "subagent_complete": logActivity(`⑂ ${ev.agent} done`, ev.result, "ok"); break;
    case "tasks_update": if (mine) renderTasks(ev.tasks); break;
    case "approval_required": if (mine) { setThinking(false); renderApproval(ev); } break;
    case "cost_update": if (mine) updateCost(ev); break;
    case "checkpoint_saved": if (mine) addChip(`📍 checkpoint saved${ev.auto ? " (auto)" : ""}`); break;
    case "work_update":
      if (document.querySelector(".tab.active")?.dataset.tab === "board") loadBoard();
      break;
    case "version_saved":
      if (mine) addChip(`🕘 version saved: ${ev.path}`);
      if (document.querySelector(".tab.active")?.dataset.tab === "files") loadFiles(state.currentPath);
      break;
    case "progress_update": if (mine) addProgressChip(ev.note); break;
    case "compacted": if (mine) addChip(`🗜 context compacted (${ev.dropped} messages summarized)`); break;
    case "error": if (mine) { setThinking(false); addMsg("error", ev.message); } break;
    case "turn_complete":
      if (!mine) break;
      if (state.streamEl) { state.streamEl.classList.remove("streaming"); state.streamEl = null; }
      state.busy = false; setThinking(false);
      $("send-btn").disabled = false;
      loadFiles(state.currentPath);
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
  const r = await fetch("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: state.sessionId, message: text, member_id: state.memberId }) });
  if (!r.ok) {
    const err = await r.json().catch(() => ({}));
    addMsg("error", err.detail || `request failed (${r.status})`);
    state.busy = false;
    $("send-btn").disabled = false;
  }
  if ($("session-title").textContent === "new session") $("session-title").textContent = text.slice(0, 60);
});

$("chat-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("chat-form").requestSubmit(); }
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

function addChip(text) {
  const div = document.createElement("div");
  div.className = "sys-chip";
  div.textContent = text;
  $("messages").appendChild(div);
  scrollChat();
}

function addProgressChip(note) {
  addChip(`🧭 progress: ${note}`);
}

function addToolChip(ev) {
  const div = document.createElement("div");
  div.className = "tool-chip";
  div.textContent = ev.error ? `⚠ ${ev.name}: ${ev.error}` : `🔧 ${ev.name} ${describeArgs(ev)}`;
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
  return a.path || a.command || a.url || a.task || a.prompt || a.label || a.note || "";
}
const agentLabel = (ev) => (ev.agent ? `[${ev.agent}] ` : "");
const scrollChat = () => { $("messages").scrollTop = $("messages").scrollHeight; };

/* ---------- approvals ---------- */
function renderApproval(ev) {
  const card = document.createElement("div");
  card.className = "approval";
  const title = { write_file: "wants to write", edit_file: "wants to edit", run_command: "wants to run", schedule_task: "wants to schedule" }[ev.tool] || `wants: ${ev.tool}`;
  card.innerHTML = `<h4>Poseidon ${title} <code></code></h4><pre></pre>
    <div class="actions"><button class="ok-btn">Approve</button>
    <button class="ghost always-btn">Always allow</button>
    <button class="deny deny-btn">Deny</button></div>`;
  card.querySelector("code").textContent = ev.subject;
  card.querySelector("pre").textContent = ev.detail || ev.subject;
  const resolve = async (approved, always) => {
    await fetch(`/api/approvals/${ev.id}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ approved, always }) });
    card.classList.add("resolved");
    card.querySelector(".actions").innerHTML = `<span class="verdict">${approved ? (always ? "✓ approved — always allow saved" : "✓ approved") : "✗ denied"}</span>`;
    setThinking(true);
  };
  card.querySelector(".ok-btn").onclick = () => resolve(true, false);
  card.querySelector(".always-btn").onclick = () => resolve(true, true);
  card.querySelector(".deny-btn").onclick = () => resolve(false, false);
  $("messages").appendChild(card);
  scrollChat();
}

/* ---------- pipeline ---------- */
function schedulePipeline() {
  clearTimeout(state.pipeTimer);
  state.pipeTimer = setTimeout(refreshPipeline, 400);
}

const KIND_ICON = { chat: "💬", background: "🌀", scheduled: "⏰", subagent: "⑂" };

async function refreshPipeline() {
  const [runsR, schedR] = await Promise.all([
    fetch(`/api/runs?project_id=${state.projectId}`).then((r) => r.json()),
    fetch(`/api/schedules?project_id=${state.projectId}`).then((r) => r.json()),
  ]);
  const runs = runsR.runs || [];
  const canvas = $("pipeline-canvas");
  canvas.innerHTML = "";
  if (schedR.schedules?.length) {
    const src = document.createElement("div");
    src.className = "pipe-sources";
    for (const s of schedR.schedules) {
      const n = document.createElement("div");
      n.className = "pnode source";
      n.innerHTML = `<span class="ico">⏰</span><div class="lbl">${esc(s.prompt.slice(0, 60))}</div>
        <div class="sub">next ${esc(s.next_run || "—")}</div>`;
      src.appendChild(n);
    }
    canvas.appendChild(src);
  }
  const tops = runs.filter((r) => !r.parent_run_id).slice(0, 10);
  const children = (id) => runs.filter((r) => r.parent_run_id === id);
  if (!tops.length && !schedR.schedules?.length) {
    canvas.innerHTML = '<div class="feed-empty">Runs will appear here as a live diagram — chat turns, background tasks, schedules, and their subagents. Click a node to drill in.</div>';
    return;
  }
  for (const run of tops) {
    canvas.appendChild(runNode(run, children));
  }
}

function runNode(run, children) {
  const wrap = document.createElement("div");
  wrap.className = "pipe-branch";
  const n = document.createElement("div");
  n.className = `pnode ${run.status}`;
  const dur = run.finished ? `${Math.max(1, Math.round(run.finished - run.started))}s` : "running…";
  n.innerHTML = `<span class="ico">${KIND_ICON[run.kind] || "•"}</span>
    <div class="lbl">${esc(run.label || run.kind)}</div>
    <div class="sub">${esc(run.kind)} · ${dur}${run.cost ? ` · $${run.cost.toFixed(4)}` : ""}</div>
    <span class="status-dot"></span>`;
  n.onclick = () => drillRun(run.id);
  wrap.appendChild(n);
  const kids = children(run.id);
  if (kids.length) {
    const box = document.createElement("div");
    box.className = "pipe-children";
    for (const k of kids) box.appendChild(runNode(k, children));
    wrap.appendChild(box);
  }
  return wrap;
}

async function drillRun(rid) {
  const run = await fetch(`/api/runs/${rid}`).then((r) => (r.ok ? r.json() : null));
  if (!run) return;
  $("drill-title").textContent = `${KIND_ICON[run.kind] || ""} ${run.label || run.kind}`;
  const evs = (run.events || []).map((e) => {
    const p = e.payload || {};
    const detail = p.content || p.summary || p.task || p.note || p.message ||
      (p.args ? (p.args.path || p.args.command || p.args.url || p.args.task || "") : "") || "";
    return `<div class="ev-row"><span class="t">${new Date(e.ts * 1000).toLocaleTimeString()}</span>
      <span class="k">${esc(e.type)}</span><span class="d">${esc(String(detail).slice(0, 160))}</span></div>`;
  }).join("");
  $("drill-body").innerHTML = `
    <div class="drill-meta">status <b>${esc(run.status)}</b> · started ${fmtTime(run.started)}
      ${run.finished ? "· finished " + fmtTime(run.finished) : ""} · $${(run.cost || 0).toFixed(4)}</div>
    ${run.result ? `<pre class="drill-result">${esc(run.result)}</pre>` : ""}
    <div class="ev-list">${evs || '<span class="muted">no events recorded</span>'}</div>`;
  $("drill-overlay").hidden = false;
}
$("drill-close").onclick = () => ($("drill-overlay").hidden = true);

/* ---------- work board ---------- */
const BOARD_COLS = [["todo", "To do"], ["doing", "In progress"], ["review", "In review"], ["done", "Done"]];

async function loadBoard() {
  const { items } = await fetch(`/api/work?project_id=${state.projectId}`).then((r) => r.json());
  const board = $("board");
  board.innerHTML = "";
  for (const [key, label] of BOARD_COLS) {
    const col = document.createElement("div");
    col.className = "bcol";
    const colItems = items.filter((i) => i.status === key);
    col.innerHTML = `<div class="bcol-head">${label} <span class="bcount">${colItems.length}</span>
      <button class="ghost mini badd" title="Add card">＋</button></div>`;
    col.querySelector(".badd").onclick = async () => {
      const title = prompt(`New card in "${label}":`);
      if (!title) return;
      await fetch("/api/work", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ project_id: state.projectId, title, status: key, member_id: state.memberId }) });
      loadBoard();
    };
    for (const item of colItems) col.appendChild(boardCard(item, key));
    board.appendChild(col);
  }
}

function boardCard(item, key) {
  const card = document.createElement("div");
  card.className = "bcard";
  const who = item.assignee_kind === "agent"
    ? '<span class="avatar tiny" style="background:#0f7fa8" title="Poseidon">🔱</span>'
    : item.assignee_name
      ? `<span class="avatar tiny" style="background:${esc(item.assignee_color || "#888")}" title="${esc(item.assignee_name)}">${esc(item.assignee_name[0].toUpperCase())}</span>`
      : "";
  const files = (item.files || []).length ? `<span class="badge">📄 ${item.files.length}</span>` : "";
  card.innerHTML = `<div class="bcard-title">${esc(item.title)}</div>
    <div class="bcard-meta">${who}${files}
      <span class="bmove"><button class="ghost mini bprev" title="Move back">◀</button><button class="ghost mini bnext" title="Move forward">▶</button></span>
    </div>`;
  const ki = BOARD_COLS.findIndex(([k]) => k === key);
  const move = async (dir) => {
    const next = BOARD_COLS[ki + dir]?.[0];
    if (!next) return;
    await fetch(`/api/work/${item.id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: next }) });
    loadBoard();
  };
  card.querySelector(".bprev").onclick = (e) => { e.stopPropagation(); move(-1); };
  card.querySelector(".bnext").onclick = (e) => { e.stopPropagation(); move(1); };
  card.onclick = () => {
    $("drill-title").textContent = `🗂 ${item.title}`;
    $("drill-body").innerHTML = `
      <div class="drill-meta">${esc(item.assignee_kind === "agent" ? "Poseidon" : item.assignee_name || "unassigned")} · updated ${fmtTime(item.updated)} · added by ${esc(item.creator_name || "?")}</div>
      ${item.notes ? `<pre class="drill-result">${esc(item.notes)}</pre>` : ""}
      ${(item.files || []).map((f) => `<div class="ev-row"><span class="k">file</span><span class="d">${esc(f)}</span></div>`).join("")}
      <div class="modal-actions"><button class="ghost mini" id="wdel">Delete card</button></div>`;
    $("drill-body").querySelector("#wdel").onclick = async () => {
      if (!confirm("Delete this card?")) return;
      await fetch(`/api/work/${item.id}?project_id=${state.projectId}`, { method: "DELETE" });
      $("drill-overlay").hidden = true;
      loadBoard();
    };
    $("drill-overlay").hidden = false;
  };
  return card;
}

/* ---------- file history ("saved versions") ---------- */
async function showHistory(path) {
  const { versions } = await fetch(`/api/files/history?path=${encodeURIComponent(path)}&project_id=${state.projectId}`).then((r) => r.json());
  $("drill-title").textContent = `🕘 ${path}`;
  const rows = versions.map((v, i) => {
    const who = v.author_kind === "agent" ? `🔱 Poseidon${v.author_name ? " (for " + esc(v.author_name) + ")" : ""}`
      : v.author_kind === "external" ? "✏️ outside edit"
      : `👤 ${esc(v.author_name || "member")}`;
    return `<div class="vrow" data-vid="${v.id}">
      <div class="vinfo"><b>${who}</b> · ${fmtTime(v.ts)}${i === 0 ? ' <span class="badge">current</span>' : ""}
        <div class="meta">${esc(v.label || "")}</div></div>
      <span class="row-actions">
        <button class="ghost mini vdiff">What changed</button>
        <button class="ghost mini vview">View</button>
        ${i === 0 ? "" : '<button class="ghost mini vrestore">Restore</button>'}
      </span></div><div class="vdetail" hidden></div>`;
  }).join("");
  $("drill-body").innerHTML = rows || '<span class="muted">no versions yet</span>';
  $("drill-body").querySelectorAll(".vrow").forEach((row) => {
    const vid = row.dataset.vid;
    const detail = row.nextElementSibling;
    row.querySelector(".vdiff").onclick = async () => {
      const d = await fetch(`/api/versions/${vid}/diff`).then((r) => r.json());
      detail.hidden = false;
      detail.innerHTML = d.binary ? '<span class="muted">binary file — no preview</span>'
        : d.first ? '<span class="muted">first version — everything is new</span>'
        : d.lines.map((l) => `<div class="dline ${l.t}">${esc(l.s)}</div>`).join("") || '<span class="muted">no changes</span>';
    };
    row.querySelector(".vview").onclick = async () => {
      const v = await fetch(`/api/versions/${vid}`).then((r) => r.json());
      detail.hidden = false;
      detail.innerHTML = `<pre class="drill-result">${esc(v.content.slice(0, 4000))}</pre>`;
    };
    row.querySelector(".vrestore")?.addEventListener("click", async () => {
      if (!confirm("Restore this version? The current version stays saved — nothing is lost.")) return;
      await fetch(`/api/versions/${vid}/restore`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ member_id: state.memberId }) });
      $("drill-overlay").hidden = true;
      loadFiles(state.currentPath);
    });
  });
  $("drill-overlay").hidden = false;
}

/* ---------- workspace: tasks ---------- */
function renderTasks(tasks) {
  const list = $("task-list");
  list.innerHTML = "";
  if (!tasks.length) { list.innerHTML = '<div class="feed-empty">No tasks right now.</div>'; return; }
  const dots = { pending: "○", in_progress: "◉", done: "✓" };
  for (const t of tasks) {
    const row = document.createElement("div");
    row.className = `task-row ${t.status}`;
    row.innerHTML = `<span class="dot-ch"></span><span class="title"></span>`;
    row.querySelector(".dot-ch").textContent = dots[t.status] || "○";
    row.querySelector(".title").textContent = t.title;
    list.appendChild(row);
  }
}

/* ---------- activity ---------- */
function logActivity(label, detail, cls) {
  const feed = $("activity-feed");
  feed.querySelector(".feed-empty")?.remove();
  const row = document.createElement("div");
  row.className = "feed-item";
  row.innerHTML = `<span class="t"></span><span class="${cls}"></span><span></span>`;
  row.children[0].textContent = new Date().toLocaleTimeString();
  row.children[1].textContent = label;
  row.children[2].textContent = detail || "";
  feed.appendChild(row);
  feed.parentElement.scrollTop = feed.parentElement.scrollHeight;
}

/* ---------- schedules ---------- */
async function loadSchedules() {
  const { schedules } = await fetch(`/api/schedules?project_id=${state.projectId}`).then((r) => r.json());
  const list = $("schedule-list");
  list.innerHTML = schedules.length ? "" : '<div class="feed-empty">No scheduled tasks yet — ask Poseidon to do something "every morning" or "in an hour".</div>';
  for (const s of schedules) {
    const card = document.createElement("div");
    card.className = "schedule-card";
    const when = s.kind === "every" ? `every ${parseFloat(s.value)} min` : s.kind === "daily" ? `daily at ${s.value}` : `once at ${s.value}`;
    card.innerHTML = `<button class="ghost cancel">Cancel</button>
      <span class="when"></span> — <span class="prompt"></span>
      <div class="meta"></div><div class="last" hidden></div>`;
    card.querySelector(".when").textContent = when;
    card.querySelector(".prompt").textContent = s.prompt;
    card.querySelector(".meta").textContent = `next: ${s.next_run || "—"}${s.last_run ? ` · last: ${s.last_run}` : ""}`;
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

/* ---------- checkpoints ---------- */
async function loadCheckpoints() {
  const { checkpoints } = await fetch(`/api/checkpoints?project_id=${state.projectId}`).then((r) => r.json());
  const list = $("checkpoint-list");
  list.innerHTML = checkpoints.length ? "" : '<div class="feed-empty">Checkpoints are saved automatically after real work (and on request). Review or rewind here.</div>';
  for (const c of checkpoints) {
    const card = document.createElement("div");
    card.className = "schedule-card";
    card.innerHTML = `<div class="row-actions">
        <button class="ghost mini view">View</button>
        <button class="ghost mini restore">Rewind</button></div>
      <span class="when">📍 ${esc(c.label)}</span>${c.auto ? ' <span class="badge">auto</span>' : ""}
      <div class="meta">${esc(c.session_title || "session")} · ${esc(c.member_name || "?")} · ${fmtTime(c.ts)}</div>
      ${c.progress ? `<div class="last">${esc(c.progress)}</div>` : ""}`;
    card.querySelector(".view").onclick = async () => {
      const d = await fetch(`/api/checkpoints/${c.id}`).then((r) => r.json());
      $("drill-title").textContent = `📍 ${d.label}`;
      const files = Object.entries(d.files || {}).map(([p, content]) =>
        `<div class="ev-row"><span class="k">file</span><span class="d">${esc(p)}</span></div><pre class="drill-result">${esc(content.slice(0, 1500))}</pre>`).join("");
      $("drill-body").innerHTML = `<div class="drill-meta">${fmtTime(d.ts)} · ${d.message_count} messages${d.progress ? " · " + esc(d.progress) : ""}</div>
        ${files || '<span class="muted">no files captured</span>'}`;
      $("drill-overlay").hidden = false;
    };
    card.querySelector(".restore").onclick = async () => {
      if (!confirm(`Rewind session to "${c.label}"? The conversation returns to that point.`)) return;
      const r = await fetch(`/api/checkpoints/${c.id}/restore`, { method: "POST" });
      if (r.ok && c.session_id === state.sessionId) openSession(state.sessionId);
    };
    list.appendChild(card);
  }
}

/* ---------- memory (the brain: Obsidian-compatible vault + link graph) ---------- */
function forceLayout(nodes, edges, w, h) {
  const pos = {};
  nodes.forEach((n, i) => {
    const a = (i / nodes.length) * Math.PI * 2;
    pos[n.id] = { x: w / 2 + Math.cos(a) * w * 0.3, y: h / 2 + Math.sin(a) * h * 0.3 };
  });
  const idx = Object.fromEntries(nodes.map((n) => [n.id, n]));
  for (let it = 0; it < 220; it++) {
    const f = {};
    nodes.forEach((n) => (f[n.id] = { x: 0, y: 0 }));
    for (let i = 0; i < nodes.length; i++)
      for (let j = i + 1; j < nodes.length; j++) {
        const a = pos[nodes[i].id], b = pos[nodes[j].id];
        let dx = a.x - b.x, dy = a.y - b.y;
        const d2 = Math.max(dx * dx + dy * dy, 100);
        const rep = 5200 / d2;
        const d = Math.sqrt(d2);
        dx /= d; dy /= d;
        f[nodes[i].id].x += dx * rep; f[nodes[i].id].y += dy * rep;
        f[nodes[j].id].x -= dx * rep; f[nodes[j].id].y -= dy * rep;
      }
    for (const e of edges) {
      if (!idx[e.source] || !idx[e.target]) continue;
      const a = pos[e.source], b = pos[e.target];
      let dx = b.x - a.x, dy = b.y - a.y;
      const d = Math.max(Math.sqrt(dx * dx + dy * dy), 1);
      const pull = (d - 95) * 0.02;
      dx /= d; dy /= d;
      f[e.source].x += dx * pull * d * 0.05; f[e.source].y += dy * pull * d * 0.05;
      f[e.target].x -= dx * pull * d * 0.05; f[e.target].y -= dy * pull * d * 0.05;
    }
    const cool = 1 - it / 220;
    for (const n of nodes) {
      const p = pos[n.id];
      p.x += (f[n.id].x + (w / 2 - p.x) * 0.01) * cool;
      p.y += (f[n.id].y + (h / 2 - p.y) * 0.01) * cool;
      p.x = Math.max(30, Math.min(w - 30, p.x));
      p.y = Math.max(20, Math.min(h - 20, p.y));
    }
  }
  return pos;
}

async function loadMemory() {
  const [graph, { entries }] = await Promise.all([
    fetch(`/api/memory/graph?project_id=${state.projectId}`).then((r) => r.json()),
    fetch(`/api/memory?project_id=${state.projectId}`).then((r) => r.json()),
  ]);
  const list = $("memory-list");
  list.innerHTML = "";
  if (!entries.length) {
    list.innerHTML = '<div class="feed-empty">Project memory — durable facts your team\'s agent has saved, linked into a graph. Plain markdown on disk (an Obsidian-compatible vault).</div>';
    return;
  }
  if (graph.nodes.length > 1 || graph.edges.length) {
    const W = Math.max(list.clientWidth - 8, 480), H = 260;
    const pos = forceLayout(graph.nodes, graph.edges, W, H);
    let svg = `<svg class="memgraph" viewBox="0 0 ${W} ${H}" width="100%" height="${H}">`;
    for (const e of graph.edges) {
      const a = pos[e.source], b = pos[e.target];
      if (a && b) svg += `<line x1="${a.x.toFixed(0)}" y1="${a.y.toFixed(0)}" x2="${b.x.toFixed(0)}" y2="${b.y.toFixed(0)}"/>`;
    }
    for (const n of graph.nodes) {
      const p = pos[n.id];
      svg += `<g class="memnode${n.ghost ? " ghost" : ""}" data-id="${esc(n.id)}">
        <circle cx="${p.x.toFixed(0)}" cy="${p.y.toFixed(0)}" r="9"/>
        <text x="${p.x.toFixed(0)}" y="${(p.y - 14).toFixed(0)}">${esc(n.title.slice(0, 22))}</text></g>`;
    }
    svg += "</svg>";
    const wrap = document.createElement("div");
    wrap.className = "memgraph-wrap";
    wrap.innerHTML = svg + `<div class="meta vault-hint">🗂 vault: ${esc(graph.vault)} — open it in Obsidian for the full graph</div>`;
    list.appendChild(wrap);
    wrap.querySelectorAll(".memnode").forEach((g) => {
      g.onclick = () => {
        const card = list.querySelector(`[data-mem="${g.dataset.id}"]`);
        if (card) { card.scrollIntoView({ behavior: "smooth", block: "center" }); card.classList.add("flash"); setTimeout(() => card.classList.remove("flash"), 1200); }
      };
    });
  }
  for (const e of entries) {
    const card = document.createElement("div");
    card.className = "schedule-card";
    card.dataset.mem = e.name;
    const linkbadges = (e.links || []).map((l) => `<span class="badge">[[${esc(l)}]]</span>`).join(" ");
    card.innerHTML = `<span class="when">🧠 ${esc(e.title)}</span> ${linkbadges}
      <div class="last">${esc(e.preview.split("\n").slice(2).join(" ").slice(0, 220))}</div>`;
    list.appendChild(card);
  }
}

/* ---------- team ---------- */
async function loadTeam() {
  const status = await fetch(`/api/projects/${state.projectId}/status`).then((r) => r.json());
  const proj = state.projects.find((p) => p.id === state.projectId) || { members: [] };
  const view = $("team-view");
  view.innerHTML = "";
  for (const m of state.members) {
    const sessions = status.sessions.filter((s) => s.member_id === m.id);
    const latest = sessions[0];
    const card = document.createElement("div");
    card.className = "schedule-card team-card";
    card.innerHTML = `<span class="avatar" style="background:${esc(m.color || "#888")}">${esc((m.name || "?")[0].toUpperCase())}</span>
      <b>${esc(m.name)}</b>
      <div class="meta">${latest ? `${esc(latest.title || "untitled")} — ${esc(latest.progress || "no note")} · ${fmtTime(latest.updated)}` : "no activity yet"}</div>`;
    view.appendChild(card);
  }
  const active = status.active_runs || [];
  if (active.length) {
    const card = document.createElement("div");
    card.className = "schedule-card";
    card.innerHTML = `<span class="when">🌀 running now</span><div class="meta">${active.map((r) => esc(`${r.kind}: ${r.label}`)).join("<br>")}</div>`;
    view.appendChild(card);
  }
}

/* ---------- files ---------- */
async function loadFiles(path) {
  const r = await fetch(`/api/files?path=${encodeURIComponent(path)}&project_id=${state.projectId}`);
  if (!r.ok) return;
  const data = await r.json();
  state.currentPath = data.path;
  $("file-view").hidden = true;
  renderBreadcrumb(data.path);
  const list = $("file-list");
  list.innerHTML = "";
  for (const e of data.entries) {
    const row = document.createElement("div");
    row.className = "file-row";
    const name = document.createElement("span");
    name.textContent = (e.dir ? "📁 " : "📄 ") + e.name;
    const right = document.createElement("span");
    right.className = "size";
    const childPath = data.path === "." ? e.name : `${data.path}/${e.name}`;
    if (e.versions) {
      const chip = document.createElement("button");
      chip.className = "ghost mini vchip";
      chip.textContent = `🕘 ${e.versions}`;
      chip.title = "Saved versions";
      chip.onclick = (ev) => { ev.stopPropagation(); showHistory(childPath); };
      right.appendChild(chip);
    }
    const sz = document.createElement("span");
    sz.textContent = e.dir ? "" : " " + fmtSize(e.size);
    right.appendChild(sz);
    row.append(name, right);
    row.onclick = () => (e.dir ? loadFiles(childPath) : viewFile(childPath));
    list.appendChild(row);
  }
}

function renderBreadcrumb(path) {
  const bc = $("file-breadcrumb");
  bc.innerHTML = "";
  const root = document.createElement("a");
  root.textContent = "project";
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
  const r = await fetch(`/api/file?path=${encodeURIComponent(path)}&project_id=${state.projectId}`);
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

/* ---------- cost ---------- */
function updateCost(ev) {
  const el = $("cost");
  el.textContent = `$${(ev.cost || 0).toFixed(4)}`;
  el.title = `Session cost — ${(ev.tokens_in || 0).toLocaleString()} in / ${(ev.tokens_out || 0).toLocaleString()} out${ev.priced ? "" : " (model unpriced, cost incomplete)"}`;
  el.classList.toggle("unpriced", !ev.priced);
}

/* ---------- tabs ---------- */
const PANE_LOADERS = { board: loadBoard, pipeline: refreshPipeline, schedules: loadSchedules, checkpoints: loadCheckpoints, memory: loadMemory, team: loadTeam, files: () => loadFiles(state.currentPath) };
for (const tab of document.querySelectorAll(".tab")) {
  tab.onclick = () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".tab-body").forEach((b) => b.classList.remove("active"));
    tab.classList.add("active");
    $(`tab-${tab.dataset.tab}`).classList.add("active");
    PANE_LOADERS[tab.dataset.tab]?.();
  };
}
function refreshPaneData() {
  const active = document.querySelector(".tab.active")?.dataset.tab;
  PANE_LOADERS[active]?.();
}

/* ---------- settings ---------- */
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

function fillEngine() {
  $("eng-compact").value = state.engine.compact_tokens;
  $("eng-keep").value = state.engine.keep_recent;
  $("eng-iter").value = state.engine.max_iterations;
  $("eng-ckpt").checked = !!state.engine.auto_checkpoint;
  if (state.approvalMode) $("eng-mode").value = state.approvalMode;
}

function fillAccount(s) {
  const a = s.account || {};
  $("acct-status").textContent = a.linked
    ? `Linked: ${a.name} <${a.email}> — teammates can add you by email.`
    : "Not linked — get your free key at getbonito.com → Poseidon.";
}
$("acct-link").onclick = async () => {
  const key = $("acct-key").value.trim();
  if (!key) return;
  const r = await fetch("/api/account/link", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key }) });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) { $("acct-status").textContent = d.detail || "link failed"; return; }
  $("acct-status").textContent = `Linked: ${d.name} <${d.email}>`;
  $("acct-key").value = "";
  const s2 = await fetch("/api/state").then((x) => x.json());
  state.members = s2.members; fillMemberSelect();
};

function fillIntegrations(s) {
  const i = s.integrations || {};
  $("int-gmail-email").value = i.gmail?.email || "";
  $("int-slack-channel").value = i.slack?.default_channel || "";
  $("int-status").textContent =
    `Gmail: ${i.gmail?.configured ? "connected" : "not configured"} · Slack: ${i.slack?.configured ? "connected" : "not configured"}`;
}

function fillRules() {
  const box = $("rules-list");
  box.innerHTML = state.rules.length ? "" : '<span class="muted">None yet — approve something with "Always allow".</span>';
  state.rules.forEach((r, i) => {
    const row = document.createElement("div");
    row.className = "rule-row";
    row.innerHTML = `<code>${esc(r.tool)}: ${esc(r.pattern)}</code><button class="ghost mini">✕</button>`;
    row.querySelector("button").onclick = async () => {
      const resp = await fetch(`/api/settings/rules/${i}`, { method: "DELETE" });
      if (resp.ok) { state.rules = (await resp.json()).rules; fillRules(); }
    };
    box.appendChild(row);
  });
}

/* ---------- Codex (ChatGPT-subscription) sign-in ---------- */
let codexPoll = null;

async function refreshCodexStatus() {
  const s = await fetch("/api/codex/status").then((r) => r.json()).catch(() => ({}));
  const badge = $("codex-status");
  badge.textContent = s.linked ? (s.expiring ? "linked (refreshing)" : "linked ✓") : "not linked";
  $("codex-logout").hidden = !s.linked;
  $("codex-signin").textContent = s.linked ? "Re-link" : "Sign in with ChatGPT";
}

$("codex-signin").onclick = async () => {
  const flow = $("codex-flow");
  flow.hidden = false;
  flow.innerHTML = "Starting…";
  const r = await fetch("/api/codex/start", { method: "POST" });
  if (!r.ok) { flow.textContent = (await r.json().catch(() => ({}))).detail || "failed to start"; return; }
  const d = await r.json();
  flow.innerHTML = `Go to <a href="${esc(d.verify_url)}" target="_blank" rel="noopener">${esc(d.verify_url)}</a>
    and enter code <b class="codex-code">${esc(d.user_code)}</b> — then use your ChatGPT model here.
    <div class="muted" id="codex-poll-note">waiting for you to authorize…</div>`;
  window.open(d.verify_url, "_blank");
  clearInterval(codexPoll);
  codexPoll = setInterval(async () => {
    const p = await fetch("/api/codex/poll", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ device_auth_id: d.device_auth_id, user_code: d.user_code }) })
      .then((x) => x.json()).catch(() => ({ status: "pending" }));
    if (p.status === "authorized") {
      clearInterval(codexPoll);
      await fetch("/api/codex/use", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model: "gpt-5.5" }) });
      flow.innerHTML = '✓ Signed in — Poseidon is now using your ChatGPT subscription (gpt-5.5).';
      refreshCodexStatus();
    }
  }, (d.interval || 5) * 1000);
};

$("codex-import").onclick = async () => {
  const r = await fetch("/api/codex/import", { method: "POST" }).then((x) => x.json());
  const flow = $("codex-flow");
  flow.hidden = false;
  if (r.ok) {
    await fetch("/api/codex/use", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ model: "gpt-5.5" }) });
    flow.innerHTML = "✓ Imported your Codex CLI login — using ChatGPT subscription.";
    refreshCodexStatus();
  } else {
    flow.textContent = "No Codex CLI login found (~/.codex/auth.json). Use Sign in with ChatGPT instead.";
  }
};

$("codex-logout").onclick = async () => {
  clearInterval(codexPoll);
  await fetch("/api/codex/logout", { method: "POST" });
  $("codex-flow").hidden = true;
  refreshCodexStatus();
};

function openSettings() { $("settings-modal").showModal(); refreshCodexStatus(); }
$("settings-btn").onclick = openSettings;
$("cfg-cancel").onclick = () => $("settings-modal").close();
$("cfg-save").onclick = async (e) => {
  e.preventDefault();
  const base_url = $("cfg-base-url").value.trim();
  const model = $("cfg-model").value.trim();
  if (base_url && model) {
    await fetch("/api/config", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ base_url, api_key: $("cfg-api-key").value, model }) });
  }
  const r = await fetch("/api/settings/engine", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ compact_tokens: +$("eng-compact").value, keep_recent: +$("eng-keep").value,
      max_iterations: +$("eng-iter").value, auto_checkpoint: $("eng-ckpt").checked,
      approval_mode: $("eng-mode").value }) });
  if (r.ok) state.engine = (await r.json()).engine;
  const integ = { gmail: { email: $("int-gmail-email").value }, slack: { default_channel: $("int-slack-channel").value } };
  if ($("int-gmail-pass").value.trim()) integ.gmail.app_password = $("int-gmail-pass").value.trim();
  if ($("int-slack-token").value.trim()) integ.slack.bot_token = $("int-slack-token").value.trim();
  const ir = await fetch("/api/settings/integrations", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(integ) });
  if (ir.ok) {
    const d = await ir.json();
    $("int-status").textContent = `Gmail: ${d.gmail_configured ? "connected" : "not configured"} · Slack: ${d.slack_configured ? "connected" : "not configured"}`;
  }
  $("settings-modal").close();
};

$("about-link").onclick = (e) => { e.preventDefault(); $("about-modal").showModal(); };
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

/* Procedural planet: new world every hyperjump — palette, bands, clouds,
   craters, ice caps, sometimes rings or a moon. */
let planetSeq = 0;
function planetSVG() {
  const id = `pg${planetSeq++}`;
  const h = Math.floor(Math.random() * 360);
  const light = `hsl(${h},62%,60%)`, base = `hsl(${h},55%,42%)`, dark = `hsl(${h},58%,25%)`;
  let inner = "";
  if (Math.random() < 0.55) {
    const n = 2 + Math.floor(Math.random() * 3);
    for (let i = 0; i < n; i++) {
      inner += `<ellipse cx="100" cy="${(40 + Math.random() * 120).toFixed(0)}" rx="96" ry="${(8 + Math.random() * 16).toFixed(0)}" fill="${Math.random() < 0.5 ? light : dark}" opacity="0.28"/>`;
    }
  }
  if (Math.random() < 0.6) {
    for (let i = 0; i < 4; i++) {
      const x = 25 + Math.random() * 120, y = 30 + Math.random() * 140;
      inner += `<path d="M${x.toFixed(0)},${y.toFixed(0)} q14,-9 30,-3 q16,5 26,-2" stroke="rgba(255,255,255,0.5)" stroke-width="${(5 + Math.random() * 5).toFixed(1)}" fill="none" stroke-linecap="round"/>`;
    }
  }
  if (Math.random() < 0.45) {
    for (let i = 0; i < 5; i++) {
      const r = 4 + Math.random() * 9, x = 45 + Math.random() * 110, y = 45 + Math.random() * 110;
      inner += `<circle cx="${x.toFixed(0)}" cy="${y.toFixed(0)}" r="${r.toFixed(1)}" fill="${dark}" opacity="0.6"/><circle cx="${(x - r * 0.25).toFixed(0)}" cy="${(y - r * 0.25).toFixed(0)}" r="${(r * 0.65).toFixed(1)}" fill="${base}" opacity="0.55"/>`;
    }
  }
  if (Math.random() < 0.35) {
    inner += `<ellipse cx="100" cy="26" rx="46" ry="16" fill="rgba(255,255,255,0.75)"/><ellipse cx="100" cy="176" rx="40" ry="14" fill="rgba(255,255,255,0.55)"/>`;
  }
  const ring = Math.random() < 0.3;
  const ringCol = `hsl(${(h + 45) % 360},48%,72%)`;
  const moon = Math.random() < 0.35
    ? `<circle cx="183" cy="36" r="9" fill="#b9c0cc"/><circle cx="180" cy="34" r="3" fill="#98a0ad"/>`
    : "";
  return `<svg viewBox="0 0 200 200" width="100%" height="100%"><defs>
    <radialGradient id="${id}b" cx="38%" cy="35%"><stop offset="0%" stop-color="${light}"/><stop offset="70%" stop-color="${base}"/><stop offset="100%" stop-color="${dark}"/></radialGradient>
    <linearGradient id="${id}t" x1="0" y1="0" x2="1" y2="0.25"><stop offset="55%" stop-color="rgba(2,6,18,0)"/><stop offset="100%" stop-color="rgba(2,6,18,0.55)"/></linearGradient>
    <clipPath id="${id}c"><circle cx="100" cy="100" r="80"/></clipPath></defs>
    <circle cx="100" cy="100" r="87" fill="${light}" opacity="0.13"/>
    ${ring ? `<ellipse cx="100" cy="100" rx="128" ry="30" fill="none" stroke="${ringCol}" stroke-width="7" opacity="0.5" transform="rotate(-18 100 100)"/>` : ""}
    <circle cx="100" cy="100" r="80" fill="url(#${id}b)"/>
    <g clip-path="url(#${id}c)">${inner}<rect width="200" height="200" fill="url(#${id}t)"/></g>
    ${ring ? `<path d="M-28,100 A128,30 0 0 0 228,100" transform="rotate(-18 100 100)" fill="none" stroke="${ringCol}" stroke-width="7" opacity="0.85"/>` : ""}
    ${moon}</svg>`;
}

const PLANET_SPOTS = [
  { left: "8%", top: "15%" }, { right: "13%", top: "13%" }, { left: "12%", bottom: "16%" },
  { right: "9%", bottom: "20%" }, { left: "40%", top: "7%" },
];
function rollPlanet(el) {
  const spot = PLANET_SPOTS[Math.floor(Math.random() * PLANET_SPOTS.length)];
  el.style.left = el.style.right = el.style.top = el.style.bottom = "auto";
  Object.assign(el.style, spot);
  const size = 150 + Math.floor(Math.random() * 130);
  el.style.width = el.style.height = `${size}px`;
  el.innerHTML = planetSVG();
}

function trekScene() {
  return `<div class="nebula n1"></div><div class="nebula n2"></div><div class="nebula n3"></div><div class="nebula n4"></div>
    ${starsSVG(260, 0.8, "l1")}${starsSVG(150, 1.2, "l2")}${starsSVG(70, 1.8, "l3")}
    <div class="planet"></div>
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

/* Ukiyo scene sprites in static/img/ are the user's own AI-generated art
   (license-clean): wave1-5.png + cloud1-9.png, background-extracted. */
function ukiyoScene() {
  const sway = () =>
    `animation-duration:${(5 + Math.random() * 4).toFixed(1)}s;animation-delay:${(-Math.random() * 8).toFixed(1)}s`;
  const flip = () => (Math.random() < 0.4 ? "transform:scaleX(-1)" : "");
  const wave = () => `wave${1 + Math.floor(Math.random() * 5)}.png`;

  // The sea flows in one direction: each row is a 200vw conveyor track
  // (waves duplicated at +100vw) drifting left and wrapping seamlessly.
  // Individual waves bob up and down on their own rhythm.
  const bob = () =>
    `animation-duration:${(3 + Math.random() * 3).toFixed(1)}s;animation-delay:${(-Math.random() * 6).toFixed(1)}s`;
  const buildRow = (cls, step, wMin, wVar) => {
    let row = "";
    for (let left = -4; left < 96; left += step) {
      const w = (wMin + Math.random() * wVar).toFixed(1);
      const x = (left + Math.random() * 3 - 1.5).toFixed(1);
      const sprite = wave(), f = flip(), bb = bob();
      for (const off of [0, 100]) {
        row += `<div class="uk-wave ${cls}" style="left:${(parseFloat(x) + off).toFixed(1)}vw;width:${w}vw;${bb}"><img src="/static/img/${sprite}" alt="" style="${f}"></div>`;
      }
    }
    return row;
  };
  const waves =
    `<div class="uk-track uk-track-back">${buildRow("back", 8, 6, 6)}</div>` +
    `<div class="uk-track uk-track-front">${buildRow("front", 9, 11, 8)}</div>`;

  let clouds = "";
  const pool = [1, 2, 3, 4, 5, 6, 7, 8, 9].sort(() => Math.random() - 0.5);
  [
    [6, 6, 170], [38, 13, 130], [66, 11, 200], [88, 19, 110],
  ].forEach(([left, top, w], i) => {
    clouds += `<div class="uk-cloud" style="left:${left}%;top:${top}%;width:${w}px;${sway()}"><img src="/static/img/cloud${pool[i]}.png" alt=""></div>`;
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
  trek(scene) {
    rollPlanet(scene.querySelector(".planet"));
  },
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
    const planet = scene.querySelector(".planet");
    scene.classList.add("jumping");
    if (planet) planet.classList.add("departing");
    skinTimers.push(setTimeout(() => {
      // arrive at a new world as the streaks fade
      if (planet) {
        rollPlanet(planet);
        planet.classList.remove("departing");
        planet.classList.add("arriving");
        skinTimers.push(setTimeout(() => planet.classList.remove("arriving"), 900));
      }
    }, 900));
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
