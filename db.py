"""Supabase client for quest_clients table."""

from __future__ import annotations
from datetime import datetime, timezone
from supabase import create_client, Client
from config import SUPABASE_URL, SUPABASE_ANON_KEY

_client: Client | None = None


def client() -> Client:
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_ANON_KEY)
    return _client


def get_client_by_tg(telegram_id: int) -> dict | None:
    resp = client().table("quest_clients").select("*").eq("telegram_id", telegram_id).execute()
    return resp.data[0] if resp.data else None


def upsert_client(telegram_id: int, **fields) -> dict:
    existing = get_client_by_tg(telegram_id)
    if existing:
        client().table("quest_clients").update(fields).eq("telegram_id", telegram_id).execute()
        result = {**existing, **fields}
    else:
        row = client().table("quest_clients").insert({"telegram_id": telegram_id, **fields}).execute()
        result = row.data[0]
    if "survey_step" in fields:
        log_funnel_step(telegram_id, fields["survey_step"])
    return result


def mark_complete(telegram_id: int) -> None:
    client().table("quest_clients").update({
        "profile_complete": True,
        "survey_step": "done",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "next_reminder_at": None,
    }).eq("telegram_id", telegram_id).execute()
    log_funnel_step(telegram_id, "done")


def set_reminder(telegram_id: int, next_at: str, reminders_sent: int) -> None:
    client().table("quest_clients").update({
        "next_reminder_at": next_at,
        "reminders_sent": reminders_sent,
    }).eq("telegram_id", telegram_id).execute()


def get_pending_reminders(now_iso: str) -> list[dict]:
    resp = (client().table("quest_clients")
            .select("*")
            .eq("profile_complete", False)
            .lte("next_reminder_at", now_iso)
            .execute())
    return resp.data


def log_funnel_step(telegram_id: int, step: str) -> None:
    """Пишет в историю воронки: пользователь перешёл на шаг step."""
    client().table("quest_funnel_events").insert({
        "telegram_id": telegram_id,
        "step": step,
    }).execute()


def get_funnel_events(telegram_id: int) -> list[dict]:
    """История переходов одного пользователя по шагам (по порядку)."""
    resp = (client().table("quest_funnel_events")
            .select("step, created_at")
            .eq("telegram_id", telegram_id)
            .order("created_at")
            .execute())
    return resp.data
