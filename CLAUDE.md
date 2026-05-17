# Max → Telegram Bridge — Project Brief for Claude Code

## What This Project Does

A Python bot running permanently on an Android phone (Redmi) via Termux.
It listens to incoming messages in the Max messenger app (logged in as the phone's owner),
analyses them with Claude AI, and forwards important messages or summaries to the owner's
second phone via a Telegram bot.

The owner controls everything (which chats to monitor, which mode) by sending commands
to the Telegram bot from their iPhone — no developer intervention needed after setup.

---

## Target Runtime Environment

- **Device:** Redmi Android phone (the Max phone)
- **Runtime:** Termux (Linux on Android, no root required)
- **Language:** Python 3 (asyncio-based, everything in one event loop)
- **Process manager:** tmux session inside Termux (keeps script alive)
- **External APIs called over internet:**
  - Max messenger (unofficial WebSocket API)
  - Anthropic Claude API (summarisation)
  - Telegram Bot API (outbound messages + inbound commands)

---

## Repository Structure

```
max-to-telegram/
│
├── main.py                      # Entry point — starts all async tasks
│
├── .env                         # API keys — gitignored, never commit
├── .env.example                 # Template showing required keys
├── config.json                  # Friend's chat settings — gitignored
├── requirements.txt
├── README.md                    # Termux setup instructions
├── .gitignore                   # Must exclude .env and config.json
│
├── max_listener/
│   └── client.py                # Max WebSocket userbot
│
├── router/
│   └── router.py                # Routes each message to correct handler
│
├── buffer/
│   └── message_buffer.py        # Collects messages, manages both summary triggers
│
├── summariser/
│   └── claude_client.py         # Calls Claude API, returns summary string
│
├── telegram/
│   ├── sender.py                # Sends messages/summaries to owner's Telegram
│   └── command_handler.py       # Polls for /commands, writes to config
│
└── config/
    └── config_manager.py        # Reads/writes config.json
```

---

## Component Responsibilities

### `main.py`
- Initialises all components
- Starts three concurrent asyncio tasks:
  1. Max listener (incoming message events)
  2. Telegram command listener (incoming /commands from owner)
  3. Buffer timeout checker (background loop, runs every 60 seconds)
- Handles graceful shutdown

### `max_listener/client.py`
- Connects to Max via WebSocket using an unofficial Python library
- Authenticates as the phone owner's Max account
- Emits a clean, normalised event per incoming message:
  `{ chat_name, sender_name, text, timestamp }`
- No routing logic — just event emission
- Recommended library: search PyPI/GitHub for `maxapi` or `max-botapi-python`
  (VK's Max messenger has an official bot API and unofficial user-level libraries)

### `router/router.py`
- Receives each normalised message event from the Max listener
- Looks up `chat_name` in config via `config_manager`
- Routes to one of three outcomes:
  - `autoresend` → pass directly to `telegram/sender.py`
  - `summarise` → pass to `buffer/message_buffer.py`
  - not configured → silently ignore

### `buffer/message_buffer.py`
- Maintains a dict: `{ chat_name: { messages: [], timer: asyncio.Task } }`
- On each new message appended to a chat buffer:
  1. **Count trigger:** if `len(messages) >= count_threshold` → call summariser,
     send summary with tag `"discussion ongoing"`, then clear the buffer
     (but keep the timeout timer running)
  2. **Timeout trigger:** reset the silence timer for this chat
- Background loop checks every 60s for chats whose silence timer has expired →
  call summariser, send summary with tag `"conversation ended"`, clear buffer
- Both thresholds are per-chat, read from config

### `summariser/claude_client.py`
- Accepts: list of message dicts + status string (`"discussion ongoing"` or `"conversation ended"`)
- Calls Claude API (`claude-sonnet-4-20250514`, max_tokens=500)
- System prompt instructs Claude to:
  - Summarise the conversation concisely
  - Identify any action items or urgent points
  - End the summary with the provided status string on its own line
- Returns the summary as a plain string

### `telegram/sender.py`
- Sends messages to the owner's Telegram using their chat ID (from `.env`)
- Two send modes:
  - **Forward:** sends original message with prefix `[Max – {chat_name}] {sender}: {text}`
  - **Summary:** sends summary with header `📋 Summary – {chat_name}`

### `telegram/command_handler.py`
- Polls Telegram Bot API for new messages (long polling)
- Only processes messages from the owner's Telegram chat ID (security: ignore all others)
- Parses commands and calls `config_manager` accordingly
- Sends confirmation reply after each command
- Ignores unrecognised input silently

### `config/config_manager.py`
- Reads and writes `config.json`
- Thread-safe (use asyncio lock)
- Schema:

```json
{
  "chats": {
    "Work Group": {
      "mode": "summarise",
      "timeout_minutes": 10,
      "message_count": 20
    },
    "Family Chat": {
      "mode": "autoresend"
    }
  }
}
```

- Exposes: `get_chat_config(chat_name)`, `set_chat_config(chat_name, config)`,
  `remove_chat(chat_name)`, `list_chats()`

---

## Config Defaults

| Setting | Default |
|---|---|
| `timeout_minutes` | 10 |
| `message_count` | 20 |

---

## Telegram Commands (owner sends these to the bot)

| Command | Effect |
|---|---|
| `/autoresend <chat name>` | Forward every message from this chat instantly |
| `/summarise <chat name>` | Summarise mode with default thresholds |
| `/summarise <chat name> <mins> <count>` | Summarise with custom timeout and count |
| `/timeout <chat name> <mins>` | Update timeout only for an existing chat |
| `/count <chat name> <n>` | Update message count threshold only |
| `/remove <chat name>` | Stop monitoring this chat |
| `/list` | Show all monitored chats with their current settings |
| `/status` | Confirm bot is alive and running |

Chat names may contain spaces — everything after the command keyword (and optional
numeric args at the end) is treated as the chat name.

---

## Environment Variables (`.env`)

```
MAX_PHONE=+7XXXXXXXXXX          # Owner's phone number for Max login
MAX_PASSWORD=                   # Max account password (if required by library)
MAX_SESSION_FILE=max_session    # Path to persist session token

ANTHROPIC_API_KEY=sk-ant-...

TELEGRAM_BOT_TOKEN=             # From BotFather
TELEGRAM_OWNER_CHAT_ID=         # Owner's personal Telegram chat ID (integer)
```

---

## `.gitignore` (must include at minimum)

```
.env
config.json
max_session*
__pycache__/
*.pyc
```

---

## `requirements.txt` (approximate — adjust to actual library names)

```
anthropic
python-telegram-bot
aiohttp
aiofiles
python-dotenv
# + whichever Max unofficial library is used
```

---

## Build Order (recommended)

Build and test each component independently before wiring together:

1. **`config/config_manager.py`** — pure data layer, no dependencies, test first
2. **`telegram/command_handler.py` + `telegram/sender.py`** — test the control
   interface end-to-end with the owner's phone before any Max code exists
3. **`summariser/claude_client.py`** — test with hardcoded dummy messages
4. **`buffer/message_buffer.py`** — test both triggers with a mock message injector
5. **`max_listener/client.py`** — connect to Max, verify events are emitted correctly
6. **`router/router.py`** — wire listener → router → buffer/sender
7. **`main.py`** — combine all tasks, test full end-to-end flow

---

## Key Implementation Notes

- **Everything is async** — use `asyncio` throughout; no blocking calls on the main loop
- **Max chat name matching** — Max may return chat IDs internally; build a mapping from
  display name → ID at startup and refresh periodically
- **Security** — Telegram command handler must reject commands from any chat ID that is
  not `TELEGRAM_OWNER_CHAT_ID`
- **Error handling** — Max WebSocket disconnects should trigger automatic reconnection
  with exponential backoff; Claude API errors should send a Telegram alert to the owner
- **Buffer persistence** — buffers are in-memory only; a restart clears them (acceptable)
- **Config persistence** — `config.json` survives restarts; this is the source of truth

---

## README.md Should Cover

1. Prerequisites: Termux installed, Python 3, tmux
2. `pkg install python git tmux` in Termux
3. `git clone <repo>`, `cd max-to-telegram`
4. `pip install -r requirements.txt`
5. Copy `.env.example` → `.env` and fill in all values
6. `tmux new -s maxbot`
7. `python main.py`
8. Detach tmux: `Ctrl+B then D`
9. Android: disable battery optimisation for Termux in Settings
10. List of all bot commands for the owner
