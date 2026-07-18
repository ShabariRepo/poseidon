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

**v0.6 — teamwork layer ✅ (shipped 2026-07-12):** the "git for non-developers"
cut. (1) **File versions**: every agent write/edit auto-snapshots (who, when,
and *which ask caused it*); outside edits captured before overwrites so nothing
is ever lost; Files pane shows 🕘 chips → history with friendly colored
"What changed" diffs and one-click Restore (restore itself is versioned).
Content-addressed blob store + SQLite metadata. (2) **Work Board** (default
pane): todo/doing/review/done kanban the AGENT keeps updated via
add/update/list_work_items — cards carry member or 🔱 Poseidon avatars, linked
files, notes; humans add/move/delete in UI; "review" column = check each
other's work. (3) **Office files**: read_document (xlsx/docx/pdf) +
edit_spreadsheet (gated + versioned) — the real Drive-and-spreadsheets
workload. Google Drive strategy: point the project workdir at a Drive for
desktop synced folder — versioning/board layer on top, zero OAuth.
(4) scripts/install.sh one-liner (activates once published to PyPI).

**v0.9.1 — context meter ✅ (shipped 2026-07-16):** out-of-the-box context
handling. Auto-summary threshold raised 24k → 198k tokens (200k-class models;
configs still on the old 24k default are migrated in place, custom values
untouched), summarizer dump/brief caps scaled to match. New context meter in the
chat toolbar: progress bar showing session fill vs the compact line (amber ≥70%,
red ≥90%), click for a plain-language explainer with live token counts. Fed by a
`context` SSE event each turn + the session endpoint on load. Small-window
models (Groq llama ~131k) should lower the threshold in Settings → Engine.

**v0.9.2 — per-provider context window ✅ (shipped 2026-07-16):** the compact
threshold now adapts to the model's real window instead of assuming 200k.
Provider config gains an optional `context_window` (presets ship sensible
values: OpenAI 128k, Groq 131k, Ollama 32k conservative, Bonito 200k; settable
in Settings → Provider, default 200k). Effective threshold =
`min(compact_tokens, window − 2k)` (8k floor) — used by auto-summary, the
summarizer dump cap, and the context meter's limit, so Groq llama compacts at
~129k instead of erroring at the provider before 198k.

**v0.10 — sandbox mode ✅ (shipped 2026-07-16):** branches for non-developers,
completing the "git for non-devs" story (versions = commits, sandbox = branch,
promote = merge, working tree = git status). Per-session 🧪 toggle clones the
project folder copy-on-write (APFS clonefile / reflink, shutil fallback) into
~/.poseidon/sandboxes/ and swaps the tool jail to the clone — files, edits,
and command cwd all follow; the real folder is untouched. Outward sends
(email/Slack) are HARD-blocked in a sandbox. Working-tree review overlay:
added/changed/deleted chips, conflict flags (real folder moved underneath),
per-file inline diffs, per-file checkboxes → Promote (applies through the
version store, so the merge itself is reversible file by file) or Discard.
Sandbox writes skip main version history — drafts enter history only at
promotion. Also the repo's FIRST test suite: tests/test_sandbox.py (8 tests —
clone/status/diff/promote/conflicts/discard-jail). Versions reconciled to
0.10.0 in both pyproject.toml and __init__.py (publish prep).

**v0.10.x — UI professional pass ✅ (2026-07-18):** CSS-first visual polish to
compete with modern dev tools (Linear/shadcn-calibre). One coherent component
system replacing the layered refinement passes: real type scale (10–17px,
500/600 weights, letter-spaced small-caps section labels, tabular-nums on all
meters/timestamps), uniform control heights (30px header controls / 28px mini /
34px default / 42px composer), consistent radii (8px controls, 10px cards, 16px
dialogs), color-mix borders + subtle two-layer shadows with hover elevation on
interactive cards, :focus-visible rings, first-class composer focus glow.
Settings dialog rebuilt: scrollable body + sticky footer, backdrop blur/dim,
divided sections, styled inputs. Dock: monochrome-at-rest icons, accent-soft
active pill (no bouncy hover). Thin styled scrollbars, centered empty states,
hidden-until-hover board card controls. Fixed 3 real bugs: trek skin dock
labels were unreadable (`button` color override out-specified `.tab`),
`[hidden]` elements shown (display reset beat the UA rule — Sign-out button
leaked into Settings), and focus rings drawn on scroll containers. All 4 skins
verified via Playwright screenshots; skin var contract untouched; app.js
untouched; 17 tests green.

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

**Publish prep done 2026-07-16:** wheel verified (static UI bundles, 47 files),
cold `pip install` from wheel boots clean, 17-test suite (sandbox + path jail +
approval broker/trust dial + pattern derivation + config migration + compact
threshold), gitleaks full-history scan CLEAN (26 commits), repo git identity
set to the ShabariRepo noreply address, Codex sign-in marked experimental in
README. CI workflow (pytest matrix) + release workflow (tag → wheel/sdist →
PyPI trusted publishing → PyInstaller Mac arm64/x86_64 + Windows binaries →
GitHub Release) + PyInstaller spec in packaging/ — local frozen build verified
(62MB onedir, boots, UI + static 200). Signing TODOs marked in release.yml.
Distribution decision: GitHub Releases is the canonical download; the Bonito
site gets a "Labs" page that links there (keeps the OSS posture).

- [ ] DECIDE: GitHub handle (`bonito-ai-labs/poseidon`?) → transfer, flip public
- [ ] PyPI: register `poseidon-ai` (verified still free 2026-07-16 — squat risk)
      + set up trusted publishing for the release workflow
- [ ] Apple Developer enrollment ($99/yr, days of lead time) + Windows signing
      (Azure Trusted Signing ~$10/mo) — needed before installers are linked publicly
- [ ] Codex OAuth live validation (10-min browser session) — shipped as experimental
- [ ] Logo / social card (fish + trident); README GIF above the fold
- [ ] Mac menu-bar launcher nicety (v2 of the installer)
- [ ] Symlink escape review on the workdir jail (resolve() handles the common
      case — tested; a symlink INSIDE the tree pointing out deserves a look)
