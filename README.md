# undo-send

**Undo Send for your Hermes agent.**

When Hermes is about to do something that leaves your machine and can't be
taken back (post to a team chat, call a webhook, write to a connected app,
`git push`), undo-send holds it for a short grace window. Cancel it in that
window and it never happens. Leave it, and it runs normally.

```
⏳ 14s  message to telegram: I'm quitting, goodbye everyone 👋   [Undo] [Send now]
```

## Why a plugin

Hermes' checkpoints and `/rollback` restore files, and file-level undo plugins
restore deleted files, but a message that has been sent or a ticket that has
been created can't be restored afterwards. undo-send handles the one moment
where an outward action is still fully reversible: before it runs.

It sits on Hermes' public `tool_execution` middleware, after Hermes' own
guardrails and approvals, so it adds a step without replacing anything. It
fails open: if undo-send itself errors, the tool call runs as it would have.

## What gets held

| Kind | Examples |
|---|---|
| Messages to people | `hermes send --to telegram "…"` (Telegram, Slack, Discord, Signal, SMS…), `imsg send`, email/message tools |
| App connector and MCP writes | `connectors__slack__post_message`, `connectors__gmail__send_email`, `mcp__linear__create_issue` |
| Publishing shell commands | `git push`, `gh pr create`, `npm publish`, `curl -X POST/PUT/PATCH/DELETE` |

Reads (`list_*`, `get_*`, `search_*`, `read_file`, `web_search`,
`hermes send --list`) are never held. Tune it with `always_hold` / `never_hold`.

The countdown shows a readable summary (`message to telegram: <text>`,
`slack: post message`, `POST to discord.com: <message>`),
never full URLs, so webhook tokens and credentials in URLs stay off screen.

## Ways to undo

- **Hermes Desktop:** while an action waits, a countdown chip appears in the
  status bar with **Undo** and **Send now**, plus a toast. An **Undo Send**
  dashboard page lists recent actions and how they ended.
- **Telegram, WhatsApp and other chats:** reply **undo** (or **unsend**) while
  it's waiting, and the newest action held **from that same chat** is cancelled,
  with a confirmation reply. Only the owners you list can do this, and it's **off
  until you set it up**:
  1. In the chat app, send `/undo-send whoami`. It replies with your ID, e.g.
     `telegram:123456789`.
  2. Allow it: `hermes config set plugins.entries.undo-send.settings.undo_senders "telegram:123456789"`
     (several: comma-separated), then `hermes gateway restart`.

  Anyone else's "undo" is passed to Hermes as a normal message, and an "undo" never
  touches actions held from another chat, Desktop or the CLI.

  *Note:* in Hermes builds before core PR
  [#151113](https://github.com/NousResearch/hermes-agent/pull/151113), an "undo"
  sent to the same chat whose turn is holding the action is queued as a busy-chat
  message and only arrives after the hold ends. Until that lands, use the Desktop
  chip, or reply from another chat app you've allowed.
- **Commands:** `/unsend` (or `/unsend <id>`, `/unsend all`), `/sendnow`, and
  `/undo-send` to list what's waiting and what happened. Hermes' own `/undo`
  still removes chat turns. Note that the CLI and chats queue slash commands
  while the agent is busy, so during a hold, use the Desktop chip or the chat
  reply.

When you undo, the agent is told the action never ran and not to retry it.

## Settings

Under `plugins.entries.undo-send.settings` in config, or Capabilities →
Plugins in Desktop:

| Key | Default | |
|---|---|---|
| `window_seconds` | 20 | Grace window. `0` turns holding off. |
| `hold_mcp_writes` | true | Hold connector write tools |
| `hold_terminal_publishes` | true | Hold publishing shell commands |
| `always_hold` / `never_hold` | [] | Per-tool overrides |
| `undo_senders` | [] | Who can reply "undo" in chat, as `platform:user_id`. Empty = chat undo off |

```
hermes config set plugins.entries.undo-send.settings.window_seconds 15
```

## Install

```
hermes plugins install undo-send --enable
```

If the status-bar chip doesn't appear in Desktop, check that **Undo Send** is
switched on under **Capabilities → Plugins**, then run *Reload desktop
plugins* from the command palette (Ctrl/⌘+K).

## Disclosure

- **No network calls, no telemetry, no credentials.** undo-send never reads
  `.env`, auth files or any secret.
- **Delays tool calls.** Matching outward actions wait up to `window_seconds`
  before running. This includes unattended runs (cron, gateway), where the
  action simply runs when the window ends; nothing waits indefinitely.
- **Local state only.** Pending and recent actions (tool name, a one-line
  summary with URLs reduced to their host, timestamps, outcome) are kept in a
  SQLite file at `HERMES_HOME/plugin-data/undo-send/pending.db`, so the agent,
  the gateway and Desktop all see and can cancel the same actions.
- **Reads incoming chat text** in the gateway only to recognise a bare "undo"
  from a sender listed in `undo_senders` (empty by default, so off); every other
  message passes through untouched. Held actions record the chat they came from
  (`platform:chat_id`) so an "undo" only cancels actions from its own chat.
- Runs no shell commands of its own and no background process.

## Development

```
cd tests && python -m pytest -q
hermes plugins validate . --install-deps
```

MIT licence.
