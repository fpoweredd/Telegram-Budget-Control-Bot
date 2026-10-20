"""Nightly report and reminders, fired by APScheduler cron triggers in the bot's time zone."""

from collections.abc import Sequence
from datetime import time
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

from src.formatting import MessageFormatter
from src.services.budget_service import BudgetService
from src.services.notifier import Notifier

__all__ = ["build_scheduler", "send_reminder", "send_weekly_report"]

# A job that could not run on time (e.g. the process was busy or restarting) still runs
# if it is less than this late; several missed runs are merged into one.
MISFIRE_GRACE_SECONDS = 15 * 60


async def send_weekly_report(budget: BudgetService, notifier: Notifier, fmt: MessageFormatter) -> None:
    try:
        report = await budget.weekly_report()
        delivered = await notifier.broadcast(fmt.weekly_report(report))
    except Exception:
        logger.exception("Nightly report failed")
        return
    logger.info("Nightly report sent to {} chats", delivered)


async def send_reminder(notifier: Notifier, fmt: MessageFormatter, recipients: Sequence[int]) -> None:
    try:
        delivered = await notifier.broadcast(fmt.texts("reminder"), recipients)
    except Exception:
        logger.exception("Reminder failed")
        return
    logger.info("Reminder sent to {} chats", delivered)


def build_scheduler(
    *,
    tz: ZoneInfo,
    report_time: time,
    reminder_times: Sequence[time],
    reminder_recipients: Sequence[int],
    budget: BudgetService,
    notifier: Notifier,
    fmt: MessageFormatter,
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(
        timezone=tz,
        job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": MISFIRE_GRACE_SECONDS},
    )
    scheduler.add_job(
        send_weekly_report,
        CronTrigger(hour=report_time.hour, minute=report_time.minute, timezone=tz),
        kwargs={"budget": budget, "notifier": notifier, "fmt": fmt},
        id="nightly_report",
    )
    if reminder_recipients:
        for at in reminder_times:
            scheduler.add_job(
                send_reminder,
                CronTrigger(hour=at.hour, minute=at.minute, timezone=tz),
                kwargs={"notifier": notifier, "fmt": fmt, "recipients": tuple(reminder_recipients)},
                id=f"reminder_{at:%H%M}",
            )
    return scheduler
