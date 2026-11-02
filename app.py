import os
import threading
from flask import Flask
import telebot
from telebot import types
from datetime import datetime, timedelta
from schedule_data import WEEK_1, WEEK_2
from apscheduler.schedulers.background import BackgroundScheduler
import pytz
import json

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER (чтобы не засыпал) ---
app = Flask(__name__)

@app.route('/')
@app.route('/health')
def health():
    return "Bot is running", 200

# --- НАСТРОЙКИ ---
TOKEN = os.getenv('BOT_TOKEN') 
MY_CHAT_ID = 123456789  # <--- ОБЯЗАТЕЛЬНО ВСТАВЬ СВОЙ РЕАЛЬНЫЙ ЧИСЛОВОЙ ID
TIMEZONE = 'Europe/Moscow' 
tz = pytz.timezone(TIMEZONE) 
STATE_FILE = 'state.json'

bot = telebot.TeleBot(TOKEN)
scheduler = BackgroundScheduler(timezone=TIMEZONE)

# Используем локальное время для якоря
ANCHOR_DATE = tz.localize(datetime(2026, 11, 2))
DAYS_OF_WEEK = {0: "Понедельник", 1: "Вторник", 2: "Среда", 3: "Четверг", 4: "Пятница", 5: "Суббота", 6: "Воскресенье"}

# --- РАБОТА С СОСТОЯНИЕМ ---
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_state(state):
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=4)

# --- ЛОГИКА РАСПИСАНИЯ ---
def get_week_number(target_date):
    if target_date.tzinfo is None:
        target_date = tz.localize(target_date)
    delta = target_date - ANCHOR_DATE
    return 1 if (delta.days // 7) % 2 == 0 else 2

def get_day_schedule_text(target_date):
    week_num = get_week_number(target_date)
    day_name = DAYS_OF_WEEK[target_date.weekday()]
    current_schedule = WEEK_1 if week_num == 1 else WEEK_2
    lessons = current_schedule.get(day_name, [])
    
    text = f"<b>📅 {day_name}, {target_date.strftime('%d.%m.%Y')}</b>\n<i>Неделя: {week_num}</i>\n\n"
    if not lessons:
        return text + "🎉 <b>Занятий нет! Отдыхай.</b>"
    
    for i, lesson in enumerate(lessons, 1):
        text += f"<b>{i}. ⏰ {lesson['time']}</b>\n📖 {lesson['subject']} ({lesson['type']})\n"
        if lesson['room']: text += f"📍 <i>Ауд: {lesson['room']}</i>\n"
        if lesson['teacher']: text += f"👨‍🏫 <i>{lesson['teacher']}</i>\n"
        text += "➖➖➖➖➖➖➖➖\n"
    return text

def get_week_schedule_text(start_date):
    week_num = get_week_number(start_date)
    current_schedule = WEEK_1 if week_num == 1 else WEEK_2
    end_date = start_date + timedelta(days=6)
    
    text = f"<b>🗓 РАСПИСАНИЕ НА НЕДЕЛЮ ({week_num})</b>\n<i>с {start_date.strftime('%d.%m')} по {end_date.strftime('%d.%m')}</i>\n\n"
    for i in range(7):
        curr_date = start_date + timedelta(days=i)
        day_name = DAYS_OF_WEEK[i]
        lessons = current_schedule.get(day_name, [])
        
        text += f"<b>🔹 {day_name} ({curr_date.strftime('%d.%m')})</b>\n"
        if not lessons:
            text += "  <i>Нет занятий</i>\n"
        else:
            for lesson in lessons:
                text += f"  • {lesson['time']} — {lesson['subject'].split(' и ')[0]}\n"
        text += "\n"
    return text

# --- ЛОГИКА ЖИВОЙ ПАНЕЛИ ---
def generate_live_text():
    now = datetime.now(tz) 
    day_name = DAYS_OF_WEEK[now.weekday()]
    current_schedule = WEEK_1 if get_week_number(now) == 1 else WEEK_2
    lessons = current_schedule.get(day_name, [])
    
    if not lessons:
        return "💤 <b>Сегодня пар нет. Отдыхай!</b>"

    current_lesson = None
    next_lesson = None

    for i, lesson in enumerate(lessons):
        start_str, end_str = lesson['time'].split(' - ')
        start_hour, start_min = map(int, start_str.split(':'))
        end_hour, end_min = map(int, end_str.split(':'))

        start_time = now.replace(hour=start_hour, minute=start_min, second=0, microsecond=0)
        end_time = now.replace(hour=end_hour, minute=end_min, second=0, microsecond=0)

        if start_time <= now <= end_time:
            current_lesson = (lesson, start_time, end_time)
            if i + 1 < len(lessons):
                next_lesson = lessons[i + 1]
            break
        elif now < start_time and next_lesson is None:
            next_lesson = lesson

    text = f"<b>🔄 ЖИВАЯ ПАНЕЛЬ | {day_name}</b>\n\n"

    if current_lesson:
        lesson, start_t, end_t = current_lesson
        total_mins = (end_t - start_t).total_seconds() / 60
        passed_mins = (now - start_t).total_seconds() / 60
        left_mins = (end_t - now).total_seconds() / 60
        
        progress = min(10, int((passed_mins / total_mins) * 10))
        bar = "🟩" * progress + "⬜" * (10 - progress)

        text += f"🔴 <b>СЕЙЧАС ИДЕТ:</b>\n"
        text += f"📖 {lesson['subject']} ({lesson['type']})\n"
        if lesson['room']: text += f"📍 Ауд: {lesson['room']}\n"
        if lesson['teacher']: text += f"👨‍🏫 {lesson['teacher']}\n"
        text += f"\n⏱ Осталось: <b>{int(left_mins)} мин.</b> (из {int(total_mins)})\n"
        text += f"{bar}\n\n"
        
    elif next_lesson:
        text += f"☕ <b>ПЕРЕРЫВ / СВОБОДНОЕ ВРЕМЯ</b>\n\n"
    else:
        text += f"🏁 <b>НА СЕГОДНЯ ВСЁ. ПАР БОЛЬШЕ НЕТ.</b>\n\n"

    if next_lesson:
        text += f"⏭ <b>СЛЕДУЮЩАЯ ПАРА:</b>\n"
        text += f"⏰ {next_lesson['time']}\n"
        text += f"📖 {next_lesson['subject']}\n"
        if next_lesson['room']: text += f"📍 Ауд: {next_lesson['room']}\n"
        
    text += f"\n<i>(Обновлено: {now.strftime('%H:%M:%S')})</i>"
    return text

def update_live_dashboard():
    state = load_state()
    msg_id = state.get("live_msg_id")
    if not msg_id: return 

    text = generate_live_text()
    try:
        bot.edit_message_text(text, chat_id=MY_CHAT_ID, message_id=msg_id, parse_mode='HTML')
    except telebot.apihelper.ApiTelegramException as e:
        if "message to edit not found" in str(e).lower():
            state["live_msg_id"] = None
            save_state(state)
        elif "message is not modified" not in str(e).lower():
            print(f"Ошибка обновления панели: {e}")

# --- КЛАВИАТУРЫ ---
def get_main_keyboard():
    state = load_state()
    markup = types.InlineKeyboardMarkup(row_width=2)
    if state.get("live_msg_id"):
        live_btn = types.InlineKeyboardButton("🔴 Отключить Live-панель", callback_data="stop_live")
    else:
        live_btn = types.InlineKeyboardButton("🟢 Включить Live-панель", callback_data="live")

    markup.add(
        types.InlineKeyboardButton("Сегодня", callback_data="today"),
        types.InlineKeyboardButton("Завтра", callback_data="tomorrow"),
        live_btn,
        types.InlineKeyboardButton("Текущая неделя", callback_data="week"),
        types.InlineKeyboardButton("Следующая неделя", callback_data="next_week")
    )
    return markup

def get_back_keyboard():
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("⬅️ Назад в меню", callback_data="main_menu"))
    return markup

# --- АВТОМАТИЧЕСКИЕ УВЕДОМЛЕНИЯ ---
def send_daily_reminder():
    tomorrow = datetime.now(tz) + timedelta(days=1) 
    text = "🔔 <b>Расписание на завтра:</b>\n\n" + get_day_schedule_text(tomorrow)
    try: bot.send_message(MY_CHAT_ID, text, parse_mode='HTML')
    except: pass

def send_weekly_summary():
    now = datetime.now(tz) 
    days_until_monday = 7 - now.weekday() if now.weekday() != 0 else 7
    next_monday = now + timedelta(days=days_until_monday)
    text = "📅 <b>Планы на следующую неделю:</b>\n\n" + get_week_schedule_text(next_monday)
    try: bot.send_message(MY_CHAT_ID, text, parse_mode='HTML')
    except: pass

def check_upcoming_classes():
    now = datetime.now(tz) 
    day_name = DAYS_OF_WEEK[now.weekday()]
    current_schedule = WEEK_1 if get_week_number(now) == 1 else WEEK_2
    lessons = current_schedule.get(day_name, [])

    if not lessons: return

    first_lesson = lessons[0]
    start_time_str = first_lesson['time'].split(' - ')[0] 
    start_hour, start_minute = map(int, start_time_str.split(':'))
    
    class_time = now.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
    reminder_time = class_time - timedelta(minutes=30)

    if now.hour == reminder_time.hour and now.minute == reminder_time.minute:
        text = (
            f"⏳ <b>Скоро первая пара!</b>\n"
            f"Через 30 минут начнется:\n\n"
            f"📖 {first_lesson['subject']}\n"
            f"⏰ {first_lesson['time']}\n"
            f"📍 Ауд: {first_lesson['room'] if first_lesson['room'] else 'Не указана'}"
        )
        try: bot.send_message(MY_CHAT_ID, text, parse_mode='HTML')
        except: pass

# --- ОБРАБОТЧИКИ КОМАНД ---
@bot.message_handler(commands=['start', 'menu'])
def start_message(message):
    welcome_text = "👋 <b>Привет! Я твой личный помощник по учебе.</b>\n\nВыбери нужный пункт ниже:"
    bot.send_message(message.chat.id, welcome_text, parse_mode='HTML', reply_markup=get_main_keyboard())

@bot.message_handler(commands=['id'])
def get_id(message):
    bot.send_message(message.chat.id, f"Твой Chat ID: <code>{message.chat.id}</code>", parse_mode='HTML')

@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    today = datetime.now(tz)
    start_of_current_week = today - timedelta(days=today.weekday())
    state = load_state()

    if call.data == "today":
        text = get_day_schedule_text(today)
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=get_back_keyboard())
    elif call.data == "tomorrow":
        text = get_day_schedule_text(today + timedelta(days=1))
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=get_back_keyboard())
    elif call.data == "week":
        text = get_week_schedule_text(start_of_current_week)
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=get_back_keyboard())
    elif call.data == "next_week":
        text = get_week_schedule_text(start_of_current_week + timedelta(days=7))
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=get_back_keyboard())
    elif call.data == "live":
        text = generate_live_text()
        msg = bot.send_message(call.message.chat.id, text, parse_mode='HTML')
        state["live_msg_id"] = msg.message_id
        save_state(state)
        try: bot.pin_chat_message(call.message.chat.id, msg.message_id, disable_notification=True)
        except: pass
        bot.answer_callback_query(call.id, "Live-панель активирована!")
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=get_main_keyboard())
    elif call.data == "stop_live":
        if state.get("live_msg_id"):
            try:
                bot.unpin_chat_message(call.message.chat.id, state["live_msg_id"])
                bot.delete_message(call.message.chat.id, state["live_msg_id"])
            except: pass
            state["live_msg_id"] = None
            save_state(state)
        bot.answer_callback_query(call.id, "Live-панель отключена.")
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=get_main_keyboard())
    elif call.data == "main_menu":
        text = "👋 <b>Главное меню</b>\n\nВыбери, что хочешь посмотреть:"
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode='HTML', reply_markup=get_main_keyboard())
        bot.answer_callback_query(call.id)

# --- ЗАПУСК ---
def run_bot():
    scheduler.add_job(send_daily_reminder, 'cron', hour=20, minute=0)
    scheduler.add_job(send_weekly_summary, 'cron', day_of_week='sun', hour=18, minute=0)
    scheduler.add_job(check_upcoming_classes, 'cron', second=0)
    scheduler.add_job(update_live_dashboard, 'cron', second=0)
    scheduler.start()
    
    print("Бот запущен в фоновом режиме...")
    bot.infinity_polling()

if __name__ == '__main__':
    threading.Thread(target=run_bot, daemon=True).start()
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
