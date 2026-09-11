# kagent-slack-bridge

A small Slack ↔ [kagent](https://kagent.dev) bridge. Runs in **Socket Mode**
(no inbound HTTP / ingress), forwards Slack messages to a kagent agent over the
A2A JSON-RPC API, and posts the reply back in a thread.

```
/kagent <question>     slash command — replies in a new thread
@kagent <question>     app mention — replies in-thread
<reply in that thread> continues the same A2A conversation (contextId reuse)
```

Per-thread conversation context is kept in memory (single replica), TTL
`KAGENT_CONTEXT_TTL` (default 24h); it resets on pod restart.

## Config (env)

| var | required | default | notes |
|---|---|---|---|
| `SLACK_BOT_TOKEN` | yes | | `xoxb-…` Bot User OAuth Token |
| `SLACK_APP_TOKEN` | yes | | `xapp-…` App-Level Token, scope `connections:write` |
| `KAGENT_A2A_URL` | yes | | agent A2A base URL, e.g. `http://kagent-controller.kagent:8083/api/a2a/kagent/k8s-agent/` |
| `KAGENT_TIMEOUT` | no | `600` | per-request seconds |
| `KAGENT_CONTEXT_TTL` | no | `86400` | thread→context mapping TTL seconds |
| `SLACK_COMMAND` | no | `/kagent` | slash command to register |
| `LOG_LEVEL` | no | `INFO` | |

## Slack app setup

1. api.slack.com → **Create New App → From a manifest**, paste
   [`slack-app-manifest.json`](slack-app-manifest.json).
2. **Install to Workspace** → copy the **Bot User OAuth Token** (`xoxb-…`).
3. **Basic Information → App-Level Tokens → Generate** with scope
   `connections:write` → copy the token (`xapp-…`).
4. Invite the bot to the channel(s): `/invite @kagent`.

## Deploy

Image is built by [`.github/workflows/release.yml`](.github/workflows/release.yml)
on a `v*.*.*` tag → `ghcr.io/zanglang/kagent-slack-bridge`.

The live Kubernetes manifests are in the `k8s-at-home` repo under
`kagent/manifests/` (ArgoCD-managed); [`k8s/`](k8s/) here is a reference copy.

## Local dev

```bash
cp .env.example .env   # fill in tokens + a port-forwarded KAGENT_A2A_URL
uv run bridge.py
```
