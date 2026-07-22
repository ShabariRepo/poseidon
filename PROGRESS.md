# Poseidon — session save (2026-07-22)

Remote: github.com/ShabariRepo/poseidon (PUBLIC). Editable install runs via
`.venv/bin/poseidon ~/Desktop/code/poseidon --no-browser` on :4747.
ALWAYS restart the process after code changes — no hot-reload.
Push over SSH is broken (id_ed25519 is the mini key, not GitHub); origin push
URL is now `https://ShabariRepo@github.com/...` + gh credential helper — works.

## Shipped this session (all pushed)
- v0.15.0: Pipeline + Memory diagrams rebuilt on vis-network (vendored, MIT).
  Hierarchical LR DAG when subagent edges exist, physics cloud otherwise;
  status colors, dashed schedule nodes, themed tooltips, click-to-drill,
  ?tab=/?project= deep links. Published to PyPI (manual twine; twine HUNG
  post-upload once — the file was actually uploaded, verify on pypi before
  re-uploading).
- CI→PyPI: release.yml publishes via PYPI_API_TOKEN repo secret (skip-existing
  on). PROVEN: v0.15.1 tag → publish-pypi job SUCCESS → live on PyPI with zero
  manual steps. Binary jobs (mac/win) queue slowly on public runners; the
  GitHub Release auto-creates when they finish.
- Repo hardening: main branch protection (PR required, 1 approval, no force
  push/deletions; admins bypass so owner can still push directly), fork-PR
  workflows need approval for ALL external contributors, secrets invisible to
  fork PRs. Anyone can PR; only owner can merge.
- v0.15.1: graceful step-cap handoff — orchestrator forces a final text-only
  done/left/pickup summary before the "Stopped after N steps" error chip.
  Found in the Vintner test (Yuki's turn died capless with work complete but
  no handoff). Tests 26/26.

## Vintner Studio field test (the big one) — PASSED
Recreated the original client creative studio as "Vintner Studio" (~/Desktop/vintner-studio)
via 3 simulated members (Dana/Marco/Yuki), 9 turns, codex gpt-5.5 primary:
board plan → backend via 3 PARALLEL SUBAGENTS → Yuki sandbox branch → clean
promote → OpenAI image gen wired → app self-hosted on :5050 (venv self-heal) →
2 real Harvest Moon assets (label-legible, scored 75/82 in the app's own review
UI) → daily 09:00 schedule → pulse. Mid-test the FREE ChatGPT plan quota died
(codex 429, resets ~28d) — armed Groq fallback via /api/config/fallbacks and
failover completed the remaining turns (2 sticky failover events). Cost:
1.86M tokens sent, 925K saved by on-device dedup (33.2%; Yuki's re-read-heavy
session saved MORE than it sent, 54.8%), $0 marginal LLM spend.
Report artifact (screenshots embedded):
https://claude.ai/code/artifact/23dece11-745b-471a-9ee7-a42a236d5f67

## Open findings (from the test)
- Fallback chain ships UNARMED — codex outage hard-failed turns until armed.
  Auto-arm from vault keys or onboarding nudge. (This box now has Groq armed.)
- max_iterations default 25 too low for coding turns (this box now 40).
- Sandbox diff API is per-file only (?path= required) — no aggregate diff.
- Agents reassign board cards to "poseidon" when moving them — attribution
  drifts; update_work_item wants a keep-assignee default.
- Linked ChatGPT account is FREE plan — quota gone until ~Aug 19. Link paid
  account or rely on failover.
- llama-3.3 fallback voice credits work to "Poseidon" not member names (model).
