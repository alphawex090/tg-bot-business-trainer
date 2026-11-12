import os
import asyncio
import csv
import io
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
    InlineKeyboardMarkup, InlineKeyboardButton,
    BufferedInputFile
)
from aiogram.exceptions import TelegramForbiddenError

from config import BOT_TOKEN, ADMIN_ID
from db.database import (
    init_db, add_user, save_application,
    get_last_applications, get_stats,
    get_all_user_ids, remove_user,
    get_all_applications
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ==================== FSM АНКЕТА ====================
class Form(StatesGroup):
    name = State()
    phone = State()
    request = State()

# ==================== КЛАВИАТУРЫ ====================
def main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    kb = [[KeyboardButton(text="📝 Оставить заявку")]]
    if user_id == ADMIN_ID:
        kb.append([KeyboardButton(text="⚙️ Админ панель")])
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def admin_inline() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📂 Последние 5 заявок", callback_data="last_5")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton(text="📥 Выгрузить все заявки в CSV", callback_data="export_csv")],
    ])

# ==================== СТАРТ ====================
@dp.message(Command("start"))
async def cmd_start(msg: Message):
    await add_user(msg.from_user.id, msg.from_user.username)
    await msg.answer(
        "Здравствуйте! Нажмите «Оставить заявку», чтобы записаться.",
        reply_markup=main_keyboard(msg.from_user.id),
    )

# ==================== АНКЕТА ====================
@dp.message(F.text == "📝 Оставить заявку")
async def start_form(msg: Message, state: FSMContext):
    await state.set_state(Form.name)
    await msg.answer("Как вас зовут?", reply_markup=ReplyKeyboardRemove())

@dp.message(Form.name)
async def form_name(msg: Message, state: FSMContext):
    await state.update_data(name=msg.text)
    await state.set_state(Form.phone)
    await msg.answer("Укажите телефон для связи:")

@dp.message(Form.phone)
async def form_phone(msg: Message, state: FSMContext):
    await state.update_data(phone=msg.text)
    await state.set_state(Form.request)
    await msg.answer("Опишите ваш запрос (что хотите получить):")

@dp.message(Form.request)
async def form_request(msg: Message, state: FSMContext):
    await state.update_data(request=msg.text)
    data = await state.get_data()

    app_id = await save_application(
        user_id=msg.from_user.id,
        name=data["name"],
        phone=data["phone"],
        request_text=data["request"],
    )

    await bot.send_message(
        ADMIN_ID,
        f"🔔 <b>Новая заявка #{app_id}</b>\n\n"
        f"👤 {data['name']}\n"
        f"📞 {data['phone']}\n"
        f"📝 {data['request']}\n"
        f"🆔 <code>{msg.from_user.id}</code>",
        parse_mode="HTML",
    )

    await msg.answer(
        "✅ Спасибо! Заявка принята. Мы свяжемся с вами.",
        reply_markup=main_keyboard(msg.from_user.id),
    )
    await state.clear()

# ==================== АДМИН-ПАНЕЛЬ ====================
@dp.message(F.text == "⚙️ Админ панель")
async def admin_panel(msg: Message):
    if msg.from_user.id != ADMIN_ID:
        return
    await msg.answer("Выберите действие:", reply_markup=admin_inline())

@dp.callback_query(F.data == "last_5")
async def show_last_5(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Нет доступа", show_alert=True)
        return

    apps = await get_last_applications(5)
    if not apps:
        await call.message.answer("Заявок пока нет.")
        await call.answer()
        return

    for a in apps:
        date_str = a.created_at.strftime("%Y-%m-%d %H:%M")
        await call.message.answer(
            f"<b>Заявка #{a.id}</b> ({date_str})\n\n"
            f"👤 {a.name}\n📞 {a.phone}\n📝 {a.request_text}\n"
            f"🆔 <code>{a.user_id}</code>\nСтатус: {a.status}",
            parse_mode="HTML",
        )
    await call.answer(f"Отправлено {len(apps)} заявок")

@dp.callback_query(F.data == "stats")
async def show_stats(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Нет доступа", show_alert=True)
        return
    stats = await get_stats()
    await call.message.answer(
        f"📊 Всего заявок: {stats['total']}\nСегодня: {stats['today']}"
    )
    await call.answer()

@dp.callback_query(F.data == "export_csv")
async def export_csv(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID:
        await call.answer("Нет доступа", show_alert=True)
        return

    await call.answer("Готовлю файл...")
    
    apps = await get_all_applications()
    if not apps:
        await call.message.answer("Заявок пока нет.")
        return

    output = io.StringIO()
    output.write('\ufeff') 
    writer = csv.writer(output, delimiter=';') 
    
    writer.writerow(["ID", "Дата", "Имя", "Телефон", "Запрос", "Telegram ID", "Статус"])
    
    for a in apps:
        date_str = a.created_at.strftime("%Y-%m-%d %H:%M")
        writer.writerow([a.id, date_str, a.name, a.phone, a.request_text, a.user_id, a.status])

    document = BufferedInputFile(
        output.getvalue().encode('utf-8'),
        filename="Заявки.csv"
    )
    
    await call.message.answer_document(
        document=document,
        caption=f"📊 Выгрузка всех заявок. Всего: {len(apps)} шт."
    )

# ==================== РАССЫЛКА ====================
async def broadcast(text: str) -> tuple[int, int]:
    user_ids = await get_all_user_ids()
    success, failed = 0, 0
    for uid in user_ids:
        try:
            await bot.send_message(uid, text, parse_mode="HTML")
            success += 1
        except TelegramForbiddenError:
            await remove_user(uid)
            failed += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    return success, failed

@dp.message(Command("broadcast"))
async def cmd_broadcast(msg: Message):
    if msg.from_user.id != ADMIN_ID:
        return

    text = msg.text.replace("/broadcast", "", 1).strip()
    if not text:
        await msg.answer("Напишите так: /broadcast Текст рассылки")
        return

    status = await msg.answer("📤 Рассылаю...")
    success, failed = await broadcast(text)
    await status.edit_text(f"✅ Готово.\nУспешно: {success}\nОшибок: {failed}")

# ==================== ЗАПУСК ====================
async def main():
    await init_db()
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())