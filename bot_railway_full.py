import asyncio
import logging
import os
import re
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
    CallbackQuery, Message, FSInputFile
)
import aiosqlite
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter
from openpyxl.chart import PieChart, BarChart, Reference

# ==================== SOZLAMALAR ====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "8311683221:AAFWy1J5sq-9-_Kdp5qf3c7kMl9upEQoj4k")
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID", "-1003773765959"))

DAILY_LIMIT = int(os.getenv("DAILY_LIMIT", "2"))
REMINDER_DAYS = int(os.getenv("REMINDER_DAYS", "15"))
DB_PATH = os.getenv("DB_PATH", "murojaatlar.db")
MEDIA_PATH = os.getenv("MEDIA_PATH", "media_photos")
DEFAULT_IMAGE = "default_image.png"

# ==================== LOGGING ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ==================== BOT VA DISPATCHER ====================
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ==================== VALIDATSIYA FUNKSIYALARI ====================
def validate_passport(passport: str) -> bool:
    """Pasport tekshirish: AA1234567 (2 harf + 7 raqam)"""
    if not passport:
        return False
    pattern = r'^[A-Z]{2}\d{7}$'
    return bool(re.match(pattern, passport))

def validate_phone(phone: str) -> bool:
    """Telefon tekshirish: +998XXXXXXXXX yoki 998XXXXXXXXX"""
    if not phone:
        return False
    phone_clean = phone.replace('+', '').replace(' ', '').replace('-', '')
    pattern = r'^998\d{9}$'
    return bool(re.match(pattern, phone_clean))

def validate_full_name(full_name: str) -> bool:
    """F.I.Sh tekshirish: kamida 2 ta so'z, raqamsiz"""
    if not full_name:
        return False
    words = full_name.strip().split()
    if len(words) < 2:
        return False
    return all(not any(char.isdigit() for char in word) for word in words)

# ==================== MA'LUMOTLAR BAZASI ====================
class Database:
    """Database boshqaruvi"""
    
    def __init__(self):
        self.db_path = DB_PATH
        
    async def init_db(self):
        """Database yaratish va jadvallarni sozlash"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("PRAGMA foreign_keys = OFF")
                
                # Foydalanuvchilar jadvali
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS users (
                        user_id INTEGER PRIMARY KEY,
                        full_name TEXT,
                        phone TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # Murojaatlar jadvali
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS murojaatlar (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        full_name TEXT,
                        passport TEXT,
                        phone TEXT,
                        address TEXT,
                        category TEXT,
                        text TEXT,
                        image_path TEXT,
                        status TEXT DEFAULT 'Yangi',
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        admin_checked_at DATETIME,
                        group_message_id INTEGER
                    )
                """)
                
                # Javoblar jadvali
                await db.execute("""
                    CREATE TABLE IF NOT EXISTS javoblar (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        murojaat_id INTEGER,
                        admin_id INTEGER,
                        admin_username TEXT,
                        javob_text TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """)
                
                # MIGRATSIYA: kerakli ustunlarni qo'shish
                try:
                    cursor = await db.execute("PRAGMA table_info(murojaatlar)")
                    columns = await cursor.fetchall()
                    column_names = [col[1] for col in columns]
                    
                    required_columns = {
                        'address': 'TEXT',
                        'group_message_id': 'INTEGER',
                        'admin_checked_at': 'DATETIME'
                    }
                    
                    for col_name, col_type in required_columns.items():
                        if col_name not in column_names:
                            logger.warning(f"⚠️ '{col_name}' ustuni topilmadi, qo'shilmoqda...")
                            await db.execute(f"ALTER TABLE murojaatlar ADD COLUMN {col_name} {col_type}")
                            await db.commit()
                            logger.info(f"✅ '{col_name}' ustuni qo'shildi")
                    
                    logger.info("✅ Barcha ustunlar tekshirildi")
                    
                except Exception as migration_error:
                    logger.error(f"❌ Migratsiya xatolik: {migration_error}")
                
                await db.commit()
                logger.info("✅ Database muvaffaqiyatli yaratildi")
        except Exception as e:
            logger.error(f"❌ Database yaratishda xatolik: {e}")
            raise
    
    async def add_user(self, user_id: int, full_name: str, phone: str):
        """Foydalanuvchi qo'shish"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("PRAGMA foreign_keys = OFF")
                await db.execute(
                    "INSERT OR REPLACE INTO users (user_id, full_name, phone) VALUES (?, ?, ?)",
                    (user_id, full_name, phone)
                )
                await db.commit()
                logger.info(f"✅ User qo'shildi: {user_id}")
        except Exception as e:
            logger.error(f"❌ User qo'shishda xatolik: {e}")
    
    async def add_murojaat(self, user_id: int, full_name: str, passport: str, 
                          phone: str, address: str, category: str, text: str, 
                          image_path: str = None, group_message_id: int = None):
        """Murojaat qo'shish"""
        try:
            logger.info(f"💾 Murojaat saqlanmoqda: user={user_id}, group_msg={group_message_id}")
            
            await self.add_user(user_id, full_name, phone)
            
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("PRAGMA foreign_keys = OFF")
                cursor = await db.execute("""
                    INSERT INTO murojaatlar 
                    (user_id, full_name, passport, phone, address, category, text, image_path, group_message_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (user_id, full_name, passport, phone, address, category, text, image_path, group_message_id))
                await db.commit()
                murojaat_id = cursor.lastrowid
                
                logger.info(f"✅ Murojaat saqlandi: ID={murojaat_id}")
                return murojaat_id
                
        except Exception as e:
            logger.error(f"❌ Murojaat qo'shishda xatolik: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    async def get_user_murojaatlar(self, user_id: int):
        """Foydalanuvchi murojaatlari"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT * FROM murojaatlar WHERE user_id = ? ORDER BY created_at DESC",
                    (user_id,)
                ) as cursor:
                    return await cursor.fetchall()
        except Exception as e:
            logger.error(f"❌ Murojaatlarni olishda xatolik: {e}")
            return []
    
    async def get_murojaat_by_id(self, murojaat_id: int):
        """ID bo'yicha murojaat"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT * FROM murojaatlar WHERE id = ?",
                    (murojaat_id,)
                ) as cursor:
                    return await cursor.fetchone()
        except Exception as e:
            logger.error(f"❌ Murojaatni olishda xatolik: {e}")
            return None
    
    async def get_murojaat_by_group_msg(self, group_message_id: int):
        """Group message ID bo'yicha murojaat topish"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT * FROM murojaatlar WHERE group_message_id = ?",
                    (group_message_id,)
                ) as cursor:
                    result = await cursor.fetchone()
                    logger.info(f"🔍 Murojaat qidiruv: group_msg_id={group_message_id}, topildi={result is not None}")
                    return result
        except Exception as e:
            logger.error(f"❌ Group message bo'yicha qidiruvda xatolik: {e}")
            return None
    
    async def add_javob(self, murojaat_id: int, admin_id: int, admin_username: str, javob_text: str):
        """Javob qo'shish"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("PRAGMA foreign_keys = OFF")
                await db.execute("""
                    INSERT INTO javoblar (murojaat_id, admin_id, admin_username, javob_text)
                    VALUES (?, ?, ?, ?)
                """, (murojaat_id, admin_id, admin_username, javob_text))
                
                # Status yangilash
                await db.execute(
                    "UPDATE murojaatlar SET status = ?, admin_checked_at = ? WHERE id = ?",
                    ('Javob berilgan', datetime.now(), murojaat_id)
                )
                await db.commit()
                logger.info(f"✅ Javob qo'shildi: murojaat={murojaat_id}")
                return True
        except Exception as e:
            logger.error(f"❌ Javob qo'shishda xatolik: {e}")
            return False
    
    async def get_javoblar(self, murojaat_id: int):
        """Murojaat javoblari"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT * FROM javoblar WHERE murojaat_id = ? ORDER BY created_at ASC",
                    (murojaat_id,)
                ) as cursor:
                    return await cursor.fetchall()
        except Exception as e:
            logger.error(f"❌ Javoblarni olishda xatolik: {e}")
            return []
    
    async def get_today_count(self, user_id: int):
        """Bugungi murojaatlar soni"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                today = datetime.now().date()
                async with db.execute(
                    "SELECT COUNT(*) FROM murojaatlar WHERE user_id = ? AND DATE(created_at) = ?",
                    (user_id, today)
                ) as cursor:
                    result = await cursor.fetchone()
                    return result[0] if result else 0
        except Exception as e:
            logger.error(f"❌ Bugungi soni olishda xatolik: {e}")
            return 0
    
    async def get_old_pending_murojaatlar(self, days: int):
        """Eski javobsiz murojaatlar"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                cutoff_date = datetime.now() - timedelta(days=days)
                async with db.execute("""
                    SELECT * FROM murojaatlar 
                    WHERE status = 'Yangi' AND created_at < ?
                    ORDER BY created_at ASC
                """, (cutoff_date,)) as cursor:
                    return await cursor.fetchall()
        except Exception as e:
            logger.error(f"❌ Eski murojaatlarni olishda xatolik: {e}")
            return []
    
    async def get_all_statistics(self):
        """Barcha statistika"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                
                # Umumiy statistika
                async with db.execute("SELECT COUNT(*) as total FROM murojaatlar") as cursor:
                    total = (await cursor.fetchone())['total']
                
                async with db.execute(
                    "SELECT COUNT(*) as answered FROM murojaatlar WHERE status = 'Javob berilgan'"
                ) as cursor:
                    answered = (await cursor.fetchone())['answered']
                
                async with db.execute(
                    "SELECT COUNT(*) as pending FROM murojaatlar WHERE status = 'Yangi'"
                ) as cursor:
                    pending = (await cursor.fetchone())['pending']
                
                # Bugungi statistika
                today = datetime.now().date()
                async with db.execute(
                    "SELECT COUNT(*) as today FROM murojaatlar WHERE DATE(created_at) = ?",
                    (today,)
                ) as cursor:
                    today_count = (await cursor.fetchone())['today']
                
                # Haftalik statistika
                week_ago = datetime.now() - timedelta(days=7)
                async with db.execute(
                    "SELECT COUNT(*) as weekly FROM murojaatlar WHERE created_at >= ?",
                    (week_ago,)
                ) as cursor:
                    weekly = (await cursor.fetchone())['weekly']
                
                # Kategoriyalar
                async with db.execute("""
                    SELECT category, COUNT(*) as count 
                    FROM murojaatlar 
                    GROUP BY category 
                    ORDER BY count DESC
                """) as cursor:
                    categories = await cursor.fetchall()
                
                return {
                    'total': total,
                    'answered': answered,
                    'pending': pending,
                    'today': today_count,
                    'weekly': weekly,
                    'categories': categories
                }
        except Exception as e:
            logger.error(f"❌ Statistika olishda xatolik: {e}")
            return None
    
    async def get_all_murojaatlar_with_javoblar(self):
        """Barcha murojaatlar va javoblar (Excel uchun)"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                
                # Barcha murojaatlar
                async with db.execute(
                    "SELECT * FROM murojaatlar ORDER BY created_at DESC"
                ) as cursor:
                    murojaatlar = await cursor.fetchall()
                
                # Har bir murojaat uchun javoblarni olish
                result = []
                for m in murojaatlar:
                    javoblar = await self.get_javoblar(m['id'])
                    result.append({
                        'murojaat': dict(m),
                        'javoblar': [dict(j) for j in javoblar]
                    })
                
                return result
        except Exception as e:
            logger.error(f"❌ To'liq ma'lumotlarni olishda xatolik: {e}")
            return []

# Database obyekti
db = Database()

# ==================== FSM STATES ====================
class MurojaatStates(StatesGroup):
    waiting_for_full_name = State()
    waiting_for_passport = State()
    waiting_for_phone = State()
    waiting_for_address = State()
    waiting_for_category = State()
    waiting_for_text = State()
    waiting_for_image = State()

# ==================== KEYBOARD YARATISH ====================
def get_main_menu():
    """Asosiy menyu - FAQAT SHAXSIY CHATDA"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✍️ Murojaat yuborish")],
            [KeyboardButton(text="📋 Mening murojaatlarim")],
            [KeyboardButton(text="ℹ️ Ma'lumot")]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
    return keyboard

def get_category_keyboard():
    """Kategoriyalar klaviaturasi"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏥 Sog'liqni saqlash", callback_data="cat_health")],
        [InlineKeyboardButton(text="🏫 Ta'lim", callback_data="cat_education")],
        [InlineKeyboardButton(text="🚧 Kommunal xizmat", callback_data="cat_communal")],
        [InlineKeyboardButton(text="🚗 Transport", callback_data="cat_transport")],
        [InlineKeyboardButton(text="🏛 Boshqa", callback_data="cat_other")]
    ])
    return keyboard

def get_image_keyboard():
    """Rasm yuklash klaviaturasi"""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏭ O'tkazib yuborish", callback_data="skip_image")]
    ])
    return keyboard

# ==================== /START HANDLER ====================
@dp.message(CommandStart())
async def cmd_start(message: Message):
    """Start komandasi - FAQAT SHAXSIY CHATDA"""
    # Faqat shaxsiy chatda ishlaydi
    if message.chat.type != "private":
        return
    
    await message.answer(
        f"👋 Assalomu alaykum, <b>{message.from_user.first_name}</b>!\n\n"
        "🏛 <b>Hokimlik murojaatlari boti</b>ga xush kelibsiz!\n\n"
        "📝 Bu bot orqali siz:\n"
        "   • Hokimlikka murojaat yuborishingiz\n"
        "   • Murojaatlaringizni kuzatishingiz\n"
        "   • Javoblarni olishingiz mumkin\n\n"
        "👇 Quyidagi tugmalardan foydalaning:",
        reply_markup=get_main_menu(),
        parse_mode="HTML"
    )

# ==================== MUROJAAT YUBORISH ====================
@dp.message(F.text == "✍️ Murojaat yuborish")
async def start_murojaat(message: Message, state: FSMContext):
    """Murojaat boshlash - FAQAT SHAXSIY CHATDA"""
    # Faqat shaxsiy chatda ishlaydi
    if message.chat.type != "private":
        return
    
    # Kunlik limit tekshirish
    today_count = await db.get_today_count(message.from_user.id)
    if today_count >= DAILY_LIMIT:
        await message.answer(
            f"⏳ <b>Kechirasiz!</b>\n\n"
            f"Siz bugun allaqachon {DAILY_LIMIT} ta murojaat yuborgansiz.\n"
            f"Ertaga yana murojaat yuborishingiz mumkin.\n\n"
            f"📊 Bugun: {today_count}/{DAILY_LIMIT}",
            parse_mode="HTML",
            reply_markup=get_main_menu()
        )
        return
    
    await message.answer(
        "📋 <b>YANGI MUROJAAT</b>\n\n"
        "1️⃣ <b>To'liq ismingizni kiriting:</b>\n\n"
        "📝 Format: <code>Familiya Ism Otasining ismi</code>\n\n"
        "✅ To'g'ri: <code>Aliyev Vali Akbarovich</code>\n"
        "❌ Noto'g'ri: <code>Vali</code>",
        parse_mode="HTML"
    )
    await state.set_state(MurojaatStates.waiting_for_full_name)

@dp.message(MurojaatStates.waiting_for_full_name)
async def process_full_name(message: Message, state: FSMContext):
    """F.I.Sh qabul qilish"""
    full_name = message.text.strip()
    
    if not validate_full_name(full_name):
        await message.answer(
            "❌ <b>Noto'g'ri format!</b>\n\n"
            "To'liq ismingizni to'g'ri kiriting (kamida 2 ta so'z, raqamsiz).\n\n"
            "Qaytadan yozing:",
            parse_mode="HTML"
        )
        return
    
    await state.update_data(full_name=full_name)
    await state.set_state(MurojaatStates.waiting_for_passport)
    
    await message.answer(
        "✅ <b>Ism qabul qilindi!</b>\n\n"
        "2️⃣ <b>Pasport seriya va raqamingizni kiriting:</b>\n\n"
        "📝 Format: <code>AA1234567</code>\n\n"
        "✅ To'g'ri: <code>AA1234567</code>\n"
        "❌ Noto'g'ri: <code>aa1234567</code>",
        parse_mode="HTML"
    )

@dp.message(MurojaatStates.waiting_for_passport)
async def process_passport(message: Message, state: FSMContext):
    """Pasport qabul qilish"""
    passport = message.text.strip().upper()
    
    if not validate_passport(passport):
        await message.answer(
            "❌ <b>Noto'g'ri format!</b>\n\n"
            "Pasportni to'g'ri kiriting (2 harf + 7 raqam).\n\n"
            "Qaytadan yozing:",
            parse_mode="HTML"
        )
        return
    
    await state.update_data(passport=passport)
    await state.set_state(MurojaatStates.waiting_for_phone)
    
    await message.answer(
        "✅ <b>Pasport qabul qilindi!</b>\n\n"
        "3️⃣ <b>Telefon raqamingizni kiriting:</b>\n\n"
        "📝 Format: <code>+998XXXXXXXXX</code>\n\n"
        "✅ To'g'ri: <code>+998901234567</code>",
        parse_mode="HTML"
    )

@dp.message(MurojaatStates.waiting_for_phone)
async def process_phone(message: Message, state: FSMContext):
    """Telefon qabul qilish"""
    phone = message.text.strip()
    
    if not validate_phone(phone):
        await message.answer(
            "❌ <b>Noto'g'ri telefon!</b>\n\n"
            "Telefon raqamini to'g'ri kiriting.\n\n"
            "Qaytadan yozing:",
            parse_mode="HTML"
        )
        return
    
    await state.update_data(phone=phone)
    await state.set_state(MurojaatStates.waiting_for_address)
    
    await message.answer(
        "✅ <b>Telefon qabul qilindi!</b>\n\n"
        "4️⃣ <b>Yashash manzilingizni kiriting:</b>\n\n"
        "📝 Misol: <code>Toshkent sh., Yunusobod t., Amir Temur ko'chasi, 15-uy</code>",
        parse_mode="HTML"
    )

@dp.message(MurojaatStates.waiting_for_address)
async def process_address(message: Message, state: FSMContext):
    """Manzil qabul qilish"""
    address = message.text.strip()
    
    if len(address) < 10:
        await message.answer(
            "❌ <b>Manzil juda qisqa!</b>\n\n"
            "To'liq manzilni kiriting (kamida 10 ta belgi).\n\n"
            "Qaytadan yozing:",
            parse_mode="HTML"
        )
        return
    
    await state.update_data(address=address)
    await state.set_state(MurojaatStates.waiting_for_category)
    
    await message.answer(
        "✅ <b>Manzil qabul qilindi!</b>\n\n"
        "5️⃣ <b>Murojaat kategoriyasini tanlang:</b>",
        parse_mode="HTML",
        reply_markup=get_category_keyboard()
    )

@dp.callback_query(F.data.startswith("cat_"))
async def process_category(callback: CallbackQuery, state: FSMContext):
    """Kategoriya tanlash"""
    categories = {
        "cat_health": "🏥 Sog'liqni saqlash",
        "cat_education": "🏫 Ta'lim",
        "cat_communal": "🚧 Kommunal xizmat",
        "cat_transport": "🚗 Transport",
        "cat_other": "🏛 Boshqa"
    }
    
    category = categories.get(callback.data, "🏛 Boshqa")
    await state.update_data(category=category)
    await state.set_state(MurojaatStates.waiting_for_text)
    
    try:
        await callback.message.edit_text(
            f"✅ <b>Kategoriya tanlandi: {category}</b>\n\n"
            "6️⃣ <b>Muammongizni batafsil yozing:</b>\n\n"
            "📝 Kamida 10 ta belgi kiriting.",
            parse_mode="HTML"
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"❌ Callback edit xatolik: {e}")
        await callback.answer("✅ Kategoriya tanlandi!")

@dp.message(MurojaatStates.waiting_for_text)
async def process_text(message: Message, state: FSMContext):
    """Matn qabul qilish"""
    text = message.text.strip()
    
    if len(text) < 10:
        await message.answer(
            "❌ <b>Matn juda qisqa!</b>\n\n"
            "Muammongizni batafsil yozing (kamida 10 ta belgi).\n\n"
            "Qaytadan yozing:",
            parse_mode="HTML"
        )
        return
    
    await state.update_data(text=text)
    await state.set_state(MurojaatStates.waiting_for_image)
    
    await message.answer(
        "✅ <b>Matn qabul qilindi!</b>\n\n"
        "7️⃣ <b>Rasm yuklash (ixtiyoriy):</b>\n\n"
        "📷 Agar muammoga oid rasm bo'lsa, yuboring.\n"
        "Yoki \"O'tkazib yuborish\" tugmasini bosing.",
        reply_markup=get_image_keyboard(),
        parse_mode="HTML"
    )

@dp.message(MurojaatStates.waiting_for_image, F.photo)
async def process_image(message: Message, state: FSMContext):
    """Rasm qabul qilish"""
    try:
        photo = message.photo[-1]
        file_name = f"{message.from_user.id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
        file_path = os.path.join(MEDIA_PATH, file_name)
        
        await bot.download(photo, destination=file_path)
        logger.info(f"✅ Rasm saqlandi: {file_path}")
        
        await state.update_data(image_path=file_path)
        await finish_murojaat(message, state)
        
    except Exception as e:
        logger.error(f"❌ Rasm saqlashda xatolik: {e}")
        await message.answer("❌ Rasm saqlashda xatolik. Qaytadan yuboring yoki o'tkazing.")

@dp.callback_query(F.data == "skip_image")
async def skip_image(callback: CallbackQuery, state: FSMContext):
    """Rasmni o'tkazish"""
    await state.update_data(image_path=None)
    try:
        await callback.message.delete()
    except:
        pass
    await callback.answer()
    await finish_murojaat(callback.message, state)

async def finish_murojaat(message: Message, state: FSMContext):
    """Murojaatni yakunlash va yuborish"""
    try:
        data = await state.get_data()
        user_id = message.from_user.id
        
        # Guruhga yuborish (KNOPKASIZ!)
        group_text = (
            f"📩 <b>YANGI MUROJAAT</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 <b>F.I.Sh:</b> {data['full_name']}\n"
            f"🛂 <b>Pasport:</b> {data['passport']}\n"
            f"📱 <b>Telefon:</b> {data['phone']}\n"
            f"📍 <b>Manzil:</b> {data['address']}\n"
            f"📂 <b>Kategoriya:</b> {data['category']}\n\n"
            f"📝 <b>MUROJAAT:</b>\n{data['text']}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👤 User ID: <code>{user_id}</code>\n"
            f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
            f"💬 <i>Javob berish uchun bu xabarga REPLY qiling</i>"
        )
        
        # MUHIM: Guruhga KNOPKASIZ yuborish
        if data.get('image_path') and os.path.exists(data['image_path']):
            group_msg = await bot.send_photo(
                chat_id=GROUP_CHAT_ID,
                photo=FSInputFile(data['image_path']),
                caption=group_text,
                parse_mode="HTML"
                # reply_markup yo'q!
            )
        else:
            group_msg = await bot.send_message(
                chat_id=GROUP_CHAT_ID,
                text=group_text,
                parse_mode="HTML"
                # reply_markup yo'q!
            )
        
        # Database ga saqlash
        murojaat_id = await db.add_murojaat(
            user_id=user_id,
            full_name=data['full_name'],
            passport=data['passport'],
            phone=data['phone'],
            address=data['address'],
            category=data['category'],
            text=data['text'],
            image_path=data.get('image_path'),
            group_message_id=group_msg.message_id
        )
        
        if not murojaat_id:
            await message.answer("❌ Murojaatni saqlashda xatolik!")
            await state.clear()
            return
        
        # Foydalanuvchiga xabar
        await message.answer(
            f"✅ <b>MUROJAAT YUBORILDI!</b>\n\n"
            f"📋 Murojaat raqami: <b>#{murojaat_id}</b>\n"
            f"📂 Kategoriya: {data['category']}\n"
            f"📅 Sana: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
            f"⏰ Javob tez orada keladi!\n"
            f"📲 Javobni shu botdan olasiz.",
            parse_mode="HTML",
            reply_markup=get_main_menu()
        )
        
        await state.clear()
        logger.info(f"✅ Murojaat yuborildi: #{murojaat_id} from user {user_id}")
        
    except Exception as e:
        logger.error(f"❌ Murojaatni yakunlashda xatolik: {e}")
        import traceback
        traceback.print_exc()
        await message.answer(
            "❌ Xatolik yuz berdi. Qaytadan urinib ko'ring.",
            reply_markup=get_main_menu()
        )
        await state.clear()

# ==================== MENING MUROJAATLARIM ====================
@dp.message(F.text == "📋 Mening murojaatlarim")
async def my_murojaatlar(message: Message):
    """Foydalanuvchi murojaatlari - FAQAT SHAXSIY CHATDA"""
    if message.chat.type != "private":
        return
    
    murojaatlar = await db.get_user_murojaatlar(message.from_user.id)
    
    if not murojaatlar:
        await message.answer(
            "📭 Sizda hali murojaatlar yo'q.\n\n"
            "Yangi murojaat yuborish uchun \"✍️ Murojaat yuborish\" tugmasini bosing.",
            reply_markup=get_main_menu()
        )
        return
    
    response = (
        f"📋 <b>MENING MUROJAATLARIM</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Jami: <b>{len(murojaatlar)} ta</b>\n\n"
    )
    
    for m in murojaatlar:
        status_emoji = "✅" if m['status'] == "Javob berilgan" else "⏳"
        response += (
            f"{status_emoji} <b>#{m['id']}</b> - {m['category']}\n"
            f"   📅 {m['created_at'][:16]}\n"
            f"   📊 {m['status']}\n\n"
        )
    
    response += "\n💡 Batafsil ko'rish uchun murojaat raqamini yuboring: <code>#123</code>"
    
    await message.answer(response, parse_mode="HTML")

@dp.message(F.text.regexp(r'^#\d+$'))
async def view_murojaat_detail(message: Message):
    """Murojaat tafsilotlari - FAQAT SHAXSIY CHATDA"""
    if message.chat.type != "private":
        return
    
    try:
        murojaat_id = int(message.text.strip('#'))
        murojaat = await db.get_murojaat_by_id(murojaat_id)
        
        if not murojaat:
            await message.answer("❌ Murojaat topilmadi!")
            return
        
        # Faqat o'zining murojaati
        if murojaat['user_id'] != message.from_user.id:
            await message.answer("❌ Bu murojaat sizga tegishli emas!")
            return
        
        # Murojaat ma'lumotlari
        response = (
            f"📋 <b>MUROJAAT #{murojaat['id']}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 <b>F.I.Sh:</b> {murojaat['full_name']}\n"
            f"🛂 <b>Pasport:</b> {murojaat['passport']}\n"
            f"📱 <b>Telefon:</b> {murojaat['phone']}\n"
            f"📍 <b>Manzil:</b> {murojaat['address']}\n"
            f"📂 <b>Kategoriya:</b> {murojaat['category']}\n\n"
            f"📝 <b>MUROJAAT:</b>\n{murojaat['text']}\n\n"
            f"📅 <b>Yuborilgan:</b> {murojaat['created_at'][:16]}\n"
            f"📊 <b>Holat:</b> {murojaat['status']}\n"
        )
        
        # Javoblar
        javoblar = await db.get_javoblar(murojaat['id'])
        if javoblar:
            response += "\n━━━━━━━━━━━━━━━━━━━━━━\n"
            response += "💬 <b>JAVOBLAR:</b>\n\n"
            for j in javoblar:
                response += (
                    f"👤 <b>{j['admin_username'] or 'Admin'}</b>\n"
                    f"📅 {j['created_at'][:16]}\n"
                    f"📝 {j['javob_text']}\n\n"
                )
        
        # Rasm yuborish
        if murojaat['image_path'] and os.path.exists(murojaat['image_path']):
            photo = FSInputFile(murojaat['image_path'])
            await message.answer_photo(
                photo=photo,
                caption=response,
                parse_mode="HTML"
            )
        else:
            await message.answer(response, parse_mode="HTML")
        
    except ValueError:
        await message.answer("❌ Noto'g'ri format! Misol: <code>#123</code>", parse_mode="HTML")
    except Exception as e:
        logger.error(f"❌ Murojaat ko'rishda xatolik: {e}")
        await message.answer("❌ Xatolik yuz berdi!")

# ==================== MA'LUMOT ====================
@dp.message(F.text == "ℹ️ Ma'lumot")
async def cmd_info(message: Message):
    """Ma'lumot - FAQAT SHAXSIY CHATDA"""
    if message.chat.type != "private":
        return
    
    await message.answer(
        "ℹ️ <b>BOT HAQIDA MA'LUMOT</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🏛 Bu bot orqali hokimlikka murojaat yuborishingiz mumkin.\n\n"
        f"📊 <b>Qoidalar:</b>\n"
        f"   • Kunlik limit: {DAILY_LIMIT} ta murojaat\n"
        f"   • Javob: {REMINDER_DAYS} kun ichida\n"
        f"   • Barcha ma'lumotlar maxfiy\n\n"
        "📝 <b>Murojaat yuborish:</b>\n"
        "   1. F.I.Sh kiriting\n"
        "   2. Pasport ma'lumotlari\n"
        "   3. Telefon raqam\n"
        "   4. Manzil\n"
        "   5. Kategoriya tanlang\n"
        "   6. Muammoni yozing\n"
        "   7. Rasm (ixtiyoriy)\n\n"
        "📞 <b>Yordam kerakmi?</b>\n"
        "Adminlar bilan bog'laning.",
        parse_mode="HTML",
        reply_markup=get_main_menu()
    )

# ==================== ADMIN GURUHDA JAVOB BERISH ====================
@dp.message(F.reply_to_message, F.chat.id == GROUP_CHAT_ID)
async def group_reply_handler(message: Message):
    """Guruhda REPLY orqali javob berish - TUZATILGAN"""
    try:
        # Reply qilingan xabar ID
        reply_to_message_id = message.reply_to_message.message_id
        javob_text = message.text.strip()
        
        logger.info(f"🔍 Reply keldi: msg_id={reply_to_message_id}, text={javob_text[:50]}")
        
        # Database dan murojaatni topish
        murojaat = await db.get_murojaat_by_group_msg(reply_to_message_id)
        
        if not murojaat:
            logger.warning(f"⚠️ Murojaat topilmadi: group_msg_id={reply_to_message_id}")
            await message.reply(
                "❌ <b>Murojaat topilmadi!</b>\n\n"
                f"Reply qilingan xabar ID: <code>{reply_to_message_id}</code>\n\n"
                "<i>Bu xabar murojaat emas yoki database da yo'q.</i>",
                parse_mode="HTML"
            )
            return
        
        murojaat_id = murojaat['id']
        
        # Admin ma'lumotlari
        admin_id = message.from_user.id
        admin_username = message.from_user.username or message.from_user.first_name or "Admin"
        
        # Javobni saqlash
        success = await db.add_javob(murojaat_id, admin_id, admin_username, javob_text)
        
        if not success:
            await message.reply("❌ Javob saqlashda xatolik!")
            return
        
        # Foydalanuvchiga javob yuborish
        try:
            await bot.send_message(
                chat_id=murojaat['user_id'],
                text=(
                    f"📬 <b>MUROJAATINGIZGA JAVOB KELDI!</b>\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"📋 Murojaat: <b>#{murojaat_id}</b>\n"
                    f"📂 Kategoriya: {murojaat['category']}\n\n"
                    f"💬 <b>JAVOB:</b>\n{javob_text}\n\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"👤 Javob berdi: {admin_username}\n"
                    f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
                ),
                parse_mode="HTML"
            )
            
            # Guruhda tasdiqlash (KNOPKASIZ)
            await message.reply(
                f"✅ <b>Javob yuborildi!</b>\n\n"
                f"📋 Murojaat: <b>#{murojaat_id}</b>\n"
                f"👤 Foydalanuvchi: {murojaat['full_name']}\n"
                f"📞 Telefon: {murojaat['phone']}",
                parse_mode="HTML"
            )
            
            logger.info(f"✅ Javob yuborildi: murojaat_id={murojaat_id}")
            
        except Exception as send_error:
            logger.error(f"❌ Foydalanuvchiga javob yuborishda xatolik: {send_error}")
            await message.reply(
                f"⚠️ Javob saqlandi, lekin foydalanuvchiga yuborishda xatolik!\n"
                f"User ID: <code>{murojaat['user_id']}</code>",
                parse_mode="HTML"
            )
    
    except Exception as e:
        logger.error(f"❌ Admin javob xatolik: {e}")
        import traceback
        traceback.print_exc()
        await message.reply(f"❌ Xatolik: {e}")

# ==================== EXCEL YARATISH ====================
async def create_excel_report():
    """Excel hisobot yaratish"""
    try:
        # Ma'lumotlarni olish
        data = await db.get_all_murojaatlar_with_javoblar()
        stats = await db.get_all_statistics()
        
        if not data:
            logger.warning("⚠️ Ma'lumotlar yo'q")
            return None
        
        # Excel yaratish
        wb = openpyxl.Workbook()
        
        # SHEET 1: Statistika
        ws_stats = wb.active
        ws_stats.title = "Statistika"
        
        # Sarlavha
        ws_stats['A1'] = "MUROJAATLAR STATISTIKASI"
        ws_stats['A1'].font = Font(size=16, bold=True)
        ws_stats['A1'].alignment = Alignment(horizontal='center')
        ws_stats.merge_cells('A1:D1')
        
        # Ma'lumotlar
        row = 3
        ws_stats[f'A{row}'] = "Ko'rsatkich"
        ws_stats[f'B{row}'] = "Qiymat"
        ws_stats[f'A{row}'].font = Font(bold=True)
        ws_stats[f'B{row}'].font = Font(bold=True)
        
        row += 1
        ws_stats[f'A{row}'] = "Jami murojaatlar"
        ws_stats[f'B{row}'] = stats['total']
        
        row += 1
        ws_stats[f'A{row}'] = "Javob berilgan"
        ws_stats[f'B{row}'] = stats['answered']
        
        row += 1
        ws_stats[f'A{row}'] = "Javob kutayotgan"
        ws_stats[f'B{row}'] = stats['pending']
        
        row += 1
        ws_stats[f'A{row}'] = "Bugungi murojaatlar"
        ws_stats[f'B{row}'] = stats['today']
        
        row += 1
        ws_stats[f'A{row}'] = "Oxirgi 7 kun"
        ws_stats[f'B{row}'] = stats['weekly']
        
        # SHEET 2: Murojaatlar
        ws_murojaat = wb.create_sheet("Murojaatlar")
        
        # Sarlavhalar
        headers = ["ID", "F.I.Sh", "Pasport", "Telefon", "Manzil", "Kategoriya", "Murojaat", "Status", "Sana", "Javoblar"]
        for col, header in enumerate(headers, 1):
            cell = ws_murojaat.cell(1, col, header)
            cell.font = Font(bold=True)
            cell.fill = PatternFill(start_color="CCE5FF", end_color="CCE5FF", fill_type="solid")
        
        # Ma'lumotlarni yozish
        for row, item in enumerate(data, 2):
            m = item['murojaat']
            javoblar_text = "\n".join([f"• {j['javob_text'][:50]}..." for j in item['javoblar']]) if item['javoblar'] else "-"
            
            ws_murojaat.cell(row, 1, m['id'])
            ws_murojaat.cell(row, 2, m['full_name'])
            ws_murojaat.cell(row, 3, m['passport'])
            ws_murojaat.cell(row, 4, m['phone'])
            ws_murojaat.cell(row, 5, m['address'])
            ws_murojaat.cell(row, 6, m['category'])
            ws_murojaat.cell(row, 7, m['text'][:100] + "..." if len(m['text']) > 100 else m['text'])
            ws_murojaat.cell(row, 8, m['status'])
            ws_murojaat.cell(row, 9, m['created_at'])
            ws_murojaat.cell(row, 10, javoblar_text)
        
        # Ustunlar kengligini sozlash
        ws_murojaat.column_dimensions['A'].width = 8
        ws_murojaat.column_dimensions['B'].width = 25
        ws_murojaat.column_dimensions['C'].width = 12
        ws_murojaat.column_dimensions['D'].width = 15
        ws_murojaat.column_dimensions['E'].width = 30
        ws_murojaat.column_dimensions['F'].width = 20
        ws_murojaat.column_dimensions['G'].width = 40
        ws_murojaat.column_dimensions['H'].width = 15
        ws_murojaat.column_dimensions['I'].width = 18
        ws_murojaat.column_dimensions['J'].width = 30
        
        # Faylni saqlash
        filename = f"murojaatlar_hisobot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        filepath = os.path.join(MEDIA_PATH, filename)
        
        wb.save(filepath)
        logger.info(f"✅ Excel yaratildi: {filepath}")
        
        return filepath
    
    except Exception as e:
        logger.error(f"❌ Excel yaratishda xatolik: {e}")
        import traceback
        traceback.print_exc()
        return None

# ==================== GURUH STATISTIKA VA EXPORT ====================
@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    """Statistika - FAQAT GURUHDA"""
    if message.chat.id != GROUP_CHAT_ID:
        if message.chat.type == "private":
            await message.answer(
                "❌ Bu komanda faqat admin guruhida ishlaydi!",
                parse_mode="HTML"
            )
        return
    
    try:
        stats = await db.get_all_statistics()
        
        if not stats:
            await message.answer("❌ Statistika topilmadi.")
            return
        
        # Kategoriyalar
        categories_text = ""
        for cat in stats['categories']:
            categories_text += f"   • {cat['category']}: {cat['count']} ta\n"
        
        # Foizlar
        answered_percent = (stats['answered'] / stats['total'] * 100) if stats['total'] > 0 else 0
        pending_percent = (stats['pending'] / stats['total'] * 100) if stats['total'] > 0 else 0
        
        response = (
            "📊 <b>MUROJAATLAR STATISTIKASI</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            
            f"📈 <b>UMUMIY:</b>\n"
            f"   • Jami: <b>{stats['total']} ta</b>\n"
            f"   • Javob berilgan: <b>{stats['answered']} ta</b> ({answered_percent:.1f}%)\n"
            f"   • Kutayotgan: <b>{stats['pending']} ta</b> ({pending_percent:.1f}%)\n\n"
            
            f"📅 <b>DAVR:</b>\n"
            f"   • Bugun: <b>{stats['today']} ta</b>\n"
            f"   • Oxirgi 7 kun: <b>{stats['weekly']} ta</b>\n\n"
            
            f"📂 <b>KATEGORIYALAR:</b>\n"
            f"{categories_text}\n"
            
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🕐 Yangilandi: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        
        await message.answer(response, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"❌ Statistika xatolik: {e}")
        await message.answer(f"❌ Xatolik: {e}")

@dp.message(Command("export"))
async def cmd_export(message: Message):
    """Excel export - FAQAT GURUHDA"""
    if message.chat.id != GROUP_CHAT_ID:
        if message.chat.type == "private":
            await message.answer(
                "❌ Bu komanda faqat admin guruhida ishlaydi!",
                parse_mode="HTML"
            )
        return
    
    try:
        wait_msg = await message.answer("📊 Excel yaratilmoqda...")
        
        excel_path = await create_excel_report()
        
        if not excel_path or not os.path.exists(excel_path):
            await wait_msg.edit_text("❌ Excel yaratishda xatolik.")
            return
        
        # Faylni yuborish
        excel_file = FSInputFile(excel_path)
        await message.answer_document(
            document=excel_file,
            caption=(
                "📊 <b>MUROJAATLAR HISOBOTI</b>\n\n"
                f"📅 Yaratildi: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                f"📁 Fayl: {os.path.basename(excel_path)}"
            ),
            parse_mode="HTML"
        )
        
        await wait_msg.delete()
        logger.info(f"✅ Excel yuborildi: {excel_path}")
        
        # Faylni o'chirish
        try:
            os.remove(excel_path)
        except:
            pass
        
    except Exception as e:
        logger.error(f"❌ Excel export xatolik: {e}")
        await message.answer(f"❌ Xatolik: {e}")

# ==================== ESLATMALAR ====================
class ReminderScheduler:
    """Eslatmalar scheduleri"""
    
    def __init__(self, bot: Bot):
        self.bot = bot
        self.scheduler = AsyncIOScheduler()
    
    def start(self):
        """Schedulerni ishga tushirish"""
        # Har kuni soat 10:00 da
        self.scheduler.add_job(
            self.send_reminders,
            'cron',
            hour=10,
            minute=0
        )
        self.scheduler.start()
        logger.info("✅ Scheduler ishga tushdi")
    
    async def send_reminders(self):
        """Eski murojaatlar uchun eslatma"""
        try:
            old_murojaatlar = await db.get_old_pending_murojaatlar(REMINDER_DAYS)
            
            if not old_murojaatlar:
                logger.info("📭 Eslatma kerak bo'lgan murojaatlar yo'q")
                return
            
            for m in old_murojaatlar:
                try:
                    days_ago = (datetime.now() - datetime.strptime(m['created_at'], '%Y-%m-%d %H:%M:%S')).days
                    
                    await self.bot.send_message(
                        chat_id=GROUP_CHAT_ID,
                        text=(
                            f"⏰ <b>ESLATMA!</b>\n\n"
                            f"📋 Murojaat #{m['id']}\n"
                            f"👤 {m['full_name']}\n"
                            f"📂 {m['category']}\n"
                            f"📅 {days_ago} kun oldin yuborilgan\n\n"
                            f"❗️ Hali javob berilmagan!"
                        ),
                        parse_mode="HTML"
                    )
                    
                    await asyncio.sleep(1)
                    
                except Exception as e:
                    logger.error(f"❌ Eslatma yuborishda xatolik: {e}")
            
            logger.info(f"✅ {len(old_murojaatlar)} ta eslatma yuborildi")
            
        except Exception as e:
            logger.error(f"❌ Eslatmalar xatolik: {e}")

# ==================== MAIN ====================
async def main():
    """Asosiy funksiya"""
    try:
        # Media papka
        os.makedirs(MEDIA_PATH, exist_ok=True)
        logger.info(f"✅ Media papka: {MEDIA_PATH}")
        
        # Database
        await db.init_db()
        logger.info("✅ Database tayyor")
        
        # Scheduler
        scheduler = ReminderScheduler(bot)
        scheduler.start()
        logger.info("✅ Scheduler ishga tushdi")
        
        # Bot
        logger.info("🤖 Bot ishga tushmoqda...")
        logger.info(f"📊 Kunlik limit: {DAILY_LIMIT}")
        logger.info(f"⏰ Eslatma: {REMINDER_DAYS} kun")
        logger.info(f"👥 Guruh ID: {GROUP_CHAT_ID}")
        logger.info("✅ Bot ishga tushdi!")
        
        await dp.start_polling(bot)
        
    except Exception as e:
        logger.error(f"❌ Bot xatolik: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⏹ Bot to'xtatildi")
    except Exception as e:
        logger.error(f"❌ Xatolik: {e}")
