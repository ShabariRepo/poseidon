# 🔱 Poseidon

**An open-source agent harness that opens as a chat in your browser.**
Watch it work. Approve what matters. See what it costs.

Most agent harnesses live in a terminal. Poseidon doesn't. One command installs it,
one command opens a chat on `localhost` — with a live workspace pane showing every
file it touches, every command it runs, and a running meter of what it's spending.

```bash
pipx install poseidon-ai
poseidon ~/my-project
```

Your browser opens. You talk. It works — visibly.

## Why another harness?

Three things the others don't do:

1. **Watch it work.** Split-pane UI: chat on the left, live workspace on the right —
   activity stream, file browser, every tool call visible as it happens. No claims
   in prose you can't verify; you see the hands moving.
2. **The trust dial.** File writes and shell commands pause and ask, inline in chat,
   with a preview. Hit *Always allow* and Poseidon earns that permission permanently.
   Autonomy is granted, not assumed — and it accumulates.
3. **It knows what it costs.** A live cost meter — per session, per model, tokens
   in/out — built into the header. No more waking up to a burned API budget.

And it's properly agentic, not just a chat with tools:

- **Plans first** — multi-step work shows up as a live checklist in the workspace
- **Subagents** — big chunks get delegated to parallel subagents with their own context
- **Schedules** — "check this every morning" becomes a real scheduled run (approval-gated;
  unattended runs can only do what an *Always allow* rule already covers)

## Works with any model

Any OpenAI-compatible endpoint:

- **Ollama** — fully local, zero API key, free. Nous Hermes runs great.
- **OpenAI**, **Groq**, or any custom endpoint
- **[Bonito](https://getbonito.com)** — one key for every provider, with failover
  and team-level cost tracking

Keys are stored in `~/.poseidon/config.json` on your machine and sent nowhere else.

## Project instructions

Drop an `AGENTS.md` in your working directory and Poseidon reads it — same
convention as every other harness. No new file formats to learn.

## Status

Early. v0.2: the core loop (chat, file tools, shell with approvals, web fetch,
cost meter, activity stream) plus task planning, parallel subagents, and scheduled
runs. See [PLAN.md](PLAN.md) for the roadmap (streaming, MCP, model failover, memory).

## Development

```bash
git clone https://github.com/ShabariRepo/poseidon
cd poseidon
python3 -m venv .venv && .venv/bin/pip install -e .
.venv/bin/poseidon --no-browser
```

## License

MIT — made by [Bonito AI Labs](https://getbonito.com).
