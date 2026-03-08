# AGENTS.md

## Cursor Cloud specific instructions

### Project overview

QUEST is a Telegram bot for candidate screening (Russian-language). It uses **aiogram** (async Telegram framework) with **Supabase** (hosted PostgreSQL) as the data store.

### Source files

- `bot.py` — main bot entry point (`python bot.py`)
- `db.py` — Supabase client / data access layer
- `config.py` — loads env vars from `.env`
- `migrations/001_clients.sql` — DDL for the `quest_clients` table

### Required environment variables

Set via `.env` or injected as secrets:

| Variable | Purpose |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API token (from BotFather) |
| `SUPABASE_URL` | Supabase project REST URL |
| `SUPABASE_ANON_KEY` | Supabase anonymous/service key |

### Running the bot

```bash
source .venv/bin/activate
python bot.py
```

The bot connects to Telegram via long-polling. Without valid credentials it will exit immediately with `TokenValidationError`.

### Linting

No linter is configured in the repo. You can run `ruff check bot.py db.py config.py` (ruff is installed in the venv) for basic checks. There is one pre-existing unused-import warning (`Command` in `bot.py`).

### Testing

There are no automated tests in this project.

### Key caveats

- The bot has **no web UI or CLI**—the only interface is the Telegram chat. To test end-to-end you need a real Telegram bot token and a Supabase project with the `quest_clients` table created (see `migrations/001_clients.sql`).
- FSM state is in-memory (`MemoryStorage`), so state is lost on restart.
- The reminder loop runs via `asyncio.sleep(60)` inside the bot process; no external scheduler is required.
- `apscheduler` is listed in `requirements.txt` but is **not used** in the code.
