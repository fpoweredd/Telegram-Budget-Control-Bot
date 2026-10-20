"""Composition root: builds every dependency and runs polling until stopped."""

from datetime import date, datetime

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeChat, BotCommandScopeDefault
from google import genai
from loguru import logger

from src.config import Settings
from src.db.database import Database
from src.db.migrations import migrate
from src.db.repositories import ReceiptRepository, SettingsRepository, TransactionRepository, UserRepository
from src.formatting import MessageFormatter
from src.handlers import build_router
from src.handlers.utils import OnceGuard
from src.middlewares import MembersOnlyMiddleware
from src.scheduler import build_scheduler
from src.services.budget_service import BudgetService
from src.services.notifier import Notifier
from src.services.receipt_parser import GeminiReceiptParser
from src.services.receipt_service import ReceiptService
from src.texts import Texts

__all__ = ["build_dispatcher", "run"]


async def _set_commands(bot: Bot, settings: Settings, texts: Texts) -> None:
    member_commands = [
        BotCommand(command="start", description=texts("command_start")),
        BotCommand(command="status", description=texts("command_status")),
        BotCommand(command="help", description=texts("command_help")),
    ]
    admin_commands = [
        *member_commands,
        BotCommand(command="date", description=texts("command_date")),
        BotCommand(command="restore", description=texts("command_restore")),
    ]
    await bot.set_my_commands(member_commands, scope=BotCommandScopeDefault())
    for admin_id in settings.admin_ids:
        try:
            await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=admin_id))
        except TelegramAPIError as e:  # the admin has not started the bot yet
            logger.warning("Could not set admin commands for {}: {}", admin_id, type(e).__name__)


def build_dispatcher(
    *,
    admin_ids: tuple[int, ...],
    member_ids: tuple[int, ...],
    budget: BudgetService,
    receipts: ReceiptService,
    notifier: Notifier,
    fmt: MessageFormatter,
) -> Dispatcher:
    """Dispatcher with routers, access control and the services handlers ask for by name."""
    dp = Dispatcher(
        storage=MemoryStorage(),
        budget=budget,
        receipts=receipts,
        notifier=notifier,
        fmt=fmt,
        entry_guard=OnceGuard(),
    )
    members_only = MembersOnlyMiddleware(member_ids)
    dp.message.outer_middleware(members_only)
    dp.callback_query.outer_middleware(members_only)
    dp.include_router(build_router(admin_ids))
    return dp


async def run(settings: Settings) -> None:
    def today() -> date:
        return datetime.now(settings.tz).date()

    texts = Texts.for_language(settings.language)
    fmt = MessageFormatter(texts, settings.currency)
    bot = Bot(
        token=settings.telegram_bot_token.get_secret_value(),
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )
    gemini = genai.Client(api_key=settings.google_api_key.get_secret_value())

    async with Database(settings.db_path) as db:
        await migrate(db, today(), settings.default_target_days)

        users = UserRepository(db)
        transactions = TransactionRepository(db)
        receipt_repo = ReceiptRepository(db)
        budget = BudgetService(
            db, users, transactions, receipt_repo, SettingsRepository(db), today, settings.default_target_days
        )
        parser = GeminiReceiptParser(gemini, settings.gemini_model, settings.gemini_timeout_seconds)
        receipts = ReceiptService(db, receipt_repo, transactions, users, parser, today)
        notifier = Notifier(bot, settings.member_ids)

        dp = build_dispatcher(
            admin_ids=settings.admin_ids,
            member_ids=settings.member_ids,
            budget=budget,
            receipts=receipts,
            notifier=notifier,
            fmt=fmt,
        )

        scheduler = build_scheduler(
            tz=settings.tz,
            report_time=settings.report_time,
            reminder_times=settings.reminder_times,
            reminder_recipients=settings.user_ids,
            budget=budget,
            notifier=notifier,
            fmt=fmt,
        )
        try:
            await _set_commands(bot, settings, texts)
            scheduler.start()
            logger.info(
                "Bot started: {} members, model {}, time zone {}",
                len(settings.member_ids),
                settings.gemini_model,
                settings.timezone,
            )
            await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
        finally:
            if scheduler.running:
                scheduler.shutdown(wait=False)
            await gemini.aio.aclose()
            await bot.session.close()
            logger.info("Bot stopped")
