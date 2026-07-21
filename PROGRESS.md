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

## v0.12.0 (2026-07-21) — the token-cost edge
- retrieval.py: local BM25 (bag-of-words) + Jaccard, zero deps, nothing leaves the machine.
- search_memory tool: keyword-rank memories vs dumping the whole index; scales memory.
- compress.py: on-device context compression — dedupe re-sent blocks (file re-reads etc.),
  keep latest copy, stub earlier identical ones. Deterministic, no answer change.
- MEASURED: 35.7% input tokens saved on a session re-reading a 40KB source file x4.
  Workload-dependent (re-read frequency x content size). Visible green "saved N tok (X%)"
  chip next to the cost meter — provable in-product, not a marketing claim.
- Positioning: "Use Poseidon for work, save on token costs free out of the box" — grounded
  in the D71/Azzy cost study, now shipped + measured.
- NOTE: BoW was NOT previously in Poseidon (recall was index-injection + wikilink graph);
  it is now. Next levers if wanted: framing compression (D71 ~12%) + complexity-aware
  routing (composes with the failover chain) for a bigger, more consistent %.

## Roadmap / shelved (token savings)
- SHIPPED (v0.12.0): dedup compression — drops re-sent identical content (file re-reads,
  repeated tool output). Measured 34% on re-read-heavy coding, ~0% on chat/read-once.
  This is MY method, not the study's. Visible "saved X%" chip.
- SHELVED — port the D71/Azzy study's actual compress() (~/Desktop/code/ledger-recon/
  optimization/run_opt.py). It is RULE-BASED REGEX (drop filler phrases like "please always
  remember that", phrase swaps "in order to"->"to", collapse list redundancy), NOT BoW.
  Measured 12% avg / 20% on bloated enterprise prompts, 6/6 quality-validated. Caveat:
  targets verbose corporate prompts; Poseidon's lean prompt would save less. Stack it with
  the dedup when picked up.
- SHELVED — dynamic model routing (study's 67% lever, keyword+token-count). Biggest saving
  but task complexity isn't reliably inferable from a short prompt -> mis-route risk. Ship
  only as transparent + conservative + opt-in.
- NOTE (correction): BoW was NEVER in the ledger-recon study (grepped: no bag-of-words/
  TF-IDF/BM25/Jaccard anywhere). The study = rule-based compression + keyword routing +
  (unbuilt) embedding cache. The BM25 in Poseidon is for memory SEARCH, unrelated to savings.
