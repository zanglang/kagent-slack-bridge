"""kagent Slack bridge.

Connects a Slack workspace to a kagent agent over the A2A JSON-RPC API, in
Socket Mode (no inbound HTTP / ingress needed).

  /kagent <question>        slash command, replies in a thread
  @kagent <question>        app mention in a channel, replies in-thread
  <follow-up in thread>     continues the same A2A conversation (contextId reuse)

Config (env):
  SLACK_BOT_TOKEN     xoxb-...   (required)
  SLACK_APP_TOKEN     xapp-...   (required, app-level token, connections:write)
  KAGENT_A2A_URL      base URL of the agent's A2A endpoint (required), e.g.
                      http://kagent-controller.kagent:8083/api/a2a/kagent/k8s-agent/
  KAGENT_TIMEOUT      per-request timeout seconds (default 600)
  KAGENT_CONTEXT_TTL  seconds to keep a Slack thread -> A2A contextId mapping
                      (default 86400)
  SLACK_COMMAND       slash command name to register (default "/kagent")
  LOG_LEVEL           default INFO
"""

from __future__ import annotations

import logging
import os
import time
import uuid

import httpx
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_bolt.async_app import AsyncApp

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("kagent-slack-bridge")

A2A_URL = os.environ["KAGENT_A2A_URL"].rstrip("/") + "/"
TIMEOUT = float(os.environ.get("KAGENT_TIMEOUT", "600"))
CONTEXT_TTL = float(os.environ.get("KAGENT_CONTEXT_TTL", "86400"))
SLASH_COMMAND = os.environ.get("SLACK_COMMAND", "/kagent")

app = AsyncApp(token=os.environ["SLACK_BOT_TOKEN"])

# slack thread_ts -> (a2a context_id, last_used_epoch). Single replica, so a
# plain dict is fine; context is lost on restart, which is acceptable here.
_contexts: dict[str, tuple[str, float]] = {}


def _get_context(thread_ts: str) -> str | None:
    entry = _contexts.get(thread_ts)
    if not entry:
        return None
    ctx, ts = entry
    if time.time() - ts > CONTEXT_TTL:
        _contexts.pop(thread_ts, None)
        return None
    return ctx


def _set_context(thread_ts: str, ctx: str) -> None:
    _contexts[thread_ts] = (ctx, time.time())
    if len(_contexts) > 5000:  # crude cap
        for k, _ in sorted(_contexts.items(), key=lambda kv: kv[1][1])[:1000]:
            _contexts.pop(k, None)


async def ask_kagent(text: str, thread_ts: str) -> str:
    """Send `text` to the kagent agent, return its reply text."""
    message: dict = {
        "role": "user",
        "messageId": str(uuid.uuid4()),
        "parts": [{"kind": "text", "text": text}],
    }
    ctx = _get_context(thread_ts)
    if ctx:
        message["contextId"] = ctx

    payload = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "message/send",
        "params": {"message": message},
    }

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        r = await client.post(A2A_URL, json=payload)
        r.raise_for_status()
        body = r.json()

    if "error" in body and body["error"]:
        err = body["error"]
        raise RuntimeError(f"A2A error {err.get('code')}: {err.get('message')}")

    result = body.get("result") or {}
    new_ctx = result.get("contextId")
    if new_ctx:
        _set_context(thread_ts, new_ctx)

    out = "".join(
        part.get("text", "")
        for artifact in result.get("artifacts", []) or []
        for part in artifact.get("parts", []) or []
    ).strip()

    state = (result.get("status") or {}).get("state")
    if not out:
        if state and state != "completed":
            return f"_(agent returned no text; task state: `{state}`)_"
        return "_(no response from the agent)_"
    return out


async def handle_question(text: str, channel: str, thread_ts: str, say, client) -> None:
    text = (text or "").strip()
    if not text:
        await say(channel=channel, thread_ts=thread_ts, text="Ask me something about the cluster.")
        return
    wait = dict(channel=channel, name="hourglass_flowing_sand", timestamp=thread_ts)
    try:
        await client.reactions_add(**wait)
    except Exception:  # not fatal (missing reactions:write, or already reacted)
        pass
    try:
        reply = await ask_kagent(text, thread_ts)
        await say(channel=channel, thread_ts=thread_ts, text=reply)
    except Exception as e:  # noqa: BLE001 — surface everything to the thread
        log.exception("kagent call failed")
        await say(
            channel=channel,
            thread_ts=thread_ts,
            text=f":warning: kagent call failed:\n```{e}```",
        )
    finally:
        try:
            await client.reactions_remove(**wait)
        except Exception:
            pass


@app.command(SLASH_COMMAND)
async def on_slash(ack, command, say, client):
    await ack()
    channel = command["channel_id"]
    # start a fresh thread rooted on an echo of the question
    posted = await client.chat_postMessage(
        channel=channel, text=f"*<@{command['user_id']}> asked kagent:* {command.get('text', '')}"
    )
    await handle_question(command.get("text", ""), channel, posted["ts"], say, client)


@app.event("app_mention")
async def on_mention(event, say, client):
    # strip the leading <@BOTID> mention
    text = event.get("text", "")
    if ">" in text:
        text = text.split(">", 1)[1]
    thread_ts = event.get("thread_ts") or event["ts"]
    await handle_question(text, event["channel"], thread_ts, say, client)


@app.event("message")
async def on_thread_followup(event, say, client):
    # only react to plain user messages inside a thread we're already tracking
    if event.get("bot_id") or event.get("subtype"):
        return
    thread_ts = event.get("thread_ts")
    if not thread_ts or thread_ts not in _contexts:
        return
    await handle_question(event.get("text", ""), event["channel"], thread_ts, say, client)


@app.error
async def on_error(error, body, logger):
    logger.exception(f"unhandled: {error}\n{body}")


async def main() -> None:
    log.info("kagent Slack bridge starting; agent=%s", A2A_URL)
    handler = AsyncSocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    await handler.start_async()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
