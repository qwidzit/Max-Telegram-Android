# Max → Telegram Bridge

A Python bot that runs permanently on an Android phone (via Termux), listens to
incoming messages in the **Max** messenger app, analyses them with Claude AI,
and forwards important messages or summaries to your second phone via a
**Telegram bot**. You control everything from your iPhone by sending commands
to the Telegram bot.

## How it works

- **autoresend** chats: every message is forwarded to your Telegram instantly.
- **summarise** chats: messages are buffered and Claude produces a summary
  when either the message count threshold is hit (`discussion ongoing`) or the
  chat goes silent for the timeout period (`conversation ended`).
- Chats that are not configured are silently ignored.

## Setup on the Max phone (Termux)

1. Install **Termux** (from F-Droid — the Play Store build is outdated).
2. In Termux:
   ```sh
   pkg update && pkg install python git tmux
   git clone <this-repo-url>
   cd Max-Telegram-Android
   pip install -r requirements.txt
   ```
3. Create your config files:
   ```sh
   cp .env.example .env
   cp config.json.example config.json   # optional starting point
   ```
4. Edit `.env` and fill in **all** values:
   - `MAX_PHONE` — the Max account's phone number (this phone's owner)
   - `MAX_PASSWORD` — Max password if the library requires it
   - `MAX_SESSION_FILE` — path to persist the session token
   - `ANTHROPIC_API_KEY` — from the Anthropic console
   - `TELEGRAM_BOT_TOKEN` — from @BotFather
   - `TELEGRAM_OWNER_CHAT_ID` — your personal Telegram chat ID (an integer;
     get it by messaging your bot and checking
     `https://api.telegram.org/bot<TOKEN>/getUpdates`)
5. Run inside tmux so it survives Termux closing:
   ```sh
   tmux new -s maxbot
   python main.py
   ```
6. Detach tmux with `Ctrl+B` then `D`. Reattach later with `tmux attach -t maxbot`.
7. In Android **Settings → Battery**, disable battery optimisation for Termux
   so Android does not kill the process.

## Telegram commands

Send these to your bot from your iPhone:

| Command | Effect |
|---|---|
| `/autoresend <chat name>` | Forward every message from this chat instantly |
| `/summarise <chat name>` | Summarise mode with default thresholds |
| `/summarise <chat name> <mins> <count>` | Summarise with custom timeout and count |
| `/timeout <chat name> <mins>` | Update timeout only (existing summarise chat) |
| `/count <chat name> <n>` | Update message count threshold only |
| `/remove <chat name>` | Stop monitoring this chat |
| `/list` | Show all monitored chats and settings |
| `/status` | Confirm the bot is alive |

Chat names may contain spaces. For `/summarise`, `/timeout`, `/count`, trailing
numbers are parsed as the numeric arguments and everything before them is the
chat name.

## Defaults

| Setting | Default |
|---|---|
| `timeout_minutes` | 10 |
| `message_count` | 20 |

## Notes

- Everything runs in a single asyncio event loop.
- Buffers are in-memory only; a restart clears them (acceptable). `config.json`
  is the persistent source of truth and survives restarts.
- The Max integration uses an unofficial library. Max's API is unofficial and
  changes; if message events stop arriving after a library update, the only
  place to adjust is `MaxListener._connect_and_listen` in
  `max_listener/client.py`.
- Telegram commands are only accepted from `TELEGRAM_OWNER_CHAT_ID`; all other
  senders are ignored.
