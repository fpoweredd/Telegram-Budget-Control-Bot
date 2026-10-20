"""English texts (default). Values are HTML for Telegram's parse_mode=HTML."""

from src.domain.categories import Category

CATEGORY_LABELS: dict[Category, str] = {
    Category.GROCERIES: "Groceries",
    Category.FAST_FOOD: "Fast food",
    Category.CAFE: "Cafe",
    Category.ALCOHOL: "Alcohol",
    Category.SMOKING: "Smoking",
    Category.PHARMACY: "Pharmacy",
    Category.CLOTHING: "Clothing",
    Category.HOUSEHOLD: "Household",
    Category.ELECTRONICS: "Electronics",
    Category.TRANSPORT: "Transport",
    Category.SERVICES: "Services",
    Category.OTHER: "Other",
}

MONTHS_SHORT = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def days(count: int) -> str:
    return f"{count} day" if count == 1 else f"{count} days"


MESSAGES: dict[str, str] = {
    # Commands menu
    "command_start": "Add income or expense",
    "command_status": "Today, balance and limits",
    "command_help": "How to use the bot",
    "command_date": "Set the target date (admin)",
    "command_restore": "Reset all data (admin)",
    # Manual entry
    "start": "💶 Send an amount, e.g. <code>12.50</code>\n📷 Or send a photo of a receipt",
    "help": (
        "💶 Send an amount, then pick income or expense\n"
        "📷 Send a receipt photo and I'll read it\n"
        "👥 Every entry is shared with all members\n\n"
        "/status · today, balance and limits\n"
        "/date · set the target date (admin)\n"
        "/restore · reset all data (admin)"
    ),
    "invalid_amount": "⚠️ That doesn't look like an amount\nTry <code>12.50</code> or <code>12,50</code>",
    "amount_question": "💶 <b>{amount}</b> · income or expense?",
    "button_income": "🟢 Income",
    "button_expense": "🔴 Expense",
    # Transaction broadcast
    "income_line": "🟢 <b>+{amount}</b>",
    "expense_line": "🔴 <b>−{amount}</b>",
    "categories_line": "🧾 {categories}",
    "today_line": "🎯 Today: {spent} / {limit}",
    "balance_line": "💰 Balance: <b>{balance}</b>",
    "author_line": "👤 {author}",
    # Status and report
    "status_title": "📋 <b>Status</b> · {date}",
    "days_left_line": "⏳ {days} left until {target}",
    "target_passed_line": "⚠️ Target date {target} has passed · set a new one with /date",
    "income_today_line": "🟢 Income today: {amount}",
    "spent_today_line": "🔴 Spent today: {amount}",
    "daily_limit_line": "🎯 Daily limit: <b>{amount}</b>",
    "weekly_limit_line": "📅 Weekly limit: {amount}",
    "report_title": "📊 <b>Weekly report</b> · {date}",
    "week_spent_line": "💸 Spent <b>{spent}</b> / {limit} this week",
    "reminder": "⏰ Time to log today's income and expenses\n💶 Send an amount or 📷 a receipt photo",
    # Receipts
    "receipt_reading": "⏳ Reading the receipt…",
    "receipt_title": "🧾 <b>{store}</b>",
    "receipt_title_dated": "🧾 <b>{store}</b> · {date}",
    "receipt_unknown_store": "Receipt",
    "receipt_total_line": "💶 Total: <b>{amount}</b>",
    "receipt_item": "{emoji} {name} · {amount}",
    "receipt_item_quantity": "{emoji} {name} · {quantity} × {price} = {amount}",
    "receipt_more_items": "… and {count} more",
    "receipt_no_total": "⚠️ Couldn't read the total · retry or send the amount manually",
    "receipt_failed": "❌ Couldn't read this receipt\nTry a sharper photo with the whole receipt in frame",
    "receipt_download_failed": "❌ Couldn't download the photo, please send it again",
    "button_receipt_add": "✅ Add expense",
    "button_receipt_retry": "🔄 Retry",
    "button_receipt_cancel": "❌ Cancel",
    "receipt_retrying": "🔄 Reading it again…",
    "receipt_unchanged": "Same result as before",
    "receipt_cancelled": "Receipt discarded",
    "receipt_already_handled": "This receipt was already handled",
    "receipt_not_found": "Receipt not found",
    # Admin
    "date_prompt": "📅 Send the target date as <code>DD.MM.YYYY</code>\nToday: {today}\nCurrent target: {target}",
    "date_invalid": "⚠️ Use the format <code>DD.MM.YYYY</code>, e.g. <code>{example}</code>",
    "date_in_past": "⚠️ The target date must be after today",
    "date_set": "🎯 Target date: <b>{target}</b>\n⏳ {days} left",
    "reset_confirm": "⚠️ <b>Reset all data?</b>\nAll transactions and receipts will be deleted",
    "button_reset_confirm": "🗑 Yes, reset",
    "button_reset_cancel": "Cancel",
    "reset_done": "🗑 All data was reset\n🎯 New target date: <b>{target}</b>\nChange it with /date",
    "reset_cancelled": "Reset cancelled",
    # Generic
    "button_outdated": "This button is no longer active",
    "error_generic": "Something went wrong, please try again",
}
