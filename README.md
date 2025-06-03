# Telegram Budget Bot

A bot for personal finance management in euros with automatic receipt recognition using Google Gemini AI.

## Features

- 📊 Track income and expenses
- 🎯 Set target date for budget
- 📅 Automatic calculation of daily and weekly spending limits
- 📷 Receipt recognition via Google Gemini AI
- 📱 User-friendly Telegram interface
- 📈 Expense category statistics
- 🔔 Daily reminders and reports

## Technologies

- Python 3.8+
- aiogram 3.x
- Google Gemini AI
- SQLite

## Installation

1. Clone the repository

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create `.env` file based on `.env.example`:
```bash
cp .env.example .env
```

4. Fill in your data in `.env`:
```
TELEGRAM_BOT_TOKEN=your_bot_token
GOOGLE_API_KEY=your_google_api_key
GEMINI_MODEL=gemini-1.5-flash-latest
ADMIN_IDS=your_admin_id
USER_IDS=your_user_id
```

## Running

```bash
python bot.py
```

## Usage

1. `/start` - start entering amount or send receipt photo
2. `/status` - show current budget status
3. `/date` - set target date (admin only)
4. `/restore` - reset database (admin only)

## Receipt Recognition

The bot automatically recognizes:
- Purchase amount
- Date
- Store name
- List of items with prices
- Item categories

## Expense Categories

- 🍎 Groceries
- 🍔 Fast food
- 🍽️ Cafe/Restaurant
- 🍷 Alcohol
- 🚬 Smoking
- 💊 Pharmacy
- 👕 Clothing/Shoes
- 🏠 Household
- 💻 Electronics
- 🚌 Transport
- 🛠️ Services
- 📦 Other

You can edit and extend categories by modifying the Gemini prompt.