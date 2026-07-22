# Poseidon — distribution & install

## Honest current state (2026-07-21)

Everything is **scaffolded but not yet live**. Before Poseidon can be "download from the Bonito site" or "one-line install," two one-time actions are needed (both are yours — they need accounts/credentials I can't touch):

| Piece | State | Blocker to go live |
|---|---|---|
| PyPI package (`poseidon-ai`) | **NOT published** | The advertised `pipx install poseidon-ai` and the curl one-liner both FAIL today. Configure PyPI **trusted publishing** for this repo, then push a `v*` tag → `release.yml` publishes it. |
| Standalone binaries (Mac/Win/Linux) | Built by `release.yml` on tag, but **unsigned** | Mac needs an **Apple Developer ID** ($99/yr) + notarization; Windows needs code-signing. Unsigned = scary OS warnings, so not linkable on the Bonito site until signed. |
| `release.yml` CI | Ready (wheel→PyPI + PyInstaller matrix, now incl. Linux) | Just needs a pushed tag + the two account setups above. |
| Windows installer | **Added today** (`scripts/install.ps1`) | — |

So: **nothing installs cleanly for a stranger right now.** The rails exist; the two account setups + a tag flip it on.

## Two ways to ship (pick based on audience)

### Option A — one-line install (needs Python). Cheapest, works this week.
Publish to PyPI, then host these on `getbonito.com/poseidon`. Requires the user to have **Python 3.10+**.

- **Mac / Linux:** `curl -fsSL https://getbonito.com/poseidon/install.sh | sh`
- **Windows (PowerShell):** `irm https://getbonito.com/poseidon/install.ps1 | iex`
- **Any OS with Python, manual:** `pipx install poseidon-ai` then `poseidon ~/my-project`

Pros: trivial to maintain (publish once, works everywhere). Cons: assumes Python — fine for developers, a barrier for non-technical consumers.

### Option B — downloadable app (no Python). Best consumer UX, needs certs.
`release.yml` already builds standalone binaries (bundled Python) per OS on a tag:
`poseidon-macos-arm64`, `poseidon-macos-x86_64`, `poseidon-windows-x86_64`, `poseidon-linux-x86_64`.

Host them on the Bonito site + GitHub Releases. **Must be signed first:**
- **macOS:** codesign with a Developer ID cert + `notarytool` submit + staple. Without it, Gatekeeper blocks ("developer cannot be verified"). Cert = Apple Developer Program, $99/yr.
- **Windows:** code-sign the `.exe` (Azure Trusted Signing or an OV cert). Without it, SmartScreen warns. Runs, but looks unsafe.
- **Linux:** no signing needed; ship the tarball (or wrap as an AppImage later).

Pros: double-click, no Python, true consumer app. Cons: per-OS builds (CI handles it), plus the signing certs + notarization step.

## Recommended rollout
1. **Now:** configure PyPI trusted publishing → push a `v0.14.0` tag → `pipx install poseidon-ai` and both curl/irm one-liners work. Put the one-liners on getbonito.com/poseidon. Ship to developer-ish users immediately.
2. **Then (for the mass-consumer download):** get the Apple Developer cert + Windows signing, wire the two signing steps into `release.yml` (TODOs are already marked there), and link the signed binaries on the Bonito site.

## Per-OS install steps (once PyPI is live)

**macOS**
1. Have Python 3.10+ (`python3 --version`; if missing, `brew install python` or python.org).
2. `curl -fsSL https://getbonito.com/poseidon/install.sh | sh`
3. Poseidon opens in your browser. First run auto-opens Settings — pick a connection (ChatGPT sign-in, an API key, Bonito Gateway, or local Ollama).

**Linux**
1. Python 3.10+ (`python3 --version`; `apt install python3 python3-venv` etc. if needed).
2. `curl -fsSL https://getbonito.com/poseidon/install.sh | sh`
3. Same first-run flow.

**Windows**
1. Install Python 3.10+ from python.org — **check "Add python.exe to PATH"** during setup.
2. Open PowerShell → `irm https://getbonito.com/poseidon/install.ps1 | iex`
3. Same first-run flow.

**Any OS, developer path (no installer):**
`pipx install poseidon-ai && poseidon ~/my-project` (or `pip install poseidon-ai` in a venv).

## What runs where
Poseidon is a local server (FastAPI/uvicorn on `localhost:4747`) that opens a browser UI. It runs entirely on the user's machine — provider keys never leave it. Deps are small (fastapi, uvicorn, httpx, openpyxl, python-docx, pypdf). No database server (SQLite file in `~/.poseidon`).
