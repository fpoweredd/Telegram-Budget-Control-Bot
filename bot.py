import sqlite3
import asyncio
import json
import google.generativeai as genai
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from loguru import logger
from PIL import Image
import io
import os
from dotenv import load_dotenv

# Загружаем переменные из .env файла
load_dotenv()

logger.add("bot.log", rotation="10 MB")

# Конфигурация Gemini API
GOOGLE_API_KEY = os.getenv('GOOGLE_API_KEY')
GEMINI_MODEL = os.getenv('GEMINI_MODEL', 'gemini-1.5-flash-latest')
genai.configure(api_key=GOOGLE_API_KEY)
model = genai.GenerativeModel(GEMINI_MODEL)

# Ваш токен
TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

# Заранее определенные админы и пользователи
ADMINS = [int(id) for id in os.getenv('ADMIN_IDS').split(',')]
USERS = [int(id) for id in os.getenv('USER_IDS').split(',')]

# Объединение списков админов и пользователей
ALL_USERS = ADMINS + USERS

# Инициализация бота и диспетчера
bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Состояния FSM
class BudgetStates(StatesGroup):
    waiting_for_amount = State()
    waiting_for_date = State()
    waiting_for_receipt = State()

# Подключение к базе данных
conn = sqlite3.connect('budget.db', check_same_thread=False)
cursor = conn.cursor()

# Создание таблиц
cursor.execute('''
    CREATE TABLE IF NOT EXISTS budget (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        income REAL DEFAULT 0,
        expenses REAL DEFAULT 0
    )
''')

cursor.execute('''
    CREATE TABLE IF NOT EXISTS target_date (
        id INTEGER PRIMARY KEY,
        target_date TEXT
    )
''')

cursor.execute('''
    CREATE TABLE IF NOT EXISTS transactions (
        transaction_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        date TEXT,
        amount REAL,
        type TEXT CHECK(type IN ('income', 'expense')),
        receipt_id INTEGER,
        FOREIGN KEY (user_id) REFERENCES budget (user_id),
        FOREIGN KEY (receipt_id) REFERENCES receipts (receipt_id)
    )
''')

# Удаляем старую таблицу receipts если она существует
cursor.execute('DROP TABLE IF EXISTS receipts')

cursor.execute('''
    CREATE TABLE IF NOT EXISTS receipts (
        receipt_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        username TEXT,
        date TEXT,
        store TEXT,
        total_amount REAL,
        receipt_json TEXT,
        photo_file_id TEXT,
        photo_message_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES budget (user_id)
    )
''')

# Инициализация целевой даты
new_target_date = (datetime.now() + timedelta(days=30)).strftime('%d.%m.%Y')
cursor.execute('''
    INSERT OR IGNORE INTO target_date (id, target_date) VALUES (1, ?)
''', (new_target_date,))

conn.commit()

# Вспомогательные функции
def is_admin(user_id: int) -> bool:
    return user_id in ADMINS

def is_user(user_id: int) -> bool:
    return user_id in USERS or user_id in ADMINS

async def send_all(message: str):
    for user_id in ALL_USERS:
        try:
            await bot.send_message(user_id, message, parse_mode='HTML')
        except Exception as e:
            logger.info(f"Ошибка отправки сообщения пользователю с ID {user_id}: {e}")

def get_target_date() -> str:
    cursor.execute('SELECT target_date FROM target_date WHERE id = 1')
    return cursor.fetchone()[0]

def get_days_count_from_today(date: str) -> int:
    end_date = datetime.strptime(date, "%d.%m.%Y")
    remaining_days = (end_date.date() - datetime.now().date()).days
    return remaining_days

def get_daily_summary(date: str) -> tuple:
    cursor.execute('SELECT SUM(amount) FROM transactions WHERE type = "income" AND date = ?', (date,))
    daily_income = cursor.fetchone()[0] or 0.00
    
    cursor.execute('SELECT SUM(amount) FROM transactions WHERE type = "expense" AND date = ?', (date,))
    daily_expenses = cursor.fetchone()[0] or 0.00
    
    return daily_income, daily_expenses

def get_budget_info() -> tuple:
    cursor.execute('SELECT SUM(amount) FROM transactions WHERE type = "income"')
    total_income = cursor.fetchone()[0] or 0.00

    cursor.execute('SELECT SUM(amount) FROM transactions WHERE type = "expense"')
    total_expenses = cursor.fetchone()[0] or 0.00
    
    return total_income, total_expenses, total_income - total_expenses

def get_weekly_budget_info() -> tuple:
    today = datetime.now()
    start_of_week = today - timedelta(days=today.weekday())
    start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
    
    cursor.execute('''
        SELECT amount, type, date 
        FROM transactions
    ''')
    transactions = cursor.fetchall()

    weekly_income = 0.00
    weekly_expenses = 0.00

    for amount, type_, date_str in transactions:
        transaction_date = datetime.strptime(date_str, '%d.%m.%Y')
        transaction_date = transaction_date.replace(hour=0, minute=0, second=0, microsecond=0)

        if transaction_date >= start_of_week:
            if type_ == 'income':
                weekly_income += amount
            elif type_ == 'expense':
                weekly_expenses += amount

    return weekly_income, weekly_expenses, weekly_income - weekly_expenses

async def process_receipt_image(image_data: bytes) -> dict:
    """Обработка изображения чека через Gemini API"""
    logger.info("Начало обработки изображения чека")
    
    try:
        # Конвертируем байты в PIL.Image
        image = Image.open(io.BytesIO(image_data))
        logger.info("Изображение успешно конвертировано в PIL.Image")
        
        prompt = """Распознай этот чек. Верни результат в формате JSON. Обязательные поля:

- "total": итоговая сумма по чеку
- "date": дата покупки
- "store": название магазина, заведения или компании (например: "Mercadona", "Burger King", "MediaMarkt", "Amazon", "El Corte Inglés", "AliExpress", "Apple", "Zara")
- "items": массив товаров или услуг, каждый из которых — объект с полями:
    - "name": название товара или услуги
    - "price": цена за единицу
    - "quantity": количество (если не указано явно, то 1)
    - "category": категория — одна из:
        - "еда" (продукты в магазине)
        - "фастфуд" (рестораны быстрого питания)
        - "кафе/ресторан"
        - "алкоголь"
        - "курение"
        - "аптека"
        - "одежда/обувь"
        - "бытовое"
        - "техника/электроника"
        - "транспорт"
        - "услуги"
        - "другое"

Если что-то невозможно определить — укажи `null` вместо значения.
Названия категорий должны быть на русском языке.
Формат даты - ДД.ММ.ГГГГ

Пример результата:

{
  "total": 29.90,
  "date": "01.06.2025",
  "store": "Carrefour",
  "items": [
    {"name": "Вино Rioja", "price": 7.50, "quantity": 1, "category": "алкоголь"},
    {"name": "Хлеб", "price": 1.20, "quantity": 2, "category": "еда"},
    {"name": "Батарейки AAA", "price": 3.90, "quantity": 1, "category": "бытовое"}
  ]
}

Если название товара T-Usual, T-Jove - это проезд на транспорте и магазин BCN Metro.
В категорию "курение" попадают все чеки, связанные с курением, купленные в Tabacs Estanc, а также все покупки в вейпшопах, e-liquid, картриджи для вейпов, аксессуарах для курения.

Верни только валидный JSON без пояснений, комментариев и форматирования вне JSON.
"""
        logger.info("Отправка запроса в Gemini API")
        response = model.generate_content([prompt, image])
        logger.info("Получен ответ от Gemini API")
        
        response_text = response.text
        logger.info(f"Текст ответа: {response_text[:200]}...")  # Логируем первые 200 символов
        
        # Удаляем все строки с ```
        response_text = "\n".join(
            line for line in response_text.splitlines() if not line.strip().startswith("```")
        ).strip()
        
        try:
            receipt_data = json.loads(response_text)
            logger.info("Успешная обработка JSON из чека")
            return receipt_data
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка парсинга JSON: {str(e)}")
            logger.error(f"Проблемный текст: {response_text}")
            return None
            
    except Exception as e:
        logger.error(f"Ошибка при обработке изображения: {str(e)[:200]}")
        return None

def save_receipt(user_id: int, username: str, receipt_data: dict, photo_file_id: str = None, photo_message_id: int = None) -> bool:
    """Сохранение данных чека в базу данных"""
    try:
        cursor.execute('''
            INSERT INTO receipts (user_id, username, date, store, total_amount, receipt_json, photo_file_id, photo_message_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            user_id,
            username,
            receipt_data.get('date'),
            receipt_data.get('store'),
            receipt_data.get('total'),
            json.dumps(receipt_data),
            photo_file_id,
            photo_message_id
        ))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Ошибка при сохранении чека: {e}")
        return False

def calculate_limits() -> tuple:
    """Рассчитывает дневной и недельный лимиты на основе текущего баланса и оставшихся дней"""
    budget_info = get_budget_info()
    total_balance = budget_info[0] - budget_info[1]
    target_date = get_target_date()
    days_count = get_days_count_from_today(target_date)
    
    # Рассчитываем дневной лимит
    day_spend_amount = total_balance / days_count if days_count > 0 else 0
    
    # Рассчитываем недельный лимит
    week_spend_amount = day_spend_amount * 7 if days_count > 6 else day_spend_amount * days_count
    
    return day_spend_amount, week_spend_amount

# Хэндлеры команд
@dp.message(Command("start"))
async def cmd_start(message: types.Message, state: FSMContext):
    if not is_user(message.chat.id):
        return

    cursor.execute('''INSERT OR IGNORE INTO budget (user_id, username) VALUES (?, ?)''',
                   (message.chat.id, message.from_user.username))
    conn.commit()
    
    start_message = await message.answer(
        "Напишите сколько € вы заработали или потратили\n"
        "Или отправьте фото чека для автоматического распознавания"
    )
    await state.update_data(start_message_id=start_message.message_id)
    await state.set_state(BudgetStates.waiting_for_amount)

@dp.message(Command("status"))
async def cmd_status(message: types.Message):
    if not is_user(message.chat.id):
        return

    today = datetime.now().strftime('%d.%m.%Y')
    daily_income, daily_expenses = get_daily_summary(today)
    
    try:
        daily_income = float(daily_income)
        daily_expenses = float(daily_expenses)
    except ValueError:
        await message.answer("Ошибка в данных: некорректные значения доходов или расходов.")
        return
    
    target_date = get_target_date()
    days_count = get_days_count_from_today(target_date)
    budget_info = get_budget_info()
    total_balance = budget_info[0] - budget_info[1]
    formatted_total_balance = "{:.2f}".format(total_balance)
    day_spend_amount = total_balance / days_count if days_count > 0 else 0
    formatted_day_spend_amount = "{:.2f}".format(day_spend_amount)

    message_text = (
        f"<b>----- /status за {today} -----</b>\n"
        f"До {target_date} осталось <b>{days_count}</b> д.\n\n"
        f"🟢 <b>Доход за день:</b> {daily_income:.2f} €\n"
        f"🔴 <b>Расход за день:</b> {daily_expenses:.2f} €\n"
        f"💰 <b>Баланс:</b> {formatted_total_balance} €\n\n"
        f"🎯 <b>Рекомендуется тратить не более:</b>\n"
        f"● {formatted_day_spend_amount} € в день\n"
        f"● {float(formatted_day_spend_amount) * 7:.2f} € в неделю\n\n"
        "Нажмите /start для ввода суммы"
    )

    await message.answer(message_text, parse_mode='HTML')

@dp.message(Command("date"))
async def cmd_date(message: types.Message, state: FSMContext):
    if not is_admin(message.chat.id):
        return

    current_target_date = get_target_date()
    await message.answer(
        f"Пожалуйста, введите конечную дату в формате ДД.ММ.ГГГГ\n\n"
        f"Сейчас дата: {datetime.now().strftime('%d.%m.%Y')}\n"
        f"Установленная дата: {current_target_date}"
    )
    await state.set_state(BudgetStates.waiting_for_date)

@dp.message(Command("restore"))
async def cmd_restore(message: types.Message):
    if not is_admin(message.chat.id):
        return

    cursor.execute('DELETE FROM budget')
    cursor.execute('DELETE FROM transactions')
    new_target_date = (datetime.now() + timedelta(days=30)).strftime('%d.%m.%Y')
    cursor.execute('UPDATE target_date SET target_date = ? WHERE id = 1', (new_target_date,))
    conn.commit()
    
    await message.answer(
        f"База данных успешно сброшена\n"
        f"Новая целевая дата установлена на {new_target_date}\n"
        f"Для установки даты вручную нажмите /date"
    )

@dp.message(F.photo)
async def handle_photo(message: types.Message, state: FSMContext):
    if not is_user(message.chat.id):
        return

    # Получаем фото с максимальным разрешением
    photo = message.photo[-1]
    
    # Скачиваем фото
    file = await bot.get_file(photo.file_id)
    file_path = file.file_path
    
    # Скачиваем содержимое файла
    file_content = await bot.download_file(file_path)
    with file_content as f:
        image_data = f.read()
    
    # Обрабатываем чек
    processing_message = await message.answer("Обрабатываю чек...")
    receipt_data = await process_receipt_image(image_data)
    
    # Удаляем сообщение о обработке
    await processing_message.delete()
    
    if receipt_data:
        # Сохраняем чек в базу, включая ID сообщения с фото
        if save_receipt(message.chat.id, message.from_user.username, receipt_data, photo.file_id, message.message_id):
            # Создаем кнопки подтверждения
            markup = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✅ Добавить транзакцию", callback_data=f'add_receipt_{message.chat.id}')],
                [InlineKeyboardButton(text="🔄 Обработать еще раз", callback_data=f'reprocess_{message.chat.id}')],
                [InlineKeyboardButton(text="❌ Отмена", callback_data=f'cancel_{message.chat.id}')]
            ])
            
            # Отправляем результат в чат
            await message.answer(
                f"✅ Чек успешно обработан!\n\n"
                f"Магазин: {receipt_data.get('store', 'Не определен')}\n"
                f"Дата: {receipt_data.get('date', 'Не определена')}\n"
                f"Сумма: {receipt_data.get('total', 0)} €\n\n"
                f"Товары:\n" + "\n".join(
                    f"• {item['name']} - {item['price']} €" + (f" x {item['quantity']} = {item['price'] * item['quantity']} €" if item.get('quantity', 1) > 1 else "") + f" ({item['category']})"
                    for item in receipt_data.get('items', [])
                ),
                reply_markup=markup
            )
        else:
            await message.answer("❌ Ошибка при сохранении чека")
    else:
        await message.answer("❌ Не удалось распознать чек. Попробуйте отправить более четкое фото")

# Обработчики состояний
@dp.message(BudgetStates.waiting_for_amount)
async def process_amount(message: types.Message, state: FSMContext):
    try:
        amount = float(message.text)
        formatted_amount = "{:.2f}".format(amount)
        
        # Удаляем сообщение пользователя
        await message.delete()
        
        # Удаляем стартовое сообщение
        data = await state.get_data()
        if start_message_id := data.get('start_message_id'):
            try:
                await message.bot.delete_message(message.chat.id, start_message_id)
            except Exception as e:
                logger.error(f"Ошибка при удалении стартового сообщения: {e}")
        
        markup = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🟢 Доход", callback_data=f'income_{formatted_amount}'),
                InlineKeyboardButton(text="🔴 Расход", callback_data=f'expense_{formatted_amount}')
            ]
        ])
        
        await message.answer(
            f"Вы ввели {formatted_amount} €\nЧто с этим сделать?",
            reply_markup=markup
        )
        await state.clear()
        
    except ValueError:
        await message.answer(
            "Бот ожидал сумму, вы ввели что-то другое (о.о)\n"
            "Нажмите /start для ввода суммы или /status для отчёта"
        )

@dp.message(BudgetStates.waiting_for_date)
async def process_date(message: types.Message, state: FSMContext):
    try:
        end_date = datetime.strptime(message.text, "%d.%m.%Y")
        cursor.execute('''UPDATE target_date SET target_date = ? WHERE id = 1''', 
                      (end_date.strftime('%d.%m.%Y'),))
        conn.commit()

        remaining_days = (end_date.date() - datetime.now().date()).days
        await send_all(
            f"Конечная дата установлена: {end_date.strftime('%d.%m.%Y')}\n\n"
            f"Осталось {remaining_days} дней"
        )
        await state.clear()

    except ValueError:
        await message.answer(
            "Неверный формат даты. Пожалуйста, используйте формат ДД.ММ.ГГГГ"
        )

# Обработчик callback-запросов
@dp.callback_query(F.data.startswith(('income_', 'expense_', 'add_receipt_', 'reprocess_', 'cancel_')))
async def process_callback(callback: types.CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    username = callback.from_user.username
    transaction_date = datetime.now().strftime('%d.%m.%Y')
    daily_income, daily_expenses = get_daily_summary(transaction_date)
    
    # Получаем актуальные лимиты
    day_spend_amount, week_spend_amount = calculate_limits()
    formatted_day_spend_amount = "{:.2f}".format(day_spend_amount)
    formatted_week_spend_amount = "{:.2f}".format(week_spend_amount)

    if callback.data.startswith('cancel_'):
        try:
            # Получаем последний сохраненный чек пользователя
            cursor.execute('''
                SELECT receipt_id, photo_file_id, photo_message_id FROM receipts 
                WHERE user_id = ? 
                ORDER BY created_at DESC LIMIT 1
            ''', (user_id,))
            result = cursor.fetchone()
            
            if result:
                receipt_id, photo_file_id, photo_message_id = result
                # Удаляем чек из базы
                cursor.execute('DELETE FROM receipts WHERE receipt_id = ?', (receipt_id,))
                conn.commit()
                
                # Удаляем сообщение с чеком
                await callback.message.delete()
                
                # Удаляем фото чека
                if photo_message_id:
                    try:
                        await bot.delete_message(callback.message.chat.id, photo_message_id)
                    except Exception as e:
                        logger.error(f"Ошибка при удалении фото чека: {e}")
            
            await callback.answer("✅ Чек отменен")
            
            # Устанавливаем состояние ожидания суммы без отправки сообщения
            await state.set_state(BudgetStates.waiting_for_amount)
            return
                
        except Exception as e:
            logger.error(f"Ошибка при отмене чека: {e}")
            await callback.answer("❌ Ошибка при отмене чека", show_alert=True)
            return

    elif callback.data.startswith('add_receipt_'):
        try:
            # Получаем последний сохраненный чек пользователя
            cursor.execute('''
                SELECT receipt_json, photo_message_id, receipt_id FROM receipts 
                WHERE user_id = ? 
                ORDER BY created_at DESC LIMIT 1
            ''', (user_id,))
            result = cursor.fetchone()
            
            if not result:
                await callback.answer("❌ Чек не найден", show_alert=True)
                return
                
            receipt_json, photo_message_id, receipt_id = result
            receipt_data = json.loads(receipt_json)
            
            # Отправляем сообщение с деталями чека
            await callback.message.answer(
                f"\n".join(
                    f"• {item['name']} - {item['price']} €" + (f" x {item['quantity']} = {item['price'] * item['quantity']} €" if item.get('quantity', 1) > 1 else "") + f" ({item['category']})"
                    for item in receipt_data.get('items', [])
                )
            )
            
            # Добавляем транзакцию
            amount = receipt_data.get('total', 0)
            store = receipt_data.get('store', '')
            
            # Считаем проценты по категориям
            items = receipt_data.get('items', [])
            category_totals = {}
            for item in items:
                category = item.get('category', 'другое')
                price = item.get('price', 0)
                quantity = item.get('quantity', 1)
                category_totals[category] = category_totals.get(category, 0) + (price * quantity)
            
            # Формируем строку с категориями
            category_percentages = []
            for category, total in category_totals.items():
                percentage = (total / amount) * 100
                category_percentages.append(f"{category} - {percentage:.0f}%")
            categories_str = ", ".join(category_percentages)
            
            cursor.execute('''
                INSERT INTO transactions (user_id, username, date, amount, type, receipt_id) 
                VALUES (?, ?, ?, ?, 'expense', ?)
            ''', (user_id, username, transaction_date, amount, receipt_id))
            cursor.execute('''UPDATE budget SET expenses = expenses + ? WHERE user_id = ?''', 
                          (amount, user_id))
            conn.commit()
            
            # Пересчитываем лимиты после добавления расхода
            day_spend_amount, week_spend_amount = calculate_limits()
            formatted_day_spend_amount = "{:.2f}".format(day_spend_amount)
            
            # Получаем актуальные расходы за день
            daily_income, daily_expenses = get_daily_summary(transaction_date)
            
            # Формируем сообщение с информацией о магазине и категориями
            message = f"🔴 <b>-<u>{amount:.2f}</u> €</b>"
            if store:
                message += f" ({store})"
            message += f"\n🧾 {categories_str}\n"
            message += f"🎯 Потрачено <b>{daily_expenses:.2f}</b> из <b>{formatted_day_spend_amount} €</b> за день\n"
            message += f"От @{username}"
            
            await send_all(message)
            
            # Удаляем сообщение с чеком
            await callback.message.delete()
            
            # Удаляем фото чека
            if photo_message_id:
                try:
                    await bot.delete_message(callback.message.chat.id, photo_message_id)
                except Exception as e:
                    logger.error(f"Ошибка при удалении фото чека: {e}")
            
            # Устанавливаем состояние ожидания суммы без отправки сообщения
            await state.set_state(BudgetStates.waiting_for_amount)
            return
                
        except Exception as e:
            logger.error(f"Ошибка при добавлении транзакции: {e}")
            await callback.answer("❌ Ошибка при добавлении транзакции", show_alert=True)
            return

    elif callback.data.startswith('income_'):
        amount = float(callback.data.split('_')[1])
        formatted_amount = "{:.2f}".format(amount)

        cursor.execute('''
            INSERT INTO transactions (user_id, username, date, amount, type, receipt_id) 
            VALUES (?, ?, ?, ?, 'income', NULL)
        ''', (user_id, username, transaction_date, amount))
        cursor.execute('''UPDATE budget SET income = income + ? WHERE user_id = ?''', 
                      (amount, user_id))
        conn.commit()
        
        # Пересчитываем лимиты после добавления дохода
        day_spend_amount, week_spend_amount = calculate_limits()
        formatted_day_spend_amount = "{:.2f}".format(day_spend_amount)
        
        # Получаем актуальные расходы за день
        daily_income, daily_expenses = get_daily_summary(transaction_date)
        
        await send_all(
            f"🟢 <b>+<u>{formatted_amount}</u> €</b>\n"
            f"🎯 Потрачено <b>{daily_expenses:.2f}</b> из <b>{formatted_day_spend_amount} €</b> за день\n"
            f"От @{username}"
        )

    elif callback.data.startswith('expense_'):
        amount = float(callback.data.split('_')[1])
        formatted_amount = "{:.2f}".format(amount)

        cursor.execute('''
            INSERT INTO transactions (user_id, username, date, amount, type, receipt_id) 
            VALUES (?, ?, ?, ?, 'expense', NULL)
        ''', (user_id, username, transaction_date, amount))
        cursor.execute('''UPDATE budget SET expenses = expenses + ? WHERE user_id = ?''', 
                      (amount, user_id))
        conn.commit()
        
        # Пересчитываем лимиты после добавления расхода
        day_spend_amount, week_spend_amount = calculate_limits()
        formatted_day_spend_amount = "{:.2f}".format(day_spend_amount)
        
        # Получаем актуальные расходы за день
        daily_income, daily_expenses = get_daily_summary(transaction_date)
        
        await send_all(
            f"🔴 <b>-<u>{formatted_amount}</u> €</b>\n"
            f"🎯 Потрачено <b>{daily_expenses:.2f}</b> из <b>{formatted_day_spend_amount} €</b> за день\n"
            f"От @{username}"
        )

    elif callback.data.startswith('reprocess_'):
        try:
            # Получаем последний сохраненный чек пользователя
            cursor.execute('''
                SELECT receipt_json, photo_file_id, photo_message_id FROM receipts 
                WHERE user_id = ? 
                ORDER BY created_at DESC LIMIT 1
            ''', (user_id,))
            result = cursor.fetchone()
            
            if not result:
                await callback.answer("❌ Чек не найден", show_alert=True)
                return
                
            receipt_json, photo_file_id, photo_message_id = result
            
            if not photo_file_id:
                await callback.answer("❌ Фото не найдено", show_alert=True)
                return
                
            # Скачиваем фото
            file = await bot.get_file(photo_file_id)
            file_path = file.file_path
            
            # Скачиваем содержимое файла
            file_content = await bot.download_file(file_path)
            with file_content as f:
                image_data = f.read()
            
            # Обрабатываем чек
            processing_message = await callback.message.answer("Обрабатываю чек...")
            receipt_data = await process_receipt_image(image_data)
            
            # Удаляем сообщение о обработке
            await processing_message.delete()
            
            if receipt_data:
                # Сохраняем чек в базу
                if save_receipt(user_id, username, receipt_data, photo_file_id, photo_message_id):
                    # Создаем кнопки подтверждения
                    markup = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="✅ Добавить транзакцию", callback_data=f'add_receipt_{user_id}')],
                        [InlineKeyboardButton(text="🔄 Обработать еще раз", callback_data=f'reprocess_{user_id}')],
                        [InlineKeyboardButton(text="❌ Отмена", callback_data=f'cancel_{user_id}')]
                    ])
                    
                    # Отправляем результат в чат
                    try:
                        await callback.message.edit_text(
                            f"✅ Чек успешно обработан!\n\n"
                            f"Магазин: {receipt_data.get('store', 'Не определен')}\n"
                            f"Дата: {receipt_data.get('date', 'Не определена')}\n"
                            f"Сумма: {receipt_data.get('total', 0)} €\n\n"
                            f"Товары:\n" + "\n".join(
                                f"• {item['name']} - {item['price']} €" + (f" x {item['quantity']} = {item['price'] * item['quantity']} €" if item.get('quantity', 1) > 1 else "") + f" ({item['category']})"
                                for item in receipt_data.get('items', [])
                            ),
                            reply_markup=markup
                        )
                    except Exception as e:
                        if "message is not modified" in str(e):
                            await callback.answer("✅ Чек уже обработан с теми же данными")
                        else:
                            raise e
                else:
                    await callback.answer("❌ Ошибка при сохранении чека", show_alert=True)
            else:
                await callback.answer("❌ Не удалось распознать чек", show_alert=True)
            return
                
        except Exception as e:
            logger.error(f"Ошибка при повторной обработке чека: {e}")
            await callback.answer("❌ Ошибка при обработке чека", show_alert=True)
            return

    await callback.message.delete()
    await callback.answer()
    
    # Устанавливаем состояние ожидания суммы без отправки сообщения
    await state.set_state(BudgetStates.waiting_for_amount)

# Функции для планировщика
async def send_daily_summary():
    target_date = get_target_date()
    days_count = get_days_count_from_today(target_date)
    budget_info = get_budget_info()
    total_balance = budget_info[0] - budget_info[1]
    formatted_total_balance = "{:.2f}".format(total_balance)
    
    # Получаем актуальные лимиты
    day_spend_amount, week_spend_amount = calculate_limits()
    formatted_week_spend_amount = "{:.2f}".format(week_spend_amount)
    weekly_budget_info = get_weekly_budget_info()

    # Получаем категории трат за неделю
    today = datetime.now()
    start_of_week = today - timedelta(days=today.weekday())
    start_of_week = start_of_week.replace(hour=0, minute=0, second=0, microsecond=0)
    
    cursor.execute('''
        SELECT receipt_json FROM receipts 
        WHERE created_at >= ?
    ''', (start_of_week.strftime('%Y-%m-%d'),))
    
    receipts = cursor.fetchall()
    category_totals = {}
    
    for receipt_json, in receipts:
        try:
            receipt_data = json.loads(receipt_json)
            items = receipt_data.get('items', [])
            for item in items:
                category = item.get('category', 'другое')
                price = item.get('price', 0)
                category_totals[category] = category_totals.get(category, 0) + price
        except:
            continue
    
    # Формируем строку с категориями
    categories_str = ""
    if category_totals:
        categories = [f"{category} - {total:.0f}€" for category, total in category_totals.items()]
        categories_str = f"\n({', '.join(categories)})"

    message = (
        f"📄 --- <b>{datetime.now().strftime('%d.%m.%Y')}</b> ---\n"
        f"До {target_date} осталось <b>{days_count}</b> д.\n"
        f"Потрачено: <b>{weekly_budget_info[1]:.2f}</b> из <b>{formatted_week_spend_amount} €</b> за неделю{categories_str}\n"
        f"Баланс: <b>{formatted_total_balance} €</b>"
    )
    
    await send_all(message)

async def reminder_for_users():
    message = "Время заносить доходы/расходы!\nПожалуйста, введите сумму"
    
    for user_id in USERS:
        try:
            await bot.send_message(user_id, message)
        except Exception as e:
            logger.info(f"Ошибка отправки сообщения пользователю с ID {user_id}: {e}")

async def scheduler():
    while True:
        now = datetime.now()
        
        # Проверяем время для ежедневного отчета (23:59)
        if now.hour == 23 and now.minute == 59:
            await send_daily_summary()
        
        # Проверяем время для напоминаний (14:00 и 21:00)
        if (now.hour == 14 or now.hour == 21) and now.minute == 0:
            await reminder_for_users()
        
        await asyncio.sleep(60)  # Проверяем каждую минуту

# Обработчик для всех сообщений
@dp.message()
async def handle_all_messages(message: types.Message, state: FSMContext):
    if not is_user(message.chat.id):
        return
        
    current_state = await state.get_state()
    if current_state == BudgetStates.waiting_for_amount:
        await process_amount(message, state)
    else:
        await state.set_state(BudgetStates.waiting_for_amount)

async def main():
    # Запускаем планировщик
    asyncio.create_task(scheduler())
    
    # Автоматически запускаем бота для всех пользователей
    for user_id in USERS:
        try:
            # Инициализируем пользователя в базе данных
            cursor.execute('''INSERT OR IGNORE INTO budget (user_id, username) VALUES (?, ?)''',
                         (user_id, "user"))
            conn.commit()
            
            # Устанавливаем состояние ожидания суммы без отправки сообщения
            await dp.fsm.get_context(bot=bot, user_id=user_id, chat_id=user_id).set_state(BudgetStates.waiting_for_amount)
        except Exception as e:
            logger.info(f"Ошибка автоматического запуска для пользователя {user_id}: {e}")
    
    # Запускаем бота
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())