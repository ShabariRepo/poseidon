# Security posture

Poseidon is built local-first with layered guardrails — learn from the
OpenClaw era: an agent with shell access is a security product whether it
wants to be or not.

- **Network**: binds 127.0.0.1 by default; non-localhost Host headers are
  rejected (DNS-rebinding guard). Team mode (`--host 0.0.0.0`) requires a
  per-member token on every request; invalid tokens get 401. Put TLS in
  front (Caddy/Tailscale) for anything beyond a trusted LAN.
- **Actions**: writes, commands, spreadsheet edits, emails and Slack posts
  are approval-gated. "Always allow" rules are narrow by construction
  (directory, command word, recipient, channel). Autonomy presets widen
  file edits/commands only — outward sends always ask unless explicitly
  always-allowed.
- **Unattended runs** (schedules, background tasks) can only take gated
  actions covered by pre-existing always-allow rules.
- **Blast-radius limits**: file tools are jailed to the project folder;
  every change is versioned (restorable); auto-checkpoints snapshot
  conversation + touched files.
- **Prompt injection**: fetched web pages, emails, and file contents are
  framed as data, and the agent is instructed to refuse embedded
  directives and flag attempts. This mitigates, not eliminates — keep
  approval gates on for untrusted-content workflows.
- **Secrets**: provider keys and integration credentials live in
  `~/.poseidon/config.json` (chmod 600) and never leave your machine
  except to the providers you configured.

Report issues: open a GitHub issue with [security] in the title.
