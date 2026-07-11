# Poseidon Architecture (v0.5 — the "real product" cut)

*Design of record. Written 2026-07-11.*

## Object model

Everything an agent does is a **Run**. Runs form a tree. The UI is a projection
of the run tree; collaboration is shared access to the same store.

```
Member      — who: local profile (Netflix-style; token auth in server mode later)
Project     — where: workdir + team + shared memory + everything below
 ├─ Membership (member ↔ project, role)
 ├─ Session   — a conversation: messages, title, owner, progress note, cost
 │   └─ Checkpoint — snapshot: messages + progress + touched-file contents (auto after
 │                   write/run turns, or manual); reviewable, restorable
 ├─ Run       — one unit of agent work. kind: chat | background | scheduled | subagent
 │   ├─ parent_run_id  → the tree (chat turn → subagents; schedule → run → subagents)
 │   └─ RunEvent[]     — persisted event stream (drill-down, pipeline reconstruction)
 ├─ Schedule  — cron source: fires scheduled Runs (unattended: approval rules only)
 └─ Memory    — markdown files + MEMORY.md index, scoped per project (team-shared)
```

## Engine flows

**Chat turn** → Run(kind=chat) under the session. Subagent calls become child
Runs (parallel fan-out preserved). Every emitted event is (a) pushed to the
session SSE channel, (b) pushed to the project SSE channel, (c) persisted as a
RunEvent (capped/run).

**Background task** → `start_background_task` meta-tool returns a run_id
immediately; a detached loop (own message list, project workdir) executes it.
Unattended: approval-gated tools auto-deny unless an "always allow" rule covers
them (trust is granted in advance, never assumed). Result lands on the Run;
`run_status` / the Pipeline pane pick it up.

**Scheduled run** → Scheduler fires → fresh session + Run(kind=scheduled), same
unattended rules. Schedules appear as source nodes in the Pipeline.

**Context management** — before each model call, if the estimated token count
exceeds POSEIDON_COMPACT_TOKENS (default 24k), everything but the system prompt
and the most recent turns (boundary walked back to a user message so no orphan
tool results) is summarized by the model into one `[Compacted history]` system
message. Emits a `compacted` event.

**Progress** — every turn ends by updating `session.progress`: the model can
call `set_progress` explicitly (encouraged for significant work); otherwise the
final assistant text is truncated in as a fallback. Progress is what teammates
(and the "Project pulse") see.

**Checkpoints** — auto after any turn that executed an approval-gated tool
(label = the user ask), manual via `save_checkpoint`. Snapshot = messages +
progress + contents of files touched this turn (≤20 files, ≤64KB each).
Review shows meta + files; restore rewinds the conversation state.

**Teams / handoff** — the system prompt carries a **Project pulse**: recent
sessions (owner, progress, when), active runs, schedules. So "where did
Catherine leave off?" is answerable from turn one, and `project_status` gives
the detail on demand. Any member can open any session and continue it.

## Surfaces

- **Pipeline pane (default)** — live node graph of the run tree: schedule
  sources → top-level runs → subagent children. Status-colored, click a node
  for the drill-down overlay (events timeline, result, cost). This is the
  "press ↓ to see background processes" for non-technical people.
- Activity / Tasks / Files / Runs / Schedules / Checkpoints / Team panes.
- Header: project switcher + member profile switcher. Session drawer on the
  chat pane: continue any session, see owner + progress at a glance.

## Deployment model

Local-first single binary stays (`poseidon [path]`). Team mode = run the same
server on a shared box (e.g. a Mac mini) and everyone opens it in a browser
picking their profile. Real auth (per-member tokens), TLS, and remote access
are the server-mode roadmap; the data model is already multi-tenant by project.

## Files

```
store.py         all persistence (projects/members/sessions/runs/events/checkpoints), migrations
runs.py          RunManager: run lifecycle + event bus (session & project channels) + spawn
orchestrator.py  agent loop, meta-tools, compaction, progress, checkpoints
scheduler.py     cron source → scheduled runs
memory.py        project-scoped markdown memory
server.py        FastAPI routes + SSE
static/          vanilla JS UI (panes, pipeline SVG renderer, drawer, overlays)
```
