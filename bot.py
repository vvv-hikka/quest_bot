"""
QUEST Telegram Bot — клиентская анкета.

Запуск: python bot.py

Важно: для одного токена должен работать только один процесс бота (один polling).
Иначе Telegram возвращает Conflict. Перед стартом вызывается delete_webhook(drop_pending_updates=True).
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

from config import TELEGRAM_BOT_TOKEN, CHANNEL_USERNAME
import db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

router = Router()

# Семафор: ограничение одновременной обработки обновлений (очередь + предупреждение о нагрузке)
_handler_semaphore: asyncio.Semaphore | None = None


def _get_handler_semaphore() -> asyncio.Semaphore:
    global _handler_semaphore
    if _handler_semaphore is None:
        _handler_semaphore = asyncio.Semaphore(CONCURRENT_HANDLERS)
    return _handler_semaphore


async def _load_middleware(handler, event, data):
    """Ограничивает число одновременных обработчиков; при ожидании шлёт сообщение о нагрузке."""
    sem = _get_handler_semaphore()
    chat_id = (getattr(event, "chat", None) or getattr(getattr(event, "message", None), "chat", None))
    if chat_id:
        chat_id = chat_id.id
    bot = data.get("bot")
    try:
        await asyncio.wait_for(sem.acquire(), timeout=0.01)
    except asyncio.TimeoutError:
        if chat_id and bot:
            try:
                await bot.send_message(chat_id, LOAD_MSG, parse_mode="HTML")
            except Exception as e:
                log.debug("Load message not sent: %s", e)
        await sem.acquire()
    try:
        return await handler(event, data)
    finally:
        sem.release()


@router.message.outer_middleware()
async def load_middleware_msg(handler, event, data):
    return await _load_middleware(handler, event, data)


@router.callback_query.outer_middleware()
async def load_middleware_cb(handler, event, data):
    return await _load_middleware(handler, event, data)


# ── Тексты ──────────────────────────────────────────────────────

WELCOME = (
    "Привет!\n\n"
    "Мы — команда <b>QUEST</b> и наша миссия — сделать процесс отбора "
    "квалифицированных специалистов на работу более эффективным.\n\n"
    "Мы считаем, что текущий процесс найма не даёт достаточно прозрачности "
    "как соискателям, так и HR-специалистам и хотим это исправить.\n\n"
    "Для лучшей адаптации процессов найма к современной ситуации на рынке труда, "
    "QUEST имеет несколько отличий от большинства современных систем скрининга кандидатов. "
    "Вот некоторые из них:\n\n"
    "🔓 <b>Открытые алгоритмы скрининга кандидатов</b>\n\n"
    "📊 <b>Учёт разнообразных факторов при скрининге</b> — не только резюме, "
    "но и портфолио, GitHub, соревнования на LeetCode и Kaggle, "
    "соответствие ценностям компании\n\n"
    "✅ <b>Верификация опыта соискателей</b> их коллегами с прошлых мест работы "
    "и сокомандниками с некоммерческих проектов — для сокращения рисков подделки опыта\n\n"
    f"В нашем телеграм-канале {CHANNEL_USERNAME} ты можешь следить за обновлениями, "
    "а в комментариях канала мы отвечаем на ваши вопросы и предложения о сотрудничестве.\n\n"
    "🚀 <b>Запуск совсем скоро!</b>\n\n"
    "А сейчас заполни небольшую анкету, чтобы мы могли как можно скорее "
    "показать твоё резюме HR-ам. Если что, её можно будет изменить в любой момент."
)

Q_FULL_NAME = "📝 Введи своё <b>полное ФИО</b>:"
Q_PHONE = "📱 Введи свой <b>номер телефона</b>:"
Q_EMAIL = "📧 Введи свою <b>электронную почту</b>:"
Q_SPECIALTY = "💼 Введи свою <b>специальность</b> (в свободном формате):"
Q_RESUME = (
    "📄 Отправь своё <b>резюме</b> — PDF-файлом или ссылкой.\n\n"
    "Если хочешь пропустить — нажми кнопку ниже."
)
Q_PORTFOLIO = (
    "🎨 <b>Портфолио</b> — в свободном формате напиши о самых крутых своих проектах "
    "в области, в которой хочешь развиваться, и добавь ссылки, которые считаешь нужными.\n\n"
    "Если хочешь пропустить — нажми кнопку ниже."
)
Q_SOFT_SKILLS = (
    "🤝 Расскажи о своих <b>софт-скиллах</b>.\n\n"
    "Если хочешь пропустить — нажми кнопку ниже."
)
Q_WORK_VALUES = (
    "💡 Расскажи про свои <b>ценности в работе</b> — что для тебя важно "
    "в будущем месте работы?\n\n"
    "Если хочешь пропустить — нажми кнопку ниже."
)

COMPLETE_MSG = (
    "🎉 <b>Поздравляем с регистрацией!</b>\n\n"
    f"Чтобы не пропустить обновления, подпишись на наш телеграм-канал — {CHANNEL_USERNAME}.\n\n"
    "Спасибо за твой вклад в развитие адекватных HR-процессов!"
)

REMINDER_MSG = (
    "👋 Привет! Ты начал заполнять анкету в QUEST, но не завершил её.\n"
    "Заверши регистрацию, чтобы HR-специалисты могли увидеть твой профиль!"
)

# Расписание напоминаний: (часы, номер напоминания)
REMINDER_SCHEDULE = [
    (1, 1),       # через 1 час
    (24, 2),      # через 1 день
    (72, 3),      # через 3 дня
    (168, 4),     # через 1 неделю
]

# Обработка нагрузки: макс. одновременных обработчиков; при ожидании — сообщение пользователю
CONCURRENT_HANDLERS = 5
LOAD_MSG = (
    "⏳ Сейчас высокая нагрузка. Ваш запрос в очереди, ответим в течение 10–30 сек."
)


# ── Клавиатуры ──────────────────────────────────────────────────

def kb_start_survey() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Заполнить анкету", callback_data="survey:start")],
    ])

def kb_skip() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ Пропустить", callback_data="survey:skip")],
    ])

def kb_edit_profile() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Редактировать профиль", callback_data="profile:edit")],
    ])

def kb_continue_survey() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Продолжить заполнение", callback_data="survey:start")],
    ])


# ── FSM ─────────────────────────────────────────────────────────

class Survey(StatesGroup):
    full_name = State()
    phone = State()
    email = State()
    specialty = State()
    resume = State()
    portfolio = State()
    soft_skills = State()
    work_values = State()


# ── Форматирование профиля ──────────────────────────────────────

def format_profile(c: dict) -> str:
    lines = ["👤 <b>Твой профиль QUEST</b>\n"]
    if c.get("full_name"):
        lines.append(f"<b>ФИО:</b> {c['full_name']}")
    if c.get("phone"):
        lines.append(f"<b>Телефон:</b> {c['phone']}")
    if c.get("email"):
        lines.append(f"<b>Почта:</b> {c['email']}")
    if c.get("specialty"):
        lines.append(f"<b>Специальность:</b> {c['specialty']}")
    if c.get("resume_link"):
        lines.append(f"<b>Резюме:</b> {c['resume_link']}")
    elif c.get("resume_file_id"):
        lines.append("<b>Резюме:</b> 📎 файл загружен")
    if c.get("portfolio"):
        lines.append(f"<b>Портфолио:</b> {c['portfolio'][:200]}{'…' if len(c.get('portfolio','')) > 200 else ''}")
    if c.get("soft_skills"):
        lines.append(f"<b>Софт-скиллы:</b> {c['soft_skills'][:200]}{'…' if len(c.get('soft_skills','')) > 200 else ''}")
    if c.get("work_values"):
        lines.append(f"<b>Ценности:</b> {c['work_values'][:200]}{'…' if len(c.get('work_values','')) > 200 else ''}")
    return "\n".join(lines)


# ── Установка напоминания ───────────────────────────────────────

async def schedule_first_reminder(telegram_id: int) -> None:
    next_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    await db.set_reminder(telegram_id, next_at, 0)


# ── /start ──────────────────────────────────────────────────────

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    tg = message.from_user

    existing = await db.get_client_by_tg(tg.id)
    if existing and existing.get("profile_complete"):
        await message.answer(format_profile(existing), parse_mode="HTML",
                             reply_markup=kb_edit_profile())
        return

    if not existing:
        await db.upsert_client(tg.id, telegram_username=tg.username, survey_step="started")
        await schedule_first_reminder(tg.id)

    await message.answer(WELCOME, parse_mode="HTML", reply_markup=kb_start_survey())


# ── Начало анкеты ───────────────────────────────────────────────

# Восстановление шага анкеты из БД (survey_step -> state, вопрос, клавиатура)
RESUME_STEPS = {
    "phone": (Survey.phone, Q_PHONE, None),
    "email": (Survey.email, Q_EMAIL, None),
    "specialty": (Survey.specialty, Q_SPECIALTY, None),
    "resume": (Survey.resume, Q_RESUME, kb_skip()),
    "portfolio": (Survey.portfolio, Q_PORTFOLIO, kb_skip()),
    "soft_skills": (Survey.soft_skills, Q_SOFT_SKILLS, kb_skip()),
    "work_values": (Survey.work_values, Q_WORK_VALUES, kb_skip()),
}

@router.callback_query(F.data == "survey:start")
async def start_survey(callback: CallbackQuery, state: FSMContext) -> None:
    existing = await db.get_client_by_tg(callback.from_user.id)
    step = existing.get("survey_step") if existing else None
    if step and step in RESUME_STEPS:
        st, text, kb = RESUME_STEPS[step]
        await state.set_state(st)
        await callback.message.answer(text, parse_mode="HTML", reply_markup=kb)
    else:
        await state.set_state(Survey.full_name)
        await callback.message.answer(Q_FULL_NAME, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == "profile:edit")
async def edit_profile(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Survey.full_name)
    await callback.message.answer("Давай обновим профиль.\n\n" + Q_FULL_NAME, parse_mode="HTML")
    await callback.answer()


# ── ФИО ─────────────────────────────────────────────────────────

@router.message(Survey.full_name)
async def on_full_name(message: Message, state: FSMContext) -> None:
    if not message.text or not message.text.strip():
        await message.answer("Пожалуйста, введи ФИО текстом.")
        return
    await db.upsert_client(message.from_user.id, full_name=message.text.strip(), survey_step="phone")
    await state.set_state(Survey.phone)
    await message.answer(Q_PHONE, parse_mode="HTML")


# ── Телефон ─────────────────────────────────────────────────────

@router.message(Survey.phone)
async def on_phone(message: Message, state: FSMContext) -> None:
    text = message.text.strip() if message.text else ""
    if message.contact:
        text = message.contact.phone_number
    await db.upsert_client(message.from_user.id, phone=text, survey_step="email")
    await state.set_state(Survey.email)
    await message.answer(Q_EMAIL, parse_mode="HTML")


# ── Почта ───────────────────────────────────────────────────────

@router.message(Survey.email)
async def on_email(message: Message, state: FSMContext) -> None:
    if not message.text or not message.text.strip():
        await message.answer("Пожалуйста, введи почту текстом.")
        return
    await db.upsert_client(message.from_user.id, email=message.text.strip(), survey_step="specialty")
    await state.set_state(Survey.specialty)
    await message.answer(Q_SPECIALTY, parse_mode="HTML")


# ── Специальность ───────────────────────────────────────────────

@router.message(Survey.specialty)
async def on_specialty(message: Message, state: FSMContext) -> None:
    if not message.text or not message.text.strip():
        await message.answer("Пожалуйста, введи специальность текстом.")
        return
    await db.upsert_client(message.from_user.id, specialty=message.text.strip(), survey_step="resume")
    await state.set_state(Survey.resume)
    await message.answer(Q_RESUME, parse_mode="HTML", reply_markup=kb_skip())


# ── Резюме (можно пропустить) ───────────────────────────────────

@router.callback_query(Survey.resume, F.data == "survey:skip")
async def skip_resume(callback: CallbackQuery, state: FSMContext) -> None:
    await db.upsert_client(callback.from_user.id, survey_step="portfolio")
    await state.set_state(Survey.portfolio)
    await callback.message.answer(Q_PORTFOLIO, parse_mode="HTML", reply_markup=kb_skip())
    await callback.answer()


@router.message(Survey.resume, F.document)
async def on_resume_file(message: Message, state: FSMContext) -> None:
    await db.upsert_client(message.from_user.id,
                          resume_file_id=message.document.file_id,
                          resume_link=None,
                          survey_step="portfolio")
    await state.set_state(Survey.portfolio)
    await message.answer("📎 Файл получен!\n\n" + Q_PORTFOLIO, parse_mode="HTML", reply_markup=kb_skip())


@router.message(Survey.resume, F.text)
async def on_resume_link(message: Message, state: FSMContext) -> None:
    await db.upsert_client(message.from_user.id,
                          resume_link=message.text.strip(),
                          resume_file_id=None,
                          survey_step="portfolio")
    await state.set_state(Survey.portfolio)
    await message.answer("🔗 Ссылка сохранена!\n\n" + Q_PORTFOLIO, parse_mode="HTML", reply_markup=kb_skip())


@router.message(Survey.resume)
async def on_resume_other(message: Message, state: FSMContext) -> None:
    """Резюме: прислали не документ и не текст (фото, голос и т.д.)."""
    await message.answer(
        "Отправь резюме PDF-файлом или ссылкой. Либо нажми «Пропустить».",
        parse_mode="HTML",
        reply_markup=kb_skip(),
    )


# ── Портфолио (можно пропустить) ────────────────────────────────

@router.callback_query(Survey.portfolio, F.data == "survey:skip")
async def skip_portfolio(callback: CallbackQuery, state: FSMContext) -> None:
    await db.upsert_client(callback.from_user.id, survey_step="soft_skills")
    await state.set_state(Survey.soft_skills)
    await callback.message.answer(Q_SOFT_SKILLS, parse_mode="HTML", reply_markup=kb_skip())
    await callback.answer()


@router.message(Survey.portfolio)
async def on_portfolio(message: Message, state: FSMContext) -> None:
    if not message.text or not message.text.strip():
        await message.answer("Пожалуйста, отправь описание портфолио текстом или нажми «Пропустить».")
        return
    await db.upsert_client(message.from_user.id, portfolio=message.text.strip(), survey_step="soft_skills")
    await state.set_state(Survey.soft_skills)
    await message.answer(Q_SOFT_SKILLS, parse_mode="HTML", reply_markup=kb_skip())


# ── Софт-скиллы (можно пропустить) ──────────────────────────────

@router.callback_query(Survey.soft_skills, F.data == "survey:skip")
async def skip_soft_skills(callback: CallbackQuery, state: FSMContext) -> None:
    await db.upsert_client(callback.from_user.id, survey_step="work_values")
    await state.set_state(Survey.work_values)
    await callback.message.answer(Q_WORK_VALUES, parse_mode="HTML", reply_markup=kb_skip())
    await callback.answer()


@router.message(Survey.soft_skills)
async def on_soft_skills(message: Message, state: FSMContext) -> None:
    if not message.text or not message.text.strip():
        await message.answer("Пожалуйста, отправь текст о софт-скиллах или нажми «Пропустить».")
        return
    await db.upsert_client(message.from_user.id, soft_skills=message.text.strip(), survey_step="work_values")
    await state.set_state(Survey.work_values)
    await message.answer(Q_WORK_VALUES, parse_mode="HTML", reply_markup=kb_skip())


# ── Ценности (можно пропустить) ─────────────────────────────────

@router.callback_query(Survey.work_values, F.data == "survey:skip")
async def skip_work_values(callback: CallbackQuery, state: FSMContext) -> None:
    await _finish(callback.from_user.id, callback.message, state)
    await callback.answer()


@router.message(Survey.work_values)
async def on_work_values(message: Message, state: FSMContext) -> None:
    if not message.text or not message.text.strip():
        await message.answer("Пожалуйста, отправь текст о ценностях в работе или нажми «Пропустить».")
        return
    await db.upsert_client(message.from_user.id, work_values=message.text.strip(), survey_step="work_values")
    await _finish(message.from_user.id, message, state)


# ── Завершение ──────────────────────────────────────────────────

async def _finish(telegram_id: int, message: Message, state: FSMContext) -> None:
    await db.mark_complete(telegram_id)
    await state.clear()

    await message.answer(COMPLETE_MSG, parse_mode="HTML")

    c = await db.get_client_by_tg(telegram_id)
    if c:
        await message.answer(format_profile(c), parse_mode="HTML", reply_markup=kb_edit_profile())


# ── Напоминания ─────────────────────────────────────────────────

async def check_reminders(bot: Bot) -> None:
    now = datetime.now(timezone.utc)
    pending = await db.get_pending_reminders(now.isoformat())

    for c in pending:
        tg_id = c["telegram_id"]
        sent = c.get("reminders_sent", 0)

        try:
            await bot.send_message(
                tg_id, REMINDER_MSG, parse_mode="HTML",
                reply_markup=kb_continue_survey(),
            )
            log.info("Sent reminder #%d to %d", sent + 1, tg_id)
        except Exception as e:
            log.warning("Failed to send reminder to %d: %s", tg_id, e)

        next_reminder = None
        for hours, num in REMINDER_SCHEDULE:
            if num > sent + 1:
                next_reminder = (now + timedelta(hours=hours)).isoformat()
                break

        await db.set_reminder(tg_id, next_reminder, sent + 1)


async def reminder_loop(bot: Bot) -> None:
    while True:
        try:
            await check_reminders(bot)
        except Exception as e:
            log.error("Reminder check error: %s", e)
        await asyncio.sleep(60)


# ── Точка входа ─────────────────────────────────────────────────

async def main() -> None:
    bot = Bot(token=TELEGRAM_BOT_TOKEN,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    # Снять webhook (если был) и отменить старые обновления — иначе возможен
    # Conflict от другого процесса или предыдущего запуска.
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        log.info("Webhook removed, pending updates dropped.")
    except Exception as e:
        log.warning("delete_webhook: %s", e)

    # Пауза перед polling: даём предыдущему процессу (старый контейнер/реплика) время
    # завершить getUpdates и освободить токен. Иначе возможен Conflict при перезапуске.
    POLLING_START_DELAY = 5
    if POLLING_START_DELAY > 0:
        log.info("Waiting %s s before polling (avoid Conflict on restart)...", POLLING_START_DELAY)
        await asyncio.sleep(POLLING_START_DELAY)

    asyncio.create_task(reminder_loop(bot))

    log.info("Starting QUEST bot (only one instance must run per token)...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
