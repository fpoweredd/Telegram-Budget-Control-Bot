"""Russian texts (LANGUAGE=ru). Keys and placeholders must match en.py."""

from src.domain.categories import Category

CATEGORY_LABELS: dict[Category, str] = {
    Category.GROCERIES: "Продукты",
    Category.FAST_FOOD: "Фастфуд",
    Category.CAFE: "Кафе",
    Category.ALCOHOL: "Алкоголь",
    Category.SMOKING: "Курение",
    Category.PHARMACY: "Аптека",
    Category.CLOTHING: "Одежда",
    Category.HOUSEHOLD: "Бытовое",
    Category.ELECTRONICS: "Техника",
    Category.TRANSPORT: "Транспорт",
    Category.SERVICES: "Услуги",
    Category.OTHER: "Другое",
}

MONTHS_SHORT = ("янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек")


def days(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        word = "день"
    elif count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        word = "дня"
    else:
        word = "дней"
    return f"{count} {word}"


MESSAGES: dict[str, str] = {
    # Commands menu
    "command_start": "Добавить доход или расход",
    "command_status": "Сегодня, баланс и лимиты",
    "command_help": "Как пользоваться ботом",
    "command_date": "Целевая дата (админ)",
    "command_restore": "Сбросить данные (админ)",
    # Manual entry
    "start": "💶 Отправьте сумму, например <code>12.50</code>\n📷 Или фото чека",
    "help": (
        "💶 Отправьте сумму и выберите доход или расход\n"
        "📷 Отправьте фото чека, я его распознаю\n"
        "👥 Все записи видят все участники\n\n"
        "/status · сегодня, баланс и лимиты\n"
        "/date · целевая дата (админ)\n"
        "/restore · сбросить данные (админ)"
    ),
    "invalid_amount": "⚠️ Это не похоже на сумму\nПопробуйте <code>12.50</code> или <code>12,50</code>",
    "amount_question": "💶 <b>{amount}</b> · доход или расход?",
    "button_income": "🟢 Доход",
    "button_expense": "🔴 Расход",
    # Transaction broadcast
    "income_line": "🟢 <b>+{amount}</b>",
    "expense_line": "🔴 <b>−{amount}</b>",
    "categories_line": "🧾 {categories}",
    "today_line": "🎯 Сегодня: {spent} / {limit}",
    "balance_line": "💰 Баланс: <b>{balance}</b>",
    "author_line": "👤 {author}",
    # Status and report
    "status_title": "📋 <b>Статус</b> · {date}",
    "days_left_line": "⏳ До {target} осталось {days}",
    "target_passed_line": "⚠️ Дата {target} прошла · задайте новую через /date",
    "income_today_line": "🟢 Доход за день: {amount}",
    "spent_today_line": "🔴 Расход за день: {amount}",
    "daily_limit_line": "🎯 Лимит на день: <b>{amount}</b>",
    "weekly_limit_line": "📅 Лимит на неделю: {amount}",
    "report_title": "📊 <b>Отчёт за неделю</b> · {date}",
    "week_spent_line": "💸 Потрачено <b>{spent}</b> / {limit} за неделю",
    "reminder": "⏰ Пора записать доходы и расходы\n💶 Отправьте сумму или 📷 фото чека",
    # Receipts
    "receipt_reading": "⏳ Читаю чек…",
    "receipt_title": "🧾 <b>{store}</b>",
    "receipt_title_dated": "🧾 <b>{store}</b> · {date}",
    "receipt_unknown_store": "Чек",
    "receipt_total_line": "💶 Итого: <b>{amount}</b>",
    "receipt_item": "{emoji} {name} · {amount}",
    "receipt_item_quantity": "{emoji} {name} · {quantity} × {price} = {amount}",
    "receipt_more_items": "… и ещё {count}",
    "receipt_no_total": "⚠️ Не удалось прочитать итог · повторите или введите сумму вручную",
    "receipt_failed": "❌ Не удалось распознать чек\nСфотографируйте чётче, чтобы чек был виден целиком",
    "receipt_download_failed": "❌ Не удалось скачать фото, отправьте его ещё раз",
    "button_receipt_add": "✅ Добавить расход",
    "button_receipt_retry": "🔄 Ещё раз",
    "button_receipt_cancel": "❌ Отмена",
    "receipt_retrying": "🔄 Читаю ещё раз…",
    "receipt_unchanged": "Результат не изменился",
    "receipt_cancelled": "Чек удалён",
    "receipt_already_handled": "Этот чек уже обработан",
    "receipt_not_found": "Чек не найден",
    # Admin
    "date_prompt": "📅 Отправьте целевую дату в формате <code>ДД.ММ.ГГГГ</code>\nСегодня: {today}\nСейчас: {target}",
    "date_invalid": "⚠️ Формат <code>ДД.ММ.ГГГГ</code>, например <code>{example}</code>",
    "date_in_past": "⚠️ Целевая дата должна быть позже сегодняшней",
    "date_set": "🎯 Целевая дата: <b>{target}</b>\n⏳ Осталось {days}",
    "reset_confirm": "⚠️ <b>Сбросить все данные?</b>\nВсе операции и чеки будут удалены",
    "button_reset_confirm": "🗑 Да, сбросить",
    "button_reset_cancel": "Отмена",
    "reset_done": "🗑 Данные сброшены\n🎯 Новая целевая дата: <b>{target}</b>\nИзменить: /date",
    "reset_cancelled": "Сброс отменён",
    # Generic
    "button_outdated": "Эта кнопка больше не активна",
    "error_generic": "Что-то пошло не так, попробуйте ещё раз",
}
