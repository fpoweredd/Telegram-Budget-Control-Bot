"""End-to-end handler tests: real Dispatcher and services, Telegram API replaced by a recorder."""

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from itertools import count
from typing import Any

import pytest
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.methods import (
    AnswerCallbackQuery,
    DeleteMessage,
    EditMessageReplyMarkup,
    EditMessageText,
    SendMessage,
    TelegramMethod,
)
from aiogram.types import CallbackQuery, Chat, InlineKeyboardMarkup, Message, PhotoSize, Update, User

from src.app import build_dispatcher
from src.domain.categories import Category
from src.domain.models import ParsedReceipt
from src.formatting import MessageFormatter
from src.handlers import receipts as receipt_handlers
from src.services.budget_service import BudgetService
from src.services.notifier import Notifier
from src.services.receipt_service import ReceiptService
from tests.conftest import FakeParser, item

ADMIN, USER, STRANGER = 1, 2, 999


class RecordingSession(BaseSession):
    """Answers Telegram API calls locally and records them."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[TelegramMethod[Any]] = []
        self._ids = count(1000)

    async def make_request(self, bot: Bot, method: TelegramMethod[Any], timeout: int | None = None) -> Any:
        self.calls.append(method)
        if isinstance(method, SendMessage):
            return Message(
                message_id=next(self._ids),
                date=datetime.now(UTC),
                chat=Chat(id=int(method.chat_id), type="private"),
                text=method.text,
            )
        return True

    async def stream_content(self, *args: Any, **kwargs: Any) -> AsyncGenerator[bytes, None]:
        yield b""

    async def close(self) -> None:
        pass

    def sent(self, chat_id: int | None = None) -> list[SendMessage]:
        return [c for c in self.calls if isinstance(c, SendMessage) and chat_id in (None, c.chat_id)]

    def of(self, kind: type[TelegramMethod[Any]]) -> list[Any]:
        return [c for c in self.calls if isinstance(c, kind)]


class Harness:
    def __init__(self, bot: Bot, session: RecordingSession, dp: Any) -> None:
        self.bot, self.session, self.dp = bot, session, dp
        self._update_ids = count(1)

    def _user(self, user_id: int) -> User:
        return User(id=user_id, is_bot=False, first_name=f"User{user_id}", username="nik" if user_id == ADMIN else None)

    def _message(self, user_id: int, message_id: int, **fields: Any) -> Message:
        chat = Chat(id=user_id, type="private")
        return Message(
            message_id=message_id, date=datetime.now(UTC), chat=chat, from_user=self._user(user_id), **fields
        )

    async def text(self, user_id: int, text: str, message_id: int = 1) -> None:
        message = self._message(user_id, message_id, text=text)
        await self.dp.feed_update(self.bot, Update(update_id=next(self._update_ids), message=message))

    async def photo(self, user_id: int, message_id: int = 50) -> None:
        photo = [PhotoSize(file_id="photo-id", file_unique_id="u", width=800, height=1200)]
        message = self._message(user_id, message_id, photo=photo)
        await self.dp.feed_update(self.bot, Update(update_id=next(self._update_ids), message=message))

    async def press(self, user_id: int, data: str, message_id: int = 77) -> None:
        """Press a button on the message ``message_id``; the same id twice is a double tap."""
        source = self._message(user_id, message_id, text="buttons")
        callback = CallbackQuery(
            id=str(next(self._update_ids)),
            from_user=self._user(user_id),
            chat_instance="ci",
            message=source,
            data=data,
        )
        await self.dp.feed_update(self.bot, Update(update_id=next(self._update_ids), callback_query=callback))


def _buttons(method: SendMessage) -> list[tuple[str, str]]:
    markup = method.reply_markup
    assert isinstance(markup, InlineKeyboardMarkup)
    return [(b.text, b.callback_data or "") for row in markup.inline_keyboard for b in row]


@pytest.fixture
async def harness(
    budget: BudgetService, receipts: ReceiptService, fmt: MessageFormatter, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[Harness, None]:
    async def fake_download(bot: Bot, file_id: str) -> bytes:
        return b"jpeg"

    monkeypatch.setattr(receipt_handlers, "download_photo", fake_download)
    session = RecordingSession()
    bot = Bot("42:TEST", session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = build_dispatcher(
        admin_ids=(ADMIN,),
        member_ids=(ADMIN, USER),
        budget=budget,
        receipts=receipts,
        notifier=Notifier(bot, (ADMIN, USER)),
        fmt=fmt,
    )
    yield Harness(bot, session, dp)


async def test_manual_expense_is_shared_with_every_member(harness: Harness) -> None:
    await harness.text(USER, "12,50")
    question = harness.session.sent(USER)[-1]
    assert question.text == "💶 <b>12.50 €</b> · income or expense?"
    expense_data = _buttons(question)[1][1]

    await harness.press(USER, expense_data)
    await harness.press(USER, expense_data)  # double tap

    broadcasts = [m for m in harness.session.sent() if m.text.startswith("🔴")]
    assert {m.chat_id for m in broadcasts} == {ADMIN, USER}
    assert broadcasts[0].text.endswith("👤 User2")  # no username: first name, never "@None"
    assert len(broadcasts) == 2  # one per member, the double tap was ignored


async def test_text_that_is_not_an_amount_gets_a_hint(harness: Harness) -> None:
    await harness.text(USER, "hello")
    assert harness.session.sent(USER)[-1].text.startswith("⚠️ That doesn't look like an amount")


async def test_strangers_are_ignored(harness: Harness) -> None:
    await harness.text(STRANGER, "/status")
    await harness.text(STRANGER, "10")
    assert harness.session.sent() == []


async def test_status_works_for_members(harness: Harness) -> None:
    await harness.text(USER, "/status")
    assert harness.session.sent(USER)[-1].text.startswith("📋 <b>Status</b>")


async def test_receipt_photo_preview_add_and_cleanup(harness: Harness, parser: FakeParser) -> None:
    parser.results.append(ParsedReceipt("McDonald's", None, 706, (item("Big Mac", 706, Category.FAST_FOOD),)))

    await harness.photo(ADMIN, message_id=50)

    preview = harness.session.sent(ADMIN)[-1]
    assert preview.text.startswith("🧾 <b>McDonald's</b>")
    add_data = _buttons(preview)[0][1]
    assert add_data == "receipt:add:1"  # the receipt id travels in the button

    await harness.press(ADMIN, add_data)

    deleted = {m.message_id for m in harness.session.of(DeleteMessage)}
    assert 50 in deleted  # the photo is removed to keep the chat clean
    broadcasts = [m for m in harness.session.sent() if m.text.startswith("🔴")]
    assert {m.chat_id for m in broadcasts} == {ADMIN, USER}
    assert broadcasts[0].text == "🔴 <b>−7.06 €</b> · McDonald's\n🧾 Fast food 100%\n🎯 Today: 7.06 / 0.00 € ⚠️\n👤 @nik"


async def test_failed_receipt_offers_retry_without_add(harness: Harness, parser: FakeParser) -> None:
    parser.results.append(ParsedReceipt(None, None, None))

    await harness.photo(ADMIN)

    preview = harness.session.sent(ADMIN)[-1]
    assert preview.text.startswith("❌ Couldn't read this receipt")
    assert [data.split(":")[1] for _, data in _buttons(preview)] == ["retry", "cancel"]


async def test_restore_needs_confirmation_and_is_admin_only(harness: Harness, budget: BudgetService) -> None:
    await harness.text(USER, "/restore")
    assert all("Reset all data" not in (m.text or "") for m in harness.session.sent(USER))

    await harness.text(ADMIN, "100")
    await harness.press(ADMIN, _buttons(harness.session.sent(ADMIN)[-1])[0][1], message_id=200)  # income 100
    await harness.text(ADMIN, "/restore")
    confirm = harness.session.sent(ADMIN)[-1]
    assert confirm.text.startswith("⚠️ <b>Reset all data?</b>")
    assert (await budget.snapshot()).balance_cents == 10000

    await harness.press(ADMIN, _buttons(confirm)[0][1], message_id=201)

    assert (await budget.snapshot()).balance_cents == 0
    assert any(m.text.startswith("🗑 All data was reset") for m in harness.session.of(EditMessageText))


async def test_date_command_sets_target_and_notifies_everyone(harness: Harness, budget: BudgetService) -> None:
    await harness.text(ADMIN, "/date")
    await harness.text(ADMIN, "31.12.2020")
    assert harness.session.sent(ADMIN)[-1].text == "⚠️ The target date must be after today"

    await harness.text(ADMIN, "03.04.2026")

    assert (await budget.snapshot()).days_left == 12
    notices = [m for m in harness.session.sent() if m.text.startswith("🎯 Target date")]
    assert {m.chat_id for m in notices} == {ADMIN, USER}


async def test_outdated_buttons_from_the_old_bot_are_answered(harness: Harness) -> None:
    await harness.press(ADMIN, "add_receipt_1")
    answers = harness.session.of(AnswerCallbackQuery)
    assert answers[-1].text == "This button is no longer active"
    assert harness.session.of(EditMessageReplyMarkup) == []
