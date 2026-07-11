# Poseidon — Plan

*Save-file for the vision. Written 2026-07-10.*

## What this is

A standalone open-source agent harness — **not a Bonito product**, just made by the
team (like Goose is "by Block"). Installs with one command, opens as a chat in the
browser, runs the agent on *your* machine against *your* choice of model.

The strategic model: free, habit-forming daily tool → credibility + inbound for
Bonito ("customers for life"). Bonito appears exactly twice: the About page, and a
provider preset that happens to work suspiciously well. **No banner ads, no nags** —
OSS crowds punish adware; restraint is what makes the funnel work.

## Positioning

The market phase-gap: buyers are stuck in the **chat phase**; enterprise agent
adoption is stuck in the **co-work phase**. Poseidon meets both in the middle —
chat-shaped on the surface, a real harness underneath, with supervised autonomy
that graduates.

| | Terminal? | UI? | Open? | Any model? | Cost visibility? |
|---|---|---|---|---|---|
| Claude Code / Codex / Gemini CLI | yes | terminal | partially | no | weak |
| Claude Cowork | no | desktop app | **closed** | **Anthropic only** | no |
| OpenClaw | setup-heavy | none (lives in WhatsApp/Telegram) | yes | yes | no |
| OpenHands | Docker | browser | yes | yes | no |
| **Poseidon** | **no** | **browser split-pane** | **yes** | **yes** | **built-in** |

One-liner: *open-source Cowork — OpenClaw's warmth, Claude Code's hands, Replit's
"watch it work" pane, nobody's terminal.*

## Differentiation thesis

Do NOT differentiate on the agent loop (commodity). Differentiate on:

1. **Watch-it-work UI** — split-pane: chat left, workspace right (Activity / Files
   tabs; Terminal + diff viewer later). The spreading mechanism: the only harness a
   non-terminal person can use.
2. **The trust dial** — approval cards inline in chat with previews;
   "always allow" persists pattern rules (`git *`, `src/*`). Everyone else is
   binary (YOLO mode or nag mode). This is the co-work→autonomous bridge as UI.
3. **The harness that knows what it costs** — live cost meter (per session/model,
   tokens in/out), later failover + cheap-model routing. Nobody in OSS does this,
   it's the team's DNA (built 3x for Bonito), and it pre-teaches the exact mental
   model Bonito monetizes. The funnel in disguise.

**The "sticks" list (do NOT deviate):** `AGENTS.md` for project instructions (the
existing standard, not a new format) ✅ shipped · MCP for extensibility (signal early,
ship v0.2) · OpenAI-compatible provider config ✅ · tool permissions ✅ · session
history ✅ (persisted, resume-UI later).

## Architecture (v0.1 — shipped in this scaffold)

```
poseidon-ai (PyPI)  →  `poseidon [path]`  →  FastAPI on 127.0.0.1:4747  →  browser opens
├── cli.py            entry point, arg parsing, browser launch
├── server.py         routes: /api/state|config|sessions|chat|events(SSE)|approvals|files|file
│                     localhost-only Host check (DNS-rebinding guard)
├── orchestrator.py   OpenAI-compat tool loop (httpx), AGENTS.md pickup,
│                     tool_call_id always attached (learned that one the hard way)
├── tools/            list_dir, read_file, write_file*, edit_file*, run_command*, web_fetch
│                     (* = approval-gated; paths jailed to workdir)
├── approvals.py      broker: pause turn → SSE card → resolve; "always" saves fnmatch rule
├── sessions.py       SQLite (~/.poseidon/sessions.db): messages + cost per session
├── costs.py          static price table by model substring; unknown = $0 flagged "unpriced"
└── static/           vanilla JS split-pane UI (no build step, bundled in the wheel)
```

Decisions made:
- **Python + FastAPI** (team DNA), **hatchling**, publish as **`poseidon-ai`**
  (PyPI `poseidon` is squatted by a dead DigitalOcean wrapper; command is still
  `poseidon`; PEP 541 reclaim = maybe later, don't block).
- **Vanilla JS UI for v0.1**, no Node in the build. Upgrade to React/Vite when the
  UI earns it (bundle static output into the wheel, same serving path).
- **Raw OpenAI-compat client, not LiteLLM** (for now) — covers Ollama/OpenAI/Groq/
  Bonito/custom with one code path and zero heavy deps. Revisit for Anthropic-direct.
- **Clean-room port** of the Origami orchestrator *patterns* (tool_call_id, idempotent
  tools, SSE event shapes) — no proprietary code or history in this repo.
- Non-streaming completions per iteration (robust > flashy for v0.1).

## Roadmap

**v0.2 — agentic core ✅ (shipped 2026-07-10):** task planning (`set_tasks` →
live checklist tab), parallel subagents (`run_subagent`, fan-out via gather),
scheduled runs (`schedule_task` / Schedules tab, SQLite + 20s poll loop;
unattended runs auto-deny anything without an "always allow" rule — trust is
earned first). Light "waves" UI: daylight palette, slow left↔right water wave
along the bottom (Windows-7-login vibe), reduced-motion respected.

**v0.3 — persistent memory ✅ (shipped 2026-07-10, file school):** markdown files
in `~/.poseidon/memory/` + `MEMORY.md` index injected into the system prompt each
session; `save_memory` / `read_memory` / `forget_memory` tools. Transparent by
design — the user can open and edit their agent's memory in a text editor.

**Memory A/B experiment (do NOT drop the vector school):** once file memory has
real usage, build a vector recall path (embed memories, similarity search at
turn start — local embeddings via Ollama, or any OpenAI-compat embedding endpoint)
behind a `memory_backend: files | vector | hybrid` config flag, and A/B them on
the same memory corpus: recall hit-rate, precision (irrelevant-memory injections),
token cost per turn, and "did the agent ask something it should have known".
Hypothesis from Bonito scar tissue: files win under ~200 memories on transparency
+ zero silent-failure modes (threshold/dim-mismatch bugs); vector starts winning
on recall once the index outgrows the prompt budget. Hybrid (index in prompt +
vector fallback search) is the likely end state. Lessons to port: similarity
thresholds tuned empirically (0.5 not 0.7), embedding-dim clamping, never fail
silently — log recall misses.

**v0.4 — skins ✅ (shipped 2026-07-10):** skin system — CSS-variable palettes +
per-skin vector scenes (crisp SVG, no low-poly), picker in header, persisted in
localStorage. Shipped: **Poseidon** (base daylight waves), **Trek Wars** (deep-space
starfield, 3 parallax layers + twinkle, nebulae, shooting stars, occasional
hyperjump burst), **Ukiyo-e** (woodblock indigo waves scrolling on aged paper,
foam-pearl crests + spiral curls, red sun, dash clouds), **Wasteland** (harsh sun
haze, parallax dunes + derrick silhouette, drifting dust, heat shimmer, rolling
tumbleweed). All reduced-motion safe. More skins are cheap now: palette block +
scene builder.

**v0.5 — the product cut ✅ (shipped 2026-07-11):** unified Run object model
(chat/background/scheduled/subagent as one tree), teams (member profiles,
shared projects, Project pulse handoff, project_status), background tasks,
automatic context compaction, session progress notes, auto/manual checkpoints
with review + rewind, Pipeline pane (live run-tree diagram + drill-down event
timelines), Sessions drawer, Team/Memory/Checkpoints panes, Settings surface
(engine knobs + always-allow rule management), provider-error resilience
(retry + malformed-tool-call nudge + text fallback). E2E-proven on a real
model (Groq llama-3.3): Family Assistant scenario — approval-gated writes,
trust-dial always-allow enabling unattended background writes, daily schedule,
teammate status pickup. See ARCHITECTURE.md.

**v0.5.x — server mode:** `poseidon serve` on a shared box (per-member tokens,
TLS guidance) so teams use one instance from their browsers; Duncan-Lane-scale
external integrations (gmail/slack connectors as tools).

**v0.4.x — feel alive:** token streaming; diff viewer for edit approvals (side-by-side);
session list + resume UI; Terminal tab (live run_command output); Ollama autodetect
in onboarding + friendly connection errors ("is Ollama running?"); markdown
rendering in chat.

**v0.3 — the cost story:** per-model cost breakdown pane; daily spend; failover
chains (primary → fallback model on 429/5xx — the Bonito trick, local); optional
cheap-model routing for simple turns.

**v0.4 — extensibility:** MCP client support (the ecosystem play); skills/custom
tools; multiple concurrent sessions; headless mode (`poseidon serve` on a Mini,
auth token).

**Launch (after v0.2):** demo video (creative-pipeline eats its own dog food),
Show HN — headline angle: *fully local agent with a real UI, zero API key, watch it
work* — Product Hunt (existing launch infra), README GIF above the fold.

Maintenance budget: a few hours/week. An abandoned repo with 40 open issues is
negative advertising — scope stays small enough to keep alive.

## Open items

- [ ] GitHub org + remote (`bonito-ai-labs/poseidon`?) — decide handle, push, public from day one
- [ ] PyPI: register `poseidon-ai` early (squat protection)
- [ ] Logo / social card (fish + trident)
- [ ] Security pass before launch: approval-rule patterns review, symlink escape
      check on the workdir jail, localhost token option
- [ ] Test suite (the loop, approval broker, path jail — pytest + httpx TestClient)
