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
# Railway environment variables dan olinadi
BOT_TOKEN = os.getenv("BOT_TOKEN", "8311683221:AAFWy1J5sq-9-_Kdp5qf3c7kMl9upEQoj4k")
GROUP_CHAT_ID = int(os.getenv("GROUP_CHAT_ID", "-1003773765959"))

# Qo'shimcha sozlamalar
DAILY_LIMIT = int(os.getenv("DAILY_LIMIT", "5"))
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
        """Database yaratish va jadvallarni sozlash - MIGRATSIYA QILISH"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # MUHIM: FOREIGN KEY ni o'chirish (XATOLIK TUZATISH)
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
                
                # Murojaatlar jadvali - FOREIGN KEY O'CHIRILDI
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
                
                # Javoblar jadvali - FOREIGN KEY O'CHIRILDI
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
                
                # MIGRATSIYA: barcha kerakli ustunlarni qo'shish
                try:
                    # Barcha ustunlarni tekshirish
                    cursor = await db.execute("PRAGMA table_info(murojaatlar)")
                    columns = await cursor.fetchall()
                    column_names = [col[1] for col in columns]
                    
                    # Kerakli ustunlar ro'yxati
                    required_columns = {
                        'address': 'TEXT',
                        'group_message_id': 'INTEGER',
                        'admin_checked_at': 'DATETIME'
                    }
                    
                    # Har bir ustunni tekshirish va qo'shish
                    for col_name, col_type in required_columns.items():
                        if col_name not in column_names:
                            logger.warning(f"⚠️ '{col_name}' ustuni topilmadi, qo'shilmoqda...")
                            await db.execute(f"ALTER TABLE murojaatlar ADD COLUMN {col_name} {col_type}")
                            await db.commit()
                            logger.info(f"✅ '{col_name}' ustuni muvaffaqiyatli qo'shildi")
                    
                    logger.info("✅ Barcha ustunlar tekshirildi va yangilandi")
                    
                except Exception as migration_error:
                    logger.error(f"❌ Migratsiya xatolik: {migration_error}")
                
                await db.commit()
                logger.info("✅ Database muvaffaqiyatli yaratildi va tekshirildi")
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
        """Murojaat qo'shish - XATOLIK TUZATILDI"""
        try:
            logger.info(f"💾 Murojaat saqlanmoqda: user={user_id}, group_msg={group_message_id}")
            
            # MUHIM: Avval user ni database ga qo'shamiz
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
                    rows = await cursor.fetchall()
                    return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"❌ User murojaatlari olishda xatolik: {e}")
            return []
    
    async def get_murojaat(self, murojaat_id: int):
        """Bitta murojaatni olish"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT * FROM murojaatlar WHERE id = ?",
                    (murojaat_id,)
                ) as cursor:
                    row = await cursor.fetchone()
                    return dict(row) if row else None
        except Exception as e:
            logger.error(f"❌ Murojaat olishda xatolik: {e}")
            return None
    
    async def get_pending_murojaatlar(self):
        """Javob kutayotgan murojaatlar"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT * FROM murojaatlar WHERE status = 'Yangi' ORDER BY created_at ASC"
                ) as cursor:
                    rows = await cursor.fetchall()
                    return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"❌ Pending murojaatlar olishda xatolik: {e}")
            return []
    
    async def add_javob(self, murojaat_id: int, admin_id: int, admin_username: str, javob_text: str):
        """Javob qo'shish"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                # Javobni saqlash
                await db.execute("""
                    INSERT INTO javoblar (murojaat_id, admin_id, admin_username, javob_text)
                    VALUES (?, ?, ?, ?)
                """, (murojaat_id, admin_id, admin_username, javob_text))
                
                # Status yangilash
                await db.execute("""
                    UPDATE murojaatlar 
                    SET status = 'Javob berildi', admin_checked_at = ?
                    WHERE id = ?
                """, (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), murojaat_id))
                
                await db.commit()
                logger.info(f"✅ Javob saqlandi: murojaat={murojaat_id}")
                return True
        except Exception as e:
            logger.error(f"❌ Javob qo'shishda xatolik: {e}")
            return False
    
    async def get_user_today_count(self, user_id: int) -> int:
        """Bugun yuborilgan murojaatlar soni"""
        try:
            today = datetime.now().strftime('%Y-%m-%d')
            async with aiosqlite.connect(self.db_path) as db:
                async with db.execute(
                    "SELECT COUNT(*) FROM murojaatlar WHERE user_id = ? AND DATE(created_at) = ?",
                    (user_id, today)
                ) as cursor:
                    result = await cursor.fetchone()
                    return result[0] if result else 0
        except Exception as e:
            logger.error(f"❌ Bugungi soni olishda xatolik: {e}")
            return 0
    
    async def get_all_statistics(self):
        """To'liq statistika olish"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                
                # Umumiy
                async with db.execute("SELECT COUNT(*) as total FROM murojaatlar") as cursor:
                    total = (await cursor.fetchone())['total']
                
                # Javob berilgan
                async with db.execute(
                    "SELECT COUNT(*) as answered FROM murojaatlar WHERE status = 'Javob berildi'"
                ) as cursor:
                    answered = (await cursor.fetchone())['answered']
                
                # Javob kutayotgan
                async with db.execute(
                    "SELECT COUNT(*) as pending FROM murojaatlar WHERE status = 'Yangi'"
                ) as cursor:
                    pending = (await cursor.fetchone())['pending']
                
                # Bugun
                today = datetime.now().strftime('%Y-%m-%d')
                async with db.execute(
                    "SELECT COUNT(*) as today FROM murojaatlar WHERE DATE(created_at) = ?",
                    (today,)
                ) as cursor:
                    today_count = (await cursor.fetchone())['today']
                
                # Haftalik
                week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
                async with db.execute(
                    "SELECT COUNT(*) as weekly FROM murojaatlar WHERE DATE(created_at) >= ?",
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
                    categories = [dict(row) for row in await cursor.fetchall()]
                
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
        """Barcha murojaatlar va javoblar"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                
                # Murojaatlarni olish
                async with db.execute(
                    "SELECT * FROM murojaatlar ORDER BY created_at DESC"
                ) as cursor:
                    murojaatlar = [dict(row) for row in await cursor.fetchall()]
                
                # Har bir murojaat uchun javoblarni olish
                for m in murojaatlar:
                    async with db.execute(
                        "SELECT * FROM javoblar WHERE murojaat_id = ? ORDER BY created_at DESC",
                        (m['id'],)
                    ) as cursor:
                        m['javoblar'] = [dict(row) for row in await cursor.fetchall()]
                
                return murojaatlar
        except Exception as e:
            logger.error(f"❌ Barcha murojaatlar olishda xatolik: {e}")
            return []

# Database instance
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

# ==================== MENU TUGMALARI ====================
def get_main_menu():
    """Asosiy menu tugmalari - FAQAT SHAXSIY CHATDA"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="✍️ Yangi murojaat"),
                KeyboardButton(text="📋 Mening murojaatlarim")
            ],
            [
                KeyboardButton(text="ℹ️ Yo'riqnoma"),
                KeyboardButton(text="☎️ Aloqa")
            ]
        ],
        resize_keyboard=True
    )
    return keyboard

def get_category_keyboard():
    """Kategoriya tanlash tugmalari"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏥 Sog'liqni saqlash", callback_data="cat_health")],
            [InlineKeyboardButton(text="🏫 Ta'lim", callback_data="cat_education")],
            [InlineKeyboardButton(text="🚧 Kommunal xizmat", callback_data="cat_communal")],
            [InlineKeyboardButton(text="🚗 Transport", callback_data="cat_transport")],
            [InlineKeyboardButton(text="🏛 Boshqa", callback_data="cat_other")],
        ]
    )
    return keyboard

def get_image_skip_keyboard():
    """Rasm yuklashni o'tkazish"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏭ Rasmiz davom etish", callback_data="skip_image")]
        ]
    )
    return keyboard

# ==================== START VA ASOSIY KOMANDALAR ====================
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Start komandasi"""
    await state.clear()
    
    # Faqat shaxsiy chatda menu tugmalari
    if message.chat.type == "private":
        await message.answer(
            f"👋 <b>Assalomu alaykum, {message.from_user.first_name}!</b>\n\n"
            "🤖 Men virtual qabul xonasi botiman.\n"
            "📝 Murojaatingizni yuboring, admin javobi botga keladi.\n\n"
            "💡 <b>Qanday foydalanish:</b>\n"
            "   1. <b>✍️ Yangi murojaat</b> - Ariza yuborish\n"
            "   2. <b>📋 Mening murojaatlarim</b> - Arizalarim holati\n"
            "   3. <b>ℹ️ Yo'riqnoma</b> - Batafsil ma'lumot\n\n"
            "✅ Boshlash uchun quyidagi tugmalardan foydalaning!",
            parse_mode="HTML",
            reply_markup=get_main_menu()
        )
    else:
        # Guruhda menu tugmalarisiz
        await message.answer(
            "👋 <b>Assalomu alaykum!</b>\n\n"
            "🤖 Men virtual qabul xonasi botiman.\n"
            "📊 Guruhda statistika ko'rish uchun: /stats\n"
            "📥 Excel yuklash uchun: /export",
            parse_mode="HTML"
        )

@dp.message(F.text == "ℹ️ Yo'riqnoma")
async def yoriqnoma(message: Message):
    """Yo'riqnoma - faqat shaxsiy chatda"""
    if message.chat.type != "private":
        return
    
    await message.answer(
        "📖 <b>FOYDALANISH YO'RIQNOMASI</b>\n\n"
        
        "<b>1️⃣ MUROJAAT YUBORISH:</b>\n"
        "   • <b>✍️ Yangi murojaat</b> tugmasini bosing\n"
        "   • F.I.Sh, pasport, telefon, manzil kiriting\n"
        "   • Kategoriya tanlang\n"
        "   • Muammo tavsifini yozing\n"
        "   • (Ixtiyoriy) Rasm yuklang\n\n"
        
        "<b>2️⃣ MUROJAATLAR HOLATI:</b>\n"
        "   • <b>📋 Mening murojaatlarim</b> tugmasi\n"
        "   • Barcha arizalar va javoblar\n\n"
        
        "<b>3️⃣ CHEKLOVLAR:</b>\n"
        f"   • Kunlik limit: <b>{DAILY_LIMIT} ta murojaat</b>\n"
        f"   • Eslatma: <b>{REMINDER_DAYS} kundan keyin</b>\n\n"
        
        "<b>4️⃣ QOIDALAR:</b>\n"
        "   ✅ Haqiqiy ma'lumotlar kiriting\n"
        "   ✅ Aniq va tushunarli yozing\n"
        "   ✅ Tegishli kategoriyani tanlang\n"
        "   ❌ Yolg'on ma'lumot bermang\n\n"
        
        "💬 Savol bo'lsa: <b>☎️ Aloqa</b> tugmasi!",
        parse_mode="HTML"
    )

@dp.message(F.text == "☎️ Aloqa")
async def aloqa(message: Message):
    """Aloqa ma'lumotlari - faqat shaxsiy chatda"""
    if message.chat.type != "private":
        return
    
    await message.answer(
        "📞 <b>ALOQA MA'LUMOTLARI</b>\n\n"
        
        "🏢 <b>Tashkilot nomi:</b>\n"
        "   Virtual qabul xonasi\n\n"
        
        "📍 <b>Manzil:</b>\n"
        "   Toshkent shahar\n\n"
        
        "📱 <b>Telefon:</b>\n"
        "   +998 XX XXX-XX-XX\n\n"
        
        "📧 <b>Email:</b>\n"
        "   info@example.uz\n\n"
        
        "🕐 <b>Ish vaqti:</b>\n"
        "   Dushanba-Juma: 09:00-18:00\n\n"
        
        "💻 <b>Website:</b>\n"
        "   www.example.uz\n\n"
        
        "❓ <b>Savol-javob uchun botga yozing!</b>",
        parse_mode="HTML"
    )

# ==================== YANGI MUROJAAT ====================
@dp.message(F.text == "✍️ Yangi murojaat")
async def start_murojaat(message: Message, state: FSMContext):
    """Yangi murojaat boshlash - faqat shaxsiy chatda"""
    if message.chat.type != "private":
        return
    
    # Kunlik limit tekshirish
    today_count = await db.get_user_today_count(message.from_user.id)
    if today_count >= DAILY_LIMIT:
        await message.answer(
            f"⚠️ <b>Kunlik limit tugadi!</b>\n\n"
            f"📊 Siz bugun <b>{today_count}/{DAILY_LIMIT}</b> ta murojaat yubordingiz.\n"
            f"⏰ Ertaga yana urinib ko'ring!",
            parse_mode="HTML"
        )
        return
    
    await state.set_state(MurojaatStates.waiting_for_full_name)
    await message.answer(
        "✍️ <b>YANGI MUROJAAT</b>\n\n"
        "📝 Iltimos, to'liq F.I.Sh ni kiriting:\n"
        "   <i>Masalan: Aliyev Vali Akbarovich</i>",
        parse_mode="HTML",
        reply_markup=types.ReplyKeyboardRemove()
    )

@dp.message(MurojaatStates.waiting_for_full_name)
async def process_full_name(message: Message, state: FSMContext):
    """F.I.Sh qabul qilish"""
    full_name = message.text.strip()
    
    if not validate_full_name(full_name):
        await message.answer(
            "❌ <b>Noto'g'ri F.I.Sh!</b>\n\n"
            "📝 Iltimos, to'liq F.I.Sh ni kiriting:\n"
            "   • Kamida 2 ta so'z\n"
            "   • Raqamsiz\n"
            "   <i>Masalan: Aliyev Vali Akbarovich</i>",
            parse_mode="HTML"
        )
        return
    
    await state.update_data(full_name=full_name)
    await state.set_state(MurojaatStates.waiting_for_passport)
    
    await message.answer(
        "✅ <b>F.I.Sh qabul qilindi!</b>\n\n"
        "🛂 Endi pasport seriya va raqamini kiriting:\n"
        "   <i>Masalan: AA1234567</i>",
        parse_mode="HTML"
    )

@dp.message(MurojaatStates.waiting_for_passport)
async def process_passport(message: Message, state: FSMContext):
    """Pasport qabul qilish"""
    passport = message.text.strip().upper()
    
    if not validate_passport(passport):
        await message.answer(
            "❌ <b>Noto'g'ri pasport!</b>\n\n"
            "🛂 Iltimos, pasport seriya va raqamini kiriting:\n"
            "   • Format: AA1234567\n"
            "   • 2 ta harf + 7 ta raqam\n"
            "   <i>Masalan: AA1234567</i>",
            parse_mode="HTML"
        )
        return
    
    await state.update_data(passport=passport)
    await state.set_state(MurojaatStates.waiting_for_phone)
    
    await message.answer(
        "✅ <b>Pasport qabul qilindi!</b>\n\n"
        "📱 Endi telefon raqamini kiriting:\n"
        "   <i>Masalan: +998901234567</i>",
        parse_mode="HTML"
    )

@dp.message(MurojaatStates.waiting_for_phone)
async def process_phone(message: Message, state: FSMContext):
    """Telefon qabul qilish"""
    phone = message.text.strip()
    
    if not validate_phone(phone):
        await message.answer(
            "❌ <b>Noto'g'ri telefon!</b>\n\n"
            "📱 Iltimos, telefon raqamini kiriting:\n"
            "   • Format: +998XXXXXXXXX\n"
            "   • Yoki: 998XXXXXXXXX\n"
            "   <i>Masalan: +998901234567</i>",
            parse_mode="HTML"
        )
        return
    
    await state.update_data(phone=phone)
    await state.set_state(MurojaatStates.waiting_for_address)
    
    await message.answer(
        "✅ <b>Telefon qabul qilindi!</b>\n\n"
        "📍 Endi yashash manzilingizni kiriting:\n"
        "   <i>Masalan: Toshkent sh., Yunusobod t., Abdulla Qodiriy ko'chasi 123-uy</i>",
        parse_mode="HTML"
    )

@dp.message(MurojaatStates.waiting_for_address)
async def process_address(message: Message, state: FSMContext):
    """Manzil qabul qilish"""
    address = message.text.strip()
    
    if len(address) < 10:
        await message.answer(
            "❌ <b>Manzil juda qisqa!</b>\n\n"
            "📍 Iltimos, to'liq manzilni kiriting:\n"
            "   <i>Masalan: Toshkent sh., Yunusobod t., Abdulla Qodiriy ko'chasi 123-uy</i>",
            parse_mode="HTML"
        )
        return
    
    await state.update_data(address=address)
    await state.set_state(MurojaatStates.waiting_for_category)
    
    await message.answer(
        "✅ <b>Manzil qabul qilindi!</b>\n\n"
        "📂 Endi murojaat kategoriyasini tanlang:",
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
    
    await callback.message.edit_text(
        f"✅ <b>Kategoriya tanlandi: {category}</b>\n\n"
        "📝 Endi muammongizni batafsil yozing:",
        parse_mode="HTML"
    )

@dp.message(MurojaatStates.waiting_for_text)
async def process_text(message: Message, state: FSMContext):
    """Matn qabul qilish"""
    text = message.text.strip()
    
    if len(text) < 10:
        await message.answer(
            "❌ <b>Matn juda qisqa!</b>\n\n"
            "📝 Iltimos, muammongizni batafsil yozing (kamida 10 ta belgi):",
            parse_mode="HTML"
        )
        return
    
    await state.update_data(text=text)
    await state.set_state(MurojaatStates.waiting_for_image)
    
    await message.answer(
        "✅ <b>Matn qabul qilindi!</b>\n\n"
        "📸 Agar rasm yoki hujjat yuklashni xohlasangiz, yuboring.\n"
        "⏭ Aks holda, <b>rasmiz davom etish</b> tugmasini bosing.",
        parse_mode="HTML",
        reply_markup=get_image_skip_keyboard()
    )

@dp.message(MurojaatStates.waiting_for_image, F.photo)
async def process_image(message: Message, state: FSMContext):
    """Rasm qabul qilish"""
    try:
        # Rasmni saqlash
        photo = message.photo[-1]
        photo_path = os.path.join(MEDIA_PATH, f"{message.from_user.id}_{datetime.now().timestamp()}.jpg")
        await bot.download(photo, destination=photo_path)
        
        await state.update_data(image_path=photo_path)
        await finish_murojaat(message, state)
        
    except Exception as e:
        logger.error(f"❌ Rasm saqlashda xatolik: {e}")
        await message.answer("❌ Rasm saqlashda xatolik yuz berdi. Qaytadan yuboring yoki o'tkazing.")

@dp.callback_query(F.data == "skip_image")
async def skip_image(callback: CallbackQuery, state: FSMContext):
    """Rasmni o'tkazish"""
    await state.update_data(image_path=None)
    await callback.message.delete()
    await finish_murojaat(callback.message, state)

async def finish_murojaat(message: Message, state: FSMContext):
    """Murojaatni yakunlash va yuborish"""
    try:
        data = await state.get_data()
        user_id = message.from_user.id
        
        # Database ga saqlash
        murojaat_id = await db.add_murojaat(
            user_id=user_id,
            full_name=data['full_name'],
            passport=data['passport'],
            phone=data['phone'],
            address=data['address'],
            category=data['category'],
            text=data['text'],
            image_path=data.get('image_path')
        )
        
        if not murojaat_id:
            await message.answer("❌ Murojaatni saqlashda xatolik yuz berdi!")
            await state.clear()
            return
        
        # Guruhga yuborish
        group_text = (
            f"📩 <b>YANGI MUROJAAT #{murojaat_id}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 <b>F.I.Sh:</b> {data['full_name']}\n"
            f"🛂 <b>Pasport:</b> {data['passport']}\n"
            f"📱 <b>Telefon:</b> {data['phone']}\n"
            f"📍 <b>Manzil:</b> {data['address']}\n"
            f"📂 <b>Kategoriya:</b> {data['category']}\n\n"
            f"📝 <b>MUROJAAT MATNI:</b>\n{data['text']}\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n"
            f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        )
        
        # Javob tugmasi
        reply_keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="✅ Javob berish", callback_data=f"reply_{murojaat_id}")]
            ]
        )
        
        # Rasm bilan yoki rasmiz yuborish
        if data.get('image_path') and os.path.exists(data['image_path']):
            group_msg = await bot.send_photo(
                chat_id=GROUP_CHAT_ID,
                photo=FSInputFile(data['image_path']),
                caption=group_text,
                parse_mode="HTML",
                reply_markup=reply_keyboard
            )
        else:
            group_msg = await bot.send_message(
                chat_id=GROUP_CHAT_ID,
                text=group_text,
                parse_mode="HTML",
                reply_markup=reply_keyboard
            )
        
        # Group message ID ni saqlash
        async with aiosqlite.connect(DB_PATH) as db_conn:
            await db_conn.execute(
                "UPDATE murojaatlar SET group_message_id = ? WHERE id = ?",
                (group_msg.message_id, murojaat_id)
            )
            await db_conn.commit()
        
        # Foydalanuvchiga xabar
        await message.answer(
            f"✅ <b>MUROJAAT YUBORILDI!</b>\n\n"
            f"📋 Murojaat raqami: <b>#{murojaat_id}</b>\n"
            f"📂 Kategoriya: {data['category']}\n"
            f"📅 Sana: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
            f"⏰ Tez orada javob qaytariladi!\n"
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
            "❌ Murojaatni yuborishda xatolik yuz berdi!\n"
            "Iltimos, qaytadan urinib ko'ring.",
            reply_markup=get_main_menu()
        )
        await state.clear()

# ==================== MENING MUROJAATLARIM ====================
@dp.message(F.text == "📋 Mening murojaatlarim")
async def my_murojaatlar(message: Message):
    """Foydalanuvchi murojaatlari - faqat shaxsiy chatda"""
    if message.chat.type != "private":
        return
    
    try:
        murojaatlar = await db.get_user_murojaatlar(message.from_user.id)
        
        if not murojaatlar:
            await message.answer(
                "📭 <b>Sizda hali murojaatlar yo'q!</b>\n\n"
                "✍️ Yangi murojaat yuborish uchun\n"
                "<b>✍️ Yangi murojaat</b> tugmasini bosing.",
                parse_mode="HTML"
            )
            return
        
        response = f"📋 <b>SIZNING MUROJAATLARINGIZ</b>\n\n"
        response += f"📊 Jami: <b>{len(murojaatlar)} ta</b>\n\n"
        
        for m in murojaatlar[:10]:  # Oxirgi 10 ta
            status_emoji = "✅" if m['status'] == "Javob berildi" else "⏳"
            response += (
                f"{status_emoji} <b>#{m['id']}</b> - {m['category']}\n"
                f"📅 {m['created_at'][:16]}\n"
                f"📊 Status: {m['status']}\n"
            )
            
            # Javobni ko'rsatish
            if m['status'] == "Javob berildi":
                # Javobni olish
                async with aiosqlite.connect(DB_PATH) as db_conn:
                    db_conn.row_factory = aiosqlite.Row
                    async with db_conn.execute(
                        "SELECT * FROM javoblar WHERE murojaat_id = ? ORDER BY created_at DESC LIMIT 1",
                        (m['id'],)
                    ) as cursor:
                        javob = await cursor.fetchone()
                        if javob:
                            javob = dict(javob)
                            response += f"💬 Javob: {javob['javob_text'][:100]}...\n"
            
            response += "\n"
        
        if len(murojaatlar) > 10:
            response += f"<i>... va yana {len(murojaatlar) - 10} ta murojaat</i>"
        
        await message.answer(response, parse_mode="HTML")
        
    except Exception as e:
        logger.error(f"❌ Murojaatlar olishda xatolik: {e}")
        await message.answer("❌ Xatolik yuz berdi!")

# ==================== ADMIN JAVOB BERISH ====================
@dp.callback_query(F.data.startswith("reply_"))
async def admin_reply_button(callback: CallbackQuery):
    """Admin javob berish tugmasi - FAQAT GURUHDA"""
    if callback.message.chat.id != GROUP_CHAT_ID:
        await callback.answer("❌ Bu funksiya faqat guruhda ishlaydi!", show_alert=True)
        return
    
    murojaat_id = int(callback.data.split("_")[1])
    
    await callback.answer(
        f"💬 Javob berish uchun:\n/javob {murojaat_id} <matn>\n\n"
        f"Masalan:\n/javob {murojaat_id} Murojaatingiz ko'rib chiqilmoqda...",
        show_alert=True
    )

@dp.message(Command("javob"))
async def admin_reply_command(message: Message):
    """Admin javob berish komandasi - FAQAT GURUHDA"""
    if message.chat.id != GROUP_CHAT_ID:
        return
    
    try:
        # Komandani parse qilish: /javob 123 Javob matni
        parts = message.text.split(maxsplit=2)
        if len(parts) < 3:
            await message.reply(
                "❌ Noto'g'ri format!\n\n"
                "✅ To'g'ri format:\n"
                "/javob <id> <javob_matni>\n\n"
                "Masalan:\n"
                "/javob 123 Murojaatingiz qabul qilindi..."
            )
            return
        
        murojaat_id = int(parts[1])
        javob_text = parts[2]
        
        # Murojaatni olish
        murojaat = await db.get_murojaat(murojaat_id)
        if not murojaat:
            await message.reply("❌ Murojaat topilmadi!")
            return
        
        # Javobni saqlash
        admin_id = message.from_user.id
        admin_username = message.from_user.username or message.from_user.first_name
        
        success = await db.add_javob(murojaat_id, admin_id, admin_username, javob_text)
        
        if not success:
            await message.reply("❌ Javob saqlashda xatolik!")
            return
        
        # Foydalanuvchiga xabar yuborish
        try:
            await bot.send_message(
                chat_id=murojaat['user_id'],
                text=(
                    f"📬 <b>MUROJAATINGIZGA JAVOB</b>\n"
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
            
            # Guruhda tasdiqlash
            await message.reply(
                f"✅ <b>Javob yuborildi!</b>\n\n"
                f"📋 Murojaat: #{murojaat_id}\n"
                f"👤 Foydalanuvchi: {murojaat['full_name']}\n"
                f"💬 Javob: {javob_text[:100]}...",
                parse_mode="HTML"
            )
            
            logger.info(f"✅ Javob yuborildi: #{murojaat_id} by {admin_username}")
            
        except Exception as e:
            logger.error(f"❌ Foydalanuvchiga javob yuborishda xatolik: {e}")
            await message.reply(
                "⚠️ Javob saqlandi, lekin foydalanuvchiga yuborishda xatolik!\n"
                "Foydalanuvchi botni bloklagan bo'lishi mumkin."
            )
    
    except ValueError:
        await message.reply("❌ Murojaat ID raqam bo'lishi kerak!")
    except Exception as e:
        logger.error(f"❌ Javob berishda xatolik: {e}")
        await message.reply(f"❌ Xatolik: {e}")

# ==================== ESLATMALAR ====================
class ReminderScheduler:
    """Eslatmalar uchun scheduler"""
    
    def __init__(self, bot: Bot):
        self.bot = bot
        self.scheduler = AsyncIOScheduler()
    
    def start(self):
        """Scheduler ni ishga tushirish"""
        # Har kuni soat 10:00 da eslatma
        self.scheduler.add_job(
            self.send_reminders,
            'cron',
            hour=10,
            minute=0
        )
        self.scheduler.start()
        logger.info("✅ Reminder scheduler started")
    
    async def send_reminders(self):
        """Eslatmalar yuborish"""
        try:
            pending = await db.get_pending_murojaatlar()
            reminder_date = datetime.now() - timedelta(days=REMINDER_DAYS)
            
            old_pending = [
                m for m in pending 
                if datetime.strptime(m['created_at'], '%Y-%m-%d %H:%M:%S') < reminder_date
            ]
            
            if old_pending:
                reminder_text = (
                    f"⏰ <b>ESLATMA!</b>\n\n"
                    f"📊 {len(old_pending)} ta murojaat {REMINDER_DAYS} kundan ortiq javob kutmoqda:\n\n"
                )
                
                for m in old_pending[:5]:
                    days_ago = (datetime.now() - datetime.strptime(m['created_at'], '%Y-%m-%d %H:%M:%S')).days
                    reminder_text += (
                        f"📋 #{m['id']} - {m['category']}\n"
                        f"📅 {days_ago} kun oldin\n\n"
                    )
                
                await self.bot.send_message(
                    chat_id=GROUP_CHAT_ID,
                    text=reminder_text,
                    parse_mode="HTML"
                )
                
                logger.info(f"✅ Eslatma yuborildi: {len(old_pending)} ta murojaat")
        
        except Exception as e:
            logger.error(f"❌ Eslatma yuborishda xatolik: {e}")

# ==================== EXCEL REPORT ====================
async def create_excel_report():
    """Excel hisobot yaratish - GRAFIKLAR BILAN"""
    try:
        # Ma'lumotlarni olish
        murojaatlar = await db.get_all_murojaatlar_with_javoblar()
        stats = await db.get_all_statistics()
        
        if not murojaatlar:
            return None
        
        # Workbook yaratish
        wb = openpyxl.Workbook()
        wb.remove(wb.active)  # Default sheetni o'chirish
        
        # ===== 1. UMUMIY STATISTIKA SHEET =====
        ws_stats = wb.create_sheet("📊 Statistika")
        
        # Sarlavha
        ws_stats['A1'] = "MUROJAATLAR STATISTIKASI"
        ws_stats['A1'].font = Font(size=16, bold=True)
        ws_stats.merge_cells('A1:D1')
        
        # Umumiy ma'lumotlar
        ws_stats['A3'] = "Ko'rsatkich"
        ws_stats['B3'] = "Qiymat"
        ws_stats['A3'].font = Font(bold=True)
        ws_stats['B3'].font = Font(bold=True)
        
        stats_data = [
            ["Jami murojaatlar", stats['total']],
            ["Javob berilgan", stats['answered']],
            ["Javob kutayotgan", stats['pending']],
            ["Bugungi murojaatlar", stats['today']],
            ["Haftalik murojaatlar", stats['weekly']],
        ]
        
        for idx, (name, value) in enumerate(stats_data, start=4):
            ws_stats[f'A{idx}'] = name
            ws_stats[f'B{idx}'] = value
        
        # Kategoriyalar
        ws_stats['A10'] = "KATEGORIYALAR BO'YICHA"
        ws_stats['A10'].font = Font(size=14, bold=True)
        ws_stats.merge_cells('A10:B10')
        
        ws_stats['A11'] = "Kategoriya"
        ws_stats['B11'] = "Soni"
        ws_stats['A11'].font = Font(bold=True)
        ws_stats['B11'].font = Font(bold=True)
        
        cat_start_row = 12
        for idx, cat in enumerate(stats['categories'], start=cat_start_row):
            ws_stats[f'A{idx}'] = cat['category']
            ws_stats[f'B{idx}'] = cat['count']
        
        # GRAFIK 1: Kategoriyalar bo'yicha Pie Chart
        pie_chart = PieChart()
        pie_chart.title = "Kategoriyalar bo'yicha taqsimot"
        pie_chart.height = 10
        pie_chart.width = 15
        
        cat_labels = Reference(ws_stats, min_col=1, min_row=cat_start_row, max_row=cat_start_row + len(stats['categories']) - 1)
        cat_data = Reference(ws_stats, min_col=2, min_row=cat_start_row, max_row=cat_start_row + len(stats['categories']) - 1)
        pie_chart.add_data(cat_data)
        pie_chart.set_categories(cat_labels)
        
        ws_stats.add_chart(pie_chart, "D3")
        
        # GRAFIK 2: Status bo'yicha Bar Chart
        ws_stats['A20'] = "STATUS BO'YICHA"
        ws_stats['A20'].font = Font(size=14, bold=True)
        
        ws_stats['A21'] = "Status"
        ws_stats['B21'] = "Soni"
        ws_stats['A21'].font = Font(bold=True)
        ws_stats['B21'].font = Font(bold=True)
        
        ws_stats['A22'] = "Javob berilgan"
        ws_stats['B22'] = stats['answered']
        ws_stats['A23'] = "Javob kutayotgan"
        ws_stats['B23'] = stats['pending']
        
        bar_chart = BarChart()
        bar_chart.title = "Murojaatlar statusi"
        bar_chart.height = 10
        bar_chart.width = 15
        
        status_labels = Reference(ws_stats, min_col=1, min_row=22, max_row=23)
        status_data = Reference(ws_stats, min_col=2, min_row=22, max_row=23)
        bar_chart.add_data(status_data)
        bar_chart.set_categories(status_labels)
        
        ws_stats.add_chart(bar_chart, "D20")
        
        # Ustunlar kengligini sozlash
        ws_stats.column_dimensions['A'].width = 30
        ws_stats.column_dimensions['B'].width = 15
        
        # ===== 2. BATAFSIL MUROJAATLAR SHEET =====
        ws_detail = wb.create_sheet("📋 Murojaatlar")
        
        # Sarlavha
        headers = ["ID", "F.I.Sh", "Pasport", "Telefon", "Manzil", "Kategoriya", "Murojaat matni", "Status", "Sana", "Javob", "Javob sanasi"]
        ws_detail.append(headers)
        
        # Header formatini sozlash
        for cell in ws_detail[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
            cell.alignment = Alignment(horizontal="center", vertical="center")
        
        # Ma'lumotlarni qo'shish
        for m in murojaatlar:
            javob_text = ""
            javob_date = ""
            
            if m['javoblar']:
                javob_text = m['javoblar'][0]['javob_text']
                javob_date = m['javoblar'][0]['created_at']
            
            ws_detail.append([
                m['id'],
                m['full_name'],
                m['passport'],
                m['phone'],
                m['address'],
                m['category'],
                m['text'],
                m['status'],
                m['created_at'],
                javob_text,
                javob_date
            ])
        
        # Ustunlar kengligini avtomatik sozlash
        for column in ws_detail.columns:
            max_length = 0
            column_letter = get_column_letter(column[0].column)
            
            for cell in column:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            
            adjusted_width = min(max_length + 2, 50)
            ws_detail.column_dimensions[column_letter].width = adjusted_width
        
        # Faylni saqlash
        filename = f"murojaatlar_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
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
    """Statistika ko'rish - FAQAT GURUHDA ISHLAYDI"""
    # Faqat guruhda ishlaydi
    if message.chat.id != GROUP_CHAT_ID:
        # Shaxsiy chatda javob bermaydi
        if message.chat.type == "private":
            await message.answer(
                "❌ Bu komanda faqat admin guruhida ishlaydi!",
                parse_mode="HTML"
            )
        return
    
    try:
        stats = await db.get_all_statistics()
        
        if not stats:
            await message.answer("❌ Statistika ma'lumotlari topilmadi.")
            return
        
        # Kategoriyalar statistikasi
        categories_text = ""
        for cat in stats['categories']:
            categories_text += f"   • {cat['category']}: {cat['count']} ta\n"
        
        # Foiz hisoblash
        answered_percent = (stats['answered'] / stats['total'] * 100) if stats['total'] > 0 else 0
        pending_percent = (stats['pending'] / stats['total'] * 100) if stats['total'] > 0 else 0
        
        response = (
            "📊 <b>MUROJAATLAR STATISTIKASI</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            
            f"📈 <b>UMUMIY MA'LUMOTLAR:</b>\n"
            f"   • Jami murojaatlar: <b>{stats['total']} ta</b>\n"
            f"   • Javob berilgan: <b>{stats['answered']} ta</b> ({answered_percent:.1f}%)\n"
            f"   • Javob kutayotgan: <b>{stats['pending']} ta</b> ({pending_percent:.1f}%)\n\n"
            
            f"📅 <b>DAVR BO'YICHA:</b>\n"
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
        import traceback
        traceback.print_exc()
        await message.answer(f"❌ Xatolik: {e}")

@dp.message(Command("export"))
async def cmd_export(message: Message):
    """Excel export - FAQAT GURUHDA ISHLAYDI"""
    # Faqat guruhda ishlaydi
    if message.chat.id != GROUP_CHAT_ID:
        # Shaxsiy chatda javob bermaydi
        if message.chat.type == "private":
            await message.answer(
                "❌ Bu komanda faqat admin guruhida ishlaydi!",
                parse_mode="HTML"
            )
        return
    
    try:
        # Kutish xabari
        wait_msg = await message.answer("📊 Excel fayl yaratilmoqda, iltimos kuting...")
        
        # Excel faylni yaratish
        excel_path = await create_excel_report()
        
        if not excel_path or not os.path.exists(excel_path):
            await wait_msg.edit_text("❌ Excel yaratishda xatolik yuz berdi.")
            return
        
        # Faylni yuborish
        excel_file = FSInputFile(excel_path)
        await message.answer_document(
            document=excel_file,
            caption=(
                "📊 <b>MUROJAATLAR TO'LIQ HISOBOTI</b>\n\n"
                f"📅 Yaratildi: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                f"📁 Fayl: {os.path.basename(excel_path)}\n\n"
                "📈 <b>Faylda:</b>\n"
                "   • To'liq statistika\n"
                "   • Grafiklar (Pie Chart, Bar Chart)\n"
                "   • Barcha murojaatlar va javoblar\n"
                "   • Kategoriyalar bo'yicha taqsimot\n\n"
                "<i>Excelni ochib, statistika va grafiklarni ko'ring!</i>"
            ),
            parse_mode="HTML"
        )
        
        # Kutish xabarini o'chirish
        await wait_msg.delete()
        
        logger.info(f"✅ Excel fayl yuborildi: {excel_path}")
        
        # Faylni o'chirish
        try:
            os.remove(excel_path)
            logger.info(f"🗑 Fayl o'chirildi: {excel_path}")
        except:
            pass
        
    except Exception as e:
        logger.error(f"❌ Excel export xatolik: {e}")
        import traceback
        traceback.print_exc()
        await message.answer(f"❌ Xatolik: {e}")

@dp.message(Command("debug"))
async def cmd_debug(message: Message):
    """Debug - oxirgi murojaatlarni ko'rish"""
    try:
        async with aiosqlite.connect(DB_PATH) as db_conn:
            db_conn.row_factory = aiosqlite.Row
            async with db_conn.execute(
                "SELECT id, user_id, full_name, group_message_id, status, created_at FROM murojaatlar ORDER BY id DESC LIMIT 5"
            ) as cursor:
                rows = await cursor.fetchall()
        
        if not rows:
            await message.answer("📭 Database bo'sh!")
            return
        
        response = "🔍 <b>OXIRGI 5 TA MUROJAAT:</b>\n\n"
        for r in rows:
            response += (
                f"📋 ID: {r['id']}\n"
                f"👤 User: {r['user_id']}\n"
                f"📛 Ism: {r['full_name']}\n"
                f"💬 Group Msg ID: {r['group_message_id']}\n"
                f"📊 Status: {r['status']}\n"
                f"📅 {r['created_at'][:16]}\n"
                f"━━━━━━━━━━\n"
            )
        
        await message.answer(response, parse_mode="HTML")
    
    except Exception as e:
        await message.answer(f"❌ Xatolik: {e}")
        import traceback
        traceback.print_exc()

# ==================== MAIN ====================
async def main():
    """Asosiy funksiya - BARCHA XATOLAR TUZATILDI"""
    try:
        # Media papkasini yaratish
        os.makedirs(MEDIA_PATH, exist_ok=True)
        logger.info(f"✅ Media papka yaratildi: {MEDIA_PATH}")
        
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
        logger.error(f"❌ Bot ishga tushishda xatolik: {e}")
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
        import traceback
        traceback.print_exc()
