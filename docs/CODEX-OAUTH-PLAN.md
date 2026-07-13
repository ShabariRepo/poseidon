# Codex OAuth (ChatGPT-subscription login) for Poseidon

*Reverse-engineered from a working Hermes install (`~/.hermes/hermes-agent`,
`hermes_cli/auth.py` + `agent/codex_responses_adapter.py`) on 2026-07-13.*

## Why this is a whole subsystem, not a preset

The ChatGPT-subscription token does NOT work against `api.openai.com/v1/chat/completions`
(Poseidon's normal bearer-key path). It only works against
`https://chatgpt.com/backend-api/codex` using OpenAI's **Responses API** shape,
with special headers. So Codex support = OAuth flow + token store/refresh + a
**second request pipeline** (chat-completions ⇄ Responses translation + SSE parse).

## 1) OAuth device-code login (OpenAI's own flow — NOT RFC 8628)

Constants (public Codex CLI client):
- `CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"`
- `ISSUER   = "https://auth.openai.com"`
- `TOKEN_URL = "https://auth.openai.com/oauth/token"` (used for refresh)

Flow (`_codex_device_code_login` in Hermes auth.py ~L6910):
1. **Request user code:** `POST {ISSUER}/api/accounts/deviceauth/usercode`
   → `{ user_code, device_auth_id, interval }`
2. **Show user:** visit `{ISSUER}/codex/device`, enter `user_code`.
3. **Poll:** every `interval` s (min 3),
   `POST {ISSUER}/api/accounts/deviceauth/token`
   body `{ device_auth_id, user_code }`
   → pending until authorized, then `{ access_token, refresh_token, id_token }`.
4. **account_id:** decode the `id_token` JWT (base64url payload, no verify needed)
   → claim carrying the ChatGPT account id (seen as a UUID in
   `~/.hermes/auth.json` → `providers.openai-codex.tokens.account_id`;
   Hermes `_decode_jwt_claims` ~L1681, look under `https://api.openai.com/auth`
   → `chatgpt_account_id`).

**Refresh:** `POST {TOKEN_URL}` form/json
`{ grant_type: "refresh_token", refresh_token, client_id: CLIENT_ID }`
→ new `{ access_token, refresh_token?, id_token? }`. Refresh when access_token
is within skew of expiry (`_codex_access_token_is_expiring`) — decode the JWT
`exp`. Tokens DO expire and can hit `relogin_required` (seen in the wild).

**Bonus — import existing Codex CLI login:** if `~/.codex/auth.json` exists,
read its tokens (`_import_codex_cli_tokens` ~L3479) so a user who already ran
`codex login` skips the device flow.

## 2) The Codex Responses request pipeline

- **Endpoint:** `POST https://chatgpt.com/backend-api/codex/responses`
- **Headers:**
  - `Authorization: Bearer <access_token>`
  - `chatgpt-account-id: <account_id>`
  - `OpenAI-Beta: responses=experimental` (verify exact value against adapter)
  - `originator: codex_cli_rs` (verify), `session_id: <uuid>`, `Content-Type: application/json`
- **Body (Responses API, not chat/completions):**
  - `model` (e.g. `gpt-5.5`, `gpt-5.1-codex`)
  - `instructions` (system prompt, hoisted out of messages)
  - `input`: array of Responses items — see `_chat_messages_to_responses_input`
    (adapter L279). Mapping:
    - user text → `{type:"message", role:"user", content:[{type:"input_text", text}]}`
    - assistant text → `{... role:"assistant", content:[{type:"output_text", text}]}`
    - image → `{type:"input_image", image_url}`
    - tool call → `{type:"function_call", call_id, name, arguments}`
    - tool result → `{type:"function_call_output", call_id, output}`
  - `tools`: Responses tool shape (`_responses_tools` L237) — `{type:"function", name, description, parameters}` (flattened, not nested under `function`)
  - `stream: true`
- **Response SSE (Responses event stream):** events like
  `response.output_text.delta` (content), `response.function_call_arguments.delta`
  /`.done` (tool calls), `response.completed` (final + usage). Parse these →
  Poseidon's `{content, tool_calls, usage}` shape. (Hermes adapter handles far
  more: reasoning-item replay, encrypted content, xAI issuer quirks — Poseidon
  can SKIP those for a v1.)

## 3) Poseidon wiring

- **config.py:** new provider preset `codex` with `type: "codex"` (no api_key;
  auth via stored tokens). Store tokens in `~/.poseidon/codex_auth.json`.
- **poseidon/codex.py:** `device_login()` (start + poll), `load_tokens()`,
  `refresh_if_needed()`, `import_codex_cli()`, `responses_request()` +
  `_to_responses_input()` + `_parse_responses_sse()`.
- **orchestrator.py:** in `_chat_completion` / `_chat_completion_stream`, if
  `provider["type"] == "codex"`, route to `codex.responses_request(...)` instead
  of the bearer/chat-completions path. Return the same
  `{choices:[{message}], usage}` shape so the loop is unchanged.
- **server.py:** `POST /api/codex/login/start` → returns `{user_code, verify_url}`;
  `GET /api/codex/login/poll` → `{status}`; `POST /api/codex/login/import` (CLI).
- **UI:** in Settings, a "Sign in with ChatGPT" button → shows the code + URL,
  polls, flips provider to codex on success.

## Status / risks
- v1 = text + tool calls (skip images/reasoning-replay). Enough to prove
  ChatGPT-sub login works end-to-end.
- **Needs a LIVE device login to test** — cannot be validated offline.
- ToS gray area + fragile (OpenAI can change the flow; Hermes token already saw
  `relogin_required`). Ship as opt-in, documented.
- Hermes reference (this machine): `~/.hermes/hermes-agent/hermes_cli/auth.py`
  (device flow L6910, refresh L3330, import L3479, jwt L1681),
  `agent/codex_responses_adapter.py` (translation, 1221 lines).
