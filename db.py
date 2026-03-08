"""Supabase client for quest_clients table.

Публичный API — async-функции (get_client_by_tg, upsert_client, ...), чтобы не блокировать
event loop при медленных запросах. Внутри вызовы выполняются в потоке (executor) с семафором.
"""

from __future__ import annotations
import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_ANON_KEY

log = logging.getLogger(__name__)
_client: Client | None = None
_executor: ThreadPoolExecutor | None = None
_db_semaphore: asyncio.Semaphore | None = None

# Макс. одновременных обращений к БД (остальные ждут в очереди)
MAX_CONCURRENT_DB = 10


def _get_executor() -> ThreadPoolExecutor:
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_DB, thread_name_prefix="db")
    return _executor


def _get_db_semaphore() -> asyncio.Semaphore:
    global _db_semaphore
    if _db_semaphore is None:
        _db_semaphore = asyncio.Semaphore(MAX_CONCURRENT_DB)
    return _db_semaphore


async def _run_sync(sync_fn, *args, **kwargs):
    """Выполняет синхронную функцию в потоке, не блокируя event loop."""
    loop = asyncio.get_event_loop()
    sem = _get_db_semaphore()
    async with sem:
        return await loop.run_in_executor(
            _get_executor(),
            lambda: sync_fn(*args, **kwargs),
        )


def client() -> Client:
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    return _client


def _get_client_by_tg_sync(telegram_id: int) -> dict | None:
    resp = client().table("quest_clients").select("*").eq("telegram_id", telegram_id).execute()
    return resp.data[0] if resp.data else None


def _upsert_client_sync(telegram_id: int, **fields) -> dict:
    existing = _get_client_by_tg_sync(telegram_id)
    if existing:
        client().table("quest_clients").update(fields).eq("telegram_id", telegram_id).execute()
        result = {**existing, **fields}
    else:
        row = client().table("quest_clients").insert({"telegram_id": telegram_id, **fields}).execute()
        result = row.data[0]
    if "survey_step" in fields:
        log_funnel_step(telegram_id, fields["survey_step"])
    return result


def _mark_complete_sync(telegram_id: int) -> None:
    client().table("quest_clients").update({
        "profile_complete": True,
        "survey_step": "done",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "next_reminder_at": None,
    }).eq("telegram_id", telegram_id).execute()
    log_funnel_step(telegram_id, "done")


def _set_reminder_sync(telegram_id: int, next_at: str, reminders_sent: int) -> None:
    client().table("quest_clients").update({
        "next_reminder_at": next_at,
        "reminders_sent": reminders_sent,
    }).eq("telegram_id", telegram_id).execute()


def _get_pending_reminders_sync(now_iso: str) -> list[dict]:
    resp = (client().table("quest_clients")
            .select("*")
            .eq("profile_complete", False)
            .lte("next_reminder_at", now_iso)
            .execute())
    return resp.data


# ─── Публичный async API (использовать в боте) ────────────────────

async def get_client_by_tg(telegram_id: int) -> dict | None:
    return await _run_sync(_get_client_by_tg_sync, telegram_id)


async def upsert_client(telegram_id: int, **fields) -> dict:
    return await _run_sync(_upsert_client_sync, telegram_id, **fields)


async def mark_complete(telegram_id: int) -> None:
    await _run_sync(_mark_complete_sync, telegram_id)


async def set_reminder(telegram_id: int, next_at: str, reminders_sent: int) -> None:
    await _run_sync(_set_reminder_sync, telegram_id, next_at, reminders_sent)


async def get_pending_reminders(now_iso: str) -> list[dict]:
    return await _run_sync(_get_pending_reminders_sync, now_iso)


def log_funnel_step(telegram_id: int, step: str) -> None:
    """Пишет в историю воронки: пользователь перешёл на шаг step. При ошибке (нет таблицы и т.д.) не падаем."""
    try:
        client().table("quest_funnel_events").insert({
            "telegram_id": telegram_id,
            "step": step,
        }).execute()
    except Exception as e:
        log.warning("Funnel log failed (table quest_funnel_events may be missing): %s", e)


def get_funnel_events(telegram_id: int) -> list[dict]:
    """История переходов одного пользователя по шагам (по порядку). При отсутствии таблицы возвращает []."""
    try:
        resp = (client().table("quest_funnel_events")
                .select("step, created_at")
                .eq("telegram_id", telegram_id)
                .order("created_at")
                .execute())
        return resp.data
    except Exception as e:
        log.warning("get_funnel_events failed: %s", e)
        return []
