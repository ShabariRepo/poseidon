# Poseidon — session save (2026-07-20/21)

Remote: github.com/ShabariRepo/poseidon. Editable install runs via
`.venv/bin/poseidon ~/Desktop/code/poseidon --no-browser` on :4747.
ALWAYS restart the process after code changes — it doesn't hot-reload
(an 8-day-stale process caused a batch of phantom "bugs" this session).

## Shipped this session (all pushed)
- v0.11.0 FAILOVER CHAIN: settings UI + POST /api/config/fallbacks; per-provider
  key vault (config.provider_keys) so keys survive preset hopping. Positioning:
  free failover-lite in OSS, paid smart routing = the Bonito Gateway preset
  (nudge in settings), NOT a paywalled local router.
- Settings truthfulness: preset matches the configured provider (was stuck on
  Ollama); blank API-key field keeps the saved key (was silently wiping it).
- All-time cost visible in the header chip (session · total).
- QA-driven fixes: codex/ChatGPT provider now actually runs turns (base_url
  gate + store:false); failover catches transport errors (DNS-dead) + is sticky
  (no duplicate events).
- UI polish: assistant bubbles render inline markdown (no literal **); codex
  cost chip reads "included" not $0; Careful-mode warns when a standing
  always-allow rule overrides it.

## QA campaign
Full end-to-end harness test — 3-member ad-ops team sim (Catherine/Marcus/Priya),
~26 scored turns, per-user Playwright screenshots. Report:
~/Desktop/poseidon-qa-report-2026-07-20.html (self-contained, stamped with fixes).
All team/approval/sandbox/checkpoint/schedule/subagent/failover features verified.

## Open (not blocking)
- Standing `write_file *` always-allow rule on this machine softens Careful mode
  (now surfaced in UI; Shabari may want to delete it in Settings → rules).
- Model residuals only: llama-3.3 answer variance, codex sometimes uses
  run_command over edit_file. Not harness bugs.
- Version dockerization NOT done (no Dockerfile; wheel + PyInstaller only).
