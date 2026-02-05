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
            logger.error(f"Murojaatlarni olishda xatolik: {e}")
            return []
    
    async def get_murojaat_by_id(self, murojaat_id: int):
        """ID bo'yicha murojaat olish"""
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
            logger.error(f"Murojaat olishda xatolik: {e}")
            return None
    
    async def get_murojaat_by_group_msg(self, group_message_id: int):
        """Guruh xabari ID bo'yicha murojaat topish"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT * FROM murojaatlar WHERE group_message_id = ?",
                    (group_message_id,)
                ) as cursor:
                    row = await cursor.fetchone()
                    return dict(row) if row else None
        except Exception as e:
            logger.error(f"Murojaat topishda xatolik: {e}")
            return None
    
    async def add_javob(self, murojaat_id: int, admin_id: int, admin_username: str, javob_text: str):
        """Javob qo'shish"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute("""
                    INSERT INTO javoblar (murojaat_id, admin_id, admin_username, javob_text)
                    VALUES (?, ?, ?, ?)
                """, (murojaat_id, admin_id, admin_username, javob_text))
                await db.commit()
                logger.info(f"✅ Javob saqlandi: murojaat #{murojaat_id}")
        except Exception as e:
            logger.error(f"❌ Javob qo'shishda xatolik: {e}")
    
    async def get_javob(self, murojaat_id: int):
        """Murojaat javobini olish"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT * FROM javoblar WHERE murojaat_id = ? ORDER BY created_at DESC LIMIT 1",
                    (murojaat_id,)
                ) as cursor:
                    row = await cursor.fetchone()
                    return dict(row) if row else None
        except Exception as e:
            logger.error(f"Javob olishda xatolik: {e}")
            return None
    
    async def update_status(self, murojaat_id: int, status: str):
        """Murojaat statusini yangilash"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    "UPDATE murojaatlar SET status = ?, admin_checked_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (status, murojaat_id)
                )
                await db.commit()
                logger.info(f"✅ Status yangilandi: #{murojaat_id} -> {status}")
        except Exception as e:
            logger.error(f"❌ Status yangilashda xatolik: {e}")
    
    async def get_daily_count(self, user_id: int):
        """Bugungi murojaatlar soni"""
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
            logger.error(f"Kunlik soni olishda xatolik: {e}")
            return 0
    
    async def get_pending_murojaatlar(self):
        """Javob kutayotgan murojaatlar"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT * FROM murojaatlar WHERE status != 'Javob berildi' ORDER BY created_at ASC"
                ) as cursor:
                    rows = await cursor.fetchall()
                    return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Pending murojaatlarni olishda xatolik: {e}")
            return []
    
    async def get_old_murojaatlar(self, days: int):
        """Eski murojaatlar (eslatma uchun)"""
        try:
            cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d %H:%M:%S')
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute(
                    "SELECT * FROM murojaatlar WHERE status != 'Javob berildi' AND created_at < ?",
                    (cutoff,)
                ) as cursor:
                    rows = await cursor.fetchall()
                    return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Eski murojaatlarni olishda xatolik: {e}")
            return []
    
    async def get_all_statistics(self):
        """Umumiy statistika ma'lumotlari"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                
                # Umumiy murojaatlar soni
                cursor = await db.execute("SELECT COUNT(*) as total FROM murojaatlar")
                total = (await cursor.fetchone())['total']
                
                # Javob berilganlar
                cursor = await db.execute("SELECT COUNT(*) as answered FROM murojaatlar WHERE status = 'Javob berildi'")
                answered = (await cursor.fetchone())['answered']
                
                # Javob kutayotganlar
                cursor = await db.execute("SELECT COUNT(*) as pending FROM murojaatlar WHERE status != 'Javob berildi'")
                pending = (await cursor.fetchone())['pending']
                
                # Kategoriya bo'yicha
                cursor = await db.execute("""
                    SELECT category, COUNT(*) as count 
                    FROM murojaatlar 
                    GROUP BY category 
                    ORDER BY count DESC
                """)
                categories = await cursor.fetchall()
                
                # Bugungi murojaatlar
                today = datetime.now().strftime('%Y-%m-%d')
                cursor = await db.execute(
                    "SELECT COUNT(*) as today FROM murojaatlar WHERE DATE(created_at) = ?",
                    (today,)
                )
                today_count = (await cursor.fetchone())['today']
                
                # Haftalik murojaatlar
                week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
                cursor = await db.execute(
                    "SELECT COUNT(*) as weekly FROM murojaatlar WHERE DATE(created_at) >= ?",
                    (week_ago,)
                )
                weekly_count = (await cursor.fetchone())['weekly']
                
                return {
                    'total': total,
                    'answered': answered,
                    'pending': pending,
                    'categories': [dict(row) for row in categories],
                    'today': today_count,
                    'weekly': weekly_count
                }
        except Exception as e:
            logger.error(f"Statistika olishda xatolik: {e}")
            return None
    
    async def get_all_murojaatlar_for_export(self):
        """Barcha murojaatlarni export uchun olish"""
        try:
            async with aiosqlite.connect(self.db_path) as db:
                db.row_factory = aiosqlite.Row
                async with db.execute("""
                    SELECT m.*, j.javob_text, j.admin_username, j.created_at as javob_date
                    FROM murojaatlar m
                    LEFT JOIN javoblar j ON m.id = j.murojaat_id
                    ORDER BY m.created_at DESC
                """) as cursor:
                    rows = await cursor.fetchall()
                    return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Export uchun ma'lumot olishda xatolik: {e}")
            return []

# Database instance
db = Database()

# ==================== EXCEL EXPORT FUNKSIYASI ====================
async def create_excel_report():
    """Murojaatlar statistikasini Excel faylda yaratish"""
    try:
        # Ma'lumotlarni olish
        murojaatlar = await db.get_all_murojaatlar_for_export()
        
        if not murojaatlar:
            return None
        
        # Excel fayl yaratish
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Murojaatlar"
        
        # Stil sozlamalari
        header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
        header_font = Font(bold=True, color="FFFFFF", size=11)
        border = Border(
            left=Side(style='thin'),
            right=Side(style='thin'),
            top=Side(style='thin'),
            bottom=Side(style='thin')
        )
        
        # Sarlavhalar
        headers = [
            "№", "ID", "F.I.Sh", "Pasport", "Telefon", "Manzil",
            "Kategoriya", "Murojaat matni", "Holat", "Yuborilgan sana",
            "Javob", "Javob beruvchi", "Javob sanasi"
        ]
        
        for col_num, header in enumerate(headers, 1):
            cell = ws.cell(row=1, column=col_num)
            cell.value = header
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal='center', vertical='center')
            cell.border = border
        
        # Ma'lumotlarni qo'shish
        for row_num, m in enumerate(murojaatlar, 2):
            data = [
                row_num - 1,
                m['id'],
                m['full_name'],
                m['passport'],
                m['phone'],
                m['address'] or '',
                m['category'],
                m['text'],
                m['status'],
                m['created_at'][:16] if m['created_at'] else '',
                m['javob_text'] or '',
                m['admin_username'] or '',
                m['javob_date'][:16] if m.get('javob_date') else ''
            ]
            
            for col_num, value in enumerate(data, 1):
                cell = ws.cell(row=row_num, column=col_num)
                cell.value = value
                cell.border = border
                cell.alignment = Alignment(vertical='center', wrap_text=True)
        
        # Ustunlar kengligini sozlash
        column_widths = [5, 8, 25, 12, 15, 30, 20, 40, 15, 18, 40, 20, 18]
        for col_num, width in enumerate(column_widths, 1):
            ws.column_dimensions[get_column_letter(col_num)].width = width
        
        # Satrlar balandligini sozlash
        for row in ws.iter_rows(min_row=2, max_row=ws.max_row):
            ws.row_dimensions[row[0].row].height = 30
        
        # Faylni saqlash
        filename = f"murojaatlar_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        filepath = os.path.join(MEDIA_PATH, filename)
        wb.save(filepath)
        
        logger.info(f"✅ Excel fayl yaratildi: {filepath}")
        return filepath
        
    except Exception as e:
        logger.error(f"❌ Excel yaratishda xatolik: {e}")
        import traceback
        traceback.print_exc()
        return None

# ==================== ESLATMA SCHEDULER ====================
class ReminderScheduler:
    """Eslatma uchun scheduler"""
    
    def __init__(self, bot: Bot):
        self.bot = bot
        self.scheduler = AsyncIOScheduler()
    
    def start(self):
        """Scheduler ishga tushirish"""
        # Har kuni soat 10:00 da
        self.scheduler.add_job(
            self.send_reminders,
            'cron',
            hour=10,
            minute=0
        )
        self.scheduler.start()
        logger.info("✅ Eslatma scheduler ishga tushdi")
    
    async def send_reminders(self):
        """Eski murojaatlar haqida eslatma yuborish"""
        try:
            old_murojaatlar = await db.get_old_murojaatlar(REMINDER_DAYS)
            
            if not old_murojaatlar:
                return
            
            message_text = (
                f"⚠️ <b>ESLATMA!</b>\n\n"
                f"Quyidagi murojaatlarga {REMINDER_DAYS} kundan beri javob berilmagan:\n\n"
            )
            
            for m in old_murojaatlar[:10]:
                days_ago = (datetime.now() - datetime.strptime(m['created_at'], '%Y-%m-%d %H:%M:%S')).days
                message_text += (
                    f"📋 #{m['id']} - {m['category']}\n"
                    f"👤 {m['full_name']}\n"
                    f"📅 {days_ago} kun oldin\n\n"
                )
            
            if len(old_murojaatlar) > 10:
                message_text += f"\n<i>Jami {len(old_murojaatlar)} ta javobsiz murojaat</i>"
            
            await self.bot.send_message(
                GROUP_CHAT_ID,
                message_text,
                parse_mode="HTML"
            )
            
            logger.info(f"✅ Eslatma yuborildi: {len(old_murojaatlar)} ta murojaat")
            
        except Exception as e:
            logger.error(f"❌ Eslatma yuborishda xatolik: {e}")

# ==================== STATES ====================
class MurojaatStates(StatesGroup):
    """Murojaat yuborish uchun holatlar"""
    full_name = State()
    passport = State()
    phone = State()
    address = State()
    category = State()
    text = State()
    photo = State()

# ==================== KEYBOARD FUNKSIYALAR ====================
def get_main_menu():
    """Asosiy menyu klaviaturasi"""
    keyboard = ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✍️ Murojaat yuborish")],
            [KeyboardButton(text="📋 Mening murojaatlarim")],
            [KeyboardButton(text="🏠 Bosh sahifa")]
        ],
        resize_keyboard=True
    )
    return keyboard

def get_categories_keyboard():
    """Kategoriyalar klaviaturasi"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🏛 Davlat xizmatlari", callback_data="cat_davlat")],
            [InlineKeyboardButton(text="🏥 Sog'liqni saqlash", callback_data="cat_sogliq")],
            [InlineKeyboardButton(text="🎓 Ta'lim", callback_data="cat_talim")],
            [InlineKeyboardButton(text="🚗 Transport", callback_data="cat_transport")],
            [InlineKeyboardButton(text="🏢 Kommunal xizmatlar", callback_data="cat_kommunal")],
            [InlineKeyboardButton(text="📱 Boshqa", callback_data="cat_boshqa")],
        ]
    )
    return keyboard

def get_photo_keyboard():
    """Rasm yuklash klaviaturasi"""
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📸 Rasm yuklash", callback_data="add_photo")],
            [InlineKeyboardButton(text="⏭ Rasmisiz davom etish", callback_data="skip_photo")]
        ]
    )
    return keyboard

# ==================== START HANDLER ====================
@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Start command handler"""
    await state.clear()
    
    welcome_text = (
        f"👋 <b>Assalomu aleykum, {message.from_user.first_name}!</b>\n\n"
        f"🤝 Men - Elektron murojaat botiman.\n\n"
        f"📝 <b>Nima qila olaman?</b>\n"
        f"• Davlat organlari va tashkilotlariga murojaat yuborishingiz mumkin\n"
        f"• Sizning murojaatlaringizni kuzatib borasiz\n"
        f"• Javoblarni qabul qilasiz\n\n"
        f"⚡️ Murojaat yuborish uchun quyidagi tugmani bosing!"
    )
    
    await message.answer(
        welcome_text,
        reply_markup=get_main_menu(),
        parse_mode="HTML"
    )

# ==================== BOSH SAHIFA HANDLER ====================
@dp.message(F.text == "🏠 Bosh sahifa")
async def home_handler(message: Message, state: FSMContext):
    """Bosh sahifaga qaytish"""
    await state.clear()
    await cmd_start(message, state)

# ==================== MUROJAAT YUBORISH ====================
@dp.message(F.text == "✍️ Murojaat yuborish")
async def start_murojaat(message: Message, state: FSMContext):
    """Murojaat yuborish jarayonini boshlash"""
    # Kunlik limitni tekshirish
    daily_count = await db.get_daily_count(message.from_user.id)
    
    if daily_count >= DAILY_LIMIT:
        await message.answer(
            f"⏳ <b>Kunlik limit tugadi!</b>\n\n"
            f"Siz bugun {DAILY_LIMIT} ta murojaat yuborganingiz.\n"
            f"Iltimos, ertaga qayta urinib ko'ring.\n\n"
            f"<i>Bu cheklash spam va suiiste'mol qilishlarning oldini olish uchun qo'yilgan.</i>",
            parse_mode="HTML",
            reply_markup=get_main_menu()
        )
        return
    
    await state.set_state(MurojaatStates.full_name)
    await message.answer(
        "📝 <b>1-QADAM: To'liq ismingizni kiriting</b>\n\n"
        "Masalan: <code>Aliyev Vali Akramovich</code>\n\n"
        "<i>❗️ Kamida 2 ta so'z kiriting</i>",
        parse_mode="HTML"
    )

@dp.message(MurojaatStates.full_name)
async def process_full_name(message: Message, state: FSMContext):
    """To'liq ismni qabul qilish"""
    full_name = message.text.strip()
    
    if not validate_full_name(full_name):
        await message.answer(
            "❌ <b>Noto'g'ri format!</b>\n\n"
            "Iltimos, to'liq ismingizni kiriting (kamida 2 ta so'z, raqamsiz).\n\n"
            "Masalan: <code>Aliyev Vali Akramovich</code>",
            parse_mode="HTML"
        )
        return
    
    await state.update_data(full_name=full_name)
    await state.set_state(MurojaatStates.passport)
    
    await message.answer(
        "🛂 <b>2-QADAM: Pasport seriya va raqamingizni kiriting</b>\n\n"
        "Format: <code>AA1234567</code> (2 ta KATTA harf + 7 ta raqam)\n\n"
        "Masalan: <code>AB1234567</code>",
        parse_mode="HTML"
    )

@dp.message(MurojaatStates.passport)
async def process_passport(message: Message, state: FSMContext):
    """Pasportni qabul qilish"""
    passport = message.text.strip().upper()
    
    if not validate_passport(passport):
        await message.answer(
            "❌ <b>Noto'g'ri pasport formati!</b>\n\n"
            "Format: <code>AA1234567</code> (2 ta KATTA harf + 7 ta raqam)\n\n"
            "Masalan: <code>AB1234567</code>",
            parse_mode="HTML"
        )
        return
    
    await state.update_data(passport=passport)
    await state.set_state(MurojaatStates.phone)
    
    await message.answer(
        "📱 <b>3-QADAM: Telefon raqamingizni kiriting</b>\n\n"
        "Format: <code>+998XXXXXXXXX</code>\n\n"
        "Masalan: <code>+998901234567</code>",
        parse_mode="HTML"
    )

@dp.message(MurojaatStates.phone)
async def process_phone(message: Message, state: FSMContext):
    """Telefonni qabul qilish"""
    phone = message.text.strip()
    
    if not validate_phone(phone):
        await message.answer(
            "❌ <b>Noto'g'ri telefon raqami!</b>\n\n"
            "Format: <code>+998XXXXXXXXX</code>\n\n"
            "Masalan: <code>+998901234567</code>",
            parse_mode="HTML"
        )
        return
    
    await state.update_data(phone=phone)
    await state.set_state(MurojaatStates.address)
    
    await message.answer(
        "🏠 <b>4-QADAM: Yashash manzilingizni kiriting</b>\n\n"
        "Masalan: <code>Toshkent shahar, Yunusobod tumani, Amir Temur ko'chasi, 1-uy</code>",
        parse_mode="HTML"
    )

@dp.message(MurojaatStates.address)
async def process_address(message: Message, state: FSMContext):
    """Manzilni qabul qilish"""
    address = message.text.strip()
    
    if len(address) < 10:
        await message.answer(
            "❌ <b>Manzil juda qisqa!</b>\n\n"
            "Iltimos, to'liq manzilni kiriting.",
            parse_mode="HTML"
        )
        return
    
    await state.update_data(address=address)
    await state.set_state(MurojaatStates.category)
    
    await message.answer(
        "📂 <b>5-QADAM: Murojaat turini tanlang</b>\n\n"
        "Quyidagi kategoriyalardan birini tanlang:",
        reply_markup=get_categories_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("cat_"))
async def process_category(callback: CallbackQuery, state: FSMContext):
    """Kategoriyani qabul qilish"""
    categories = {
        "cat_davlat": "🏛 Davlat xizmatlari",
        "cat_sogliq": "🏥 Sog'liqni saqlash",
        "cat_talim": "🎓 Ta'lim",
        "cat_transport": "🚗 Transport",
        "cat_kommunal": "🏢 Kommunal xizmatlar",
        "cat_boshqa": "📱 Boshqa"
    }
    
    category = categories.get(callback.data, "Boshqa")
    await state.update_data(category=category)
    await state.set_state(MurojaatStates.text)
    
    await callback.message.edit_text(
        f"✅ Kategoriya tanlandi: <b>{category}</b>",
        parse_mode="HTML"
    )
    
    await callback.message.answer(
        "📝 <b>6-QADAM: Murojaat matnini yozing</b>\n\n"
        "Muammongizni batafsil yozib bering.\n\n"
        "<i>❗️ Kamida 10 ta belgi kiriting</i>",
        parse_mode="HTML"
    )
    
    await callback.answer()

@dp.message(MurojaatStates.text)
async def process_text(message: Message, state: FSMContext):
    """Murojaat matnini qabul qilish"""
    text = message.text.strip()
    
    if len(text) < 10:
        await message.answer(
            "❌ <b>Matn juda qisqa!</b>\n\n"
            "Iltimos, muammongizni batafsil yozing (kamida 10 ta belgi).",
            parse_mode="HTML"
        )
        return
    
    await state.update_data(text=text)
    await state.set_state(MurojaatStates.photo)
    
    await message.answer(
        "📸 <b>7-QADAM: Rasm yuklash (ixtiyoriy)</b>\n\n"
        "Agar muammongizga oid rasm yoki skrinshot bo'lsa, yuklashingiz mumkin.\n\n"
        "Yoki rasmisiz davom eting.",
        reply_markup=get_photo_keyboard(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data == "add_photo")
async def add_photo_callback(callback: CallbackQuery):
    """Rasm yuklash tugmasi"""
    await callback.message.edit_text(
        "📸 <b>Rasmni yuboring</b>\n\n"
        "Faqat bitta rasm yuboring.",
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data == "skip_photo")
async def skip_photo_callback(callback: CallbackQuery, state: FSMContext):
    """Rasmisiz davom etish - default rasm bilan"""
    await callback.answer()
    
    # MUHIM: callback.from_user.id dan haqiqiy foydalanuvchi ID ni olamiz
    # callback.message - bu bot yuborgan xabar, frozen obyekt
    # Shuning uchun user_id ni parametr sifatida yuboramiz
    
    await finish_murojaat(
        callback.message, 
        state, 
        photo_path=None,  # Rasm yo'q, default ishlatiladi
        user_id=callback.from_user.id  # Haqiqiy foydalanuvchi ID
    )

@dp.message(MurojaatStates.photo, F.photo)
async def process_photo(message: Message, state: FSMContext):
    """Rasmni qabul qilish"""
    # Eng katta razmli rasmni olish
    photo = message.photo[-1]
    
    # Rasmni saqlash
    file = await bot.get_file(photo.file_id)
    file_extension = file.file_path.split('.')[-1]
    filename = f"{message.from_user.id}_{datetime.now().strftime('%Y%m%d%H%M%S')}.{file_extension}"
    photo_path = os.path.join(MEDIA_PATH, filename)
    
    await bot.download_file(file.file_path, photo_path)
    
    logger.info(f"✅ Rasm saqlandi: {photo_path}")
    
    await finish_murojaat(message, state, photo_path=photo_path)

async def finish_murojaat(message: Message, state: FSMContext, photo_path: str = None, user_id: int = None):
    """Murojaatni yakunlash va yuborish"""
    data = await state.get_data()
    
    # Ma'lumotlarni tekshirish
    required_fields = ['full_name', 'passport', 'phone', 'address', 'category', 'text']
    if not all(field in data for field in required_fields):
        await message.answer(
            "❌ Xatolik: Ma'lumotlar to'liq emas. Iltimos, qaytadan boshlang.",
            reply_markup=get_main_menu()
        )
        await state.clear()
        return
    
    # Tasdiqlash xabari
    confirm_text = (
        "✅ <b>MUROJAAT TAYYORLANDI</b>\n\n"
        f"👤 <b>F.I.Sh:</b> {data['full_name']}\n"
        f"🛂 <b>Pasport:</b> {data['passport']}\n"
        f"📱 <b>Telefon:</b> {data['phone']}\n"
        f"🏠 <b>Manzil:</b> {data['address']}\n"
        f"📂 <b>Tur:</b> {data['category']}\n"
        f"📝 <b>Matn:</b> {data['text']}\n"
        f"📸 <b>Rasm:</b> {'✅ Bor' if photo_path else '❌ Yoq'}\n\n"
        "<i>Murojaat guruhga yuborilmoqda...</i>"
    )
    
    await message.answer(confirm_text, parse_mode="HTML")
    
    # Guruhga yuborish
    try:
        group_text = (
            "🆕 <b>YANGI MUROJAAT</b>\n\n"
            f"👤 <b>F.I.Sh:</b> {data['full_name']}\n"
            f"🛂 <b>Pasport:</b> {data['passport']}\n"
            f"📱 <b>Telefon:</b> {data['phone']}\n"
            f"🏠 <b>Manzil:</b> {data['address']}\n"
            f"📂 <b>Tur:</b> {data['category']}\n"
            f"📝 <b>Matn:</b>\n{data['text']}\n\n"
            f"📅 <b>Sana:</b> {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            f"🔢 <b>User ID:</b> <code>{message.from_user.id}</code>\n\n"
            "<i>💬 Javob berish uchun bu xabarga reply qiling!</i>"
        )
        
        if photo_path and os.path.exists(photo_path):
            # Foydalanuvchi rasmi bilan yuborish
            photo_file = FSInputFile(photo_path)
            sent_message = await bot.send_photo(
                GROUP_CHAT_ID,
                photo=photo_file,
                caption=group_text,
                parse_mode="HTML"
            )
            final_image_path = photo_path  # Foydalanuvchi rasmi
        else:
            # Default rasm bilan yuborish (agar foydalanuvchi rasm yubormasa)
            if os.path.exists(DEFAULT_IMAGE):
                default_photo = FSInputFile(DEFAULT_IMAGE)
                sent_message = await bot.send_photo(
                    GROUP_CHAT_ID,
                    photo=default_photo,
                    caption=group_text,
                    parse_mode="HTML"
                )
                final_image_path = DEFAULT_IMAGE  # Default rasm
                logger.info(f"📸 Default rasm ishlatildi")
            else:
                # Agar default rasm ham bo'lmasa, matnli xabar yuborish
                sent_message = await bot.send_message(
                    GROUP_CHAT_ID,
                    group_text,
                    parse_mode="HTML",
                    disable_notification=False
                )
                final_image_path = None  # Rasm yo'q
                logger.warning(f"⚠️ Default rasm topilmadi: {DEFAULT_IMAGE}")
        
        group_message_id = sent_message.message_id
        rasm_status = 'foydalanuvchi' if photo_path else ('default' if final_image_path else 'yoq')
        logger.info(f"✅ Guruhga yuborildi: message_id={group_message_id}, rasm={rasm_status}")
        
        # User ID ni aniqlash - agar parametr berilgan bo'lsa uni ishlatamiz
        actual_user_id = user_id if user_id else message.from_user.id
        logger.info(f"🔍 DEBUG: user_id={actual_user_id}, username={message.from_user.username if hasattr(message, 'from_user') else 'N/A'}, first_name={message.from_user.first_name if hasattr(message, 'from_user') else 'N/A'}")
        
        # Database ga saqlash - MUHIM: final_image_path ishlatamiz
        murojaat_id = await db.add_murojaat(
            user_id=actual_user_id,
            full_name=data['full_name'],
            passport=data['passport'],
            phone=data['phone'],
            address=data['address'],
            category=data['category'],
            text=data['text'],
            image_path=final_image_path,  # Default yoki foydalanuvchi rasmi
            group_message_id=group_message_id
        )
        
        if murojaat_id:
            success_text = (
                "✅ <b>MUROJAAT MUVAFFAQIYATLI YUBORILDI!</b>\n\n"
                f"📋 Murojaat raqami: <b>#{murojaat_id}</b>\n\n"
                "📬 Sizning murojaatingiz ko'rib chiqilmoqda.\n"
                "Javob kelganda sizga xabar beramiz.\n\n"
                "📊 Holatni \"📋 Mening murojaatlarim\" orqali kuzatishingiz mumkin."
            )
            await message.answer(success_text, reply_markup=get_main_menu(), parse_mode="HTML")
        else:
            await message.answer(
                "⚠️ Murojaat yuborildi, lekin saqlashda xatolik yuz berdi.",
                reply_markup=get_main_menu()
            )
        
    except Exception as e:
        logger.error(f"❌ Guruhga yuborishda xatolik: {e}")
        import traceback
        traceback.print_exc()
        await message.answer(
            f"❌ <b>Xatolik yuz berdi!</b>\n\n"
            f"Murojaat yuborib bo'lmadi. Iltimos, qaytadan urinib ko'ring.\n\n"
            f"<code>{str(e)}</code>",
            reply_markup=get_main_menu(),
            parse_mode="HTML"
        )
    
    await state.clear()

# ==================== GURUHDA JAVOB BERISH ====================
@dp.message(F.chat.id == GROUP_CHAT_ID, F.reply_to_message)
async def group_reply_handler(message: Message):
    """Guruhda javob berish handler"""
    try:
        if not message.reply_to_message:
            logger.warning("⚠️ Reply to message yo'q!")
            return
        
        # Reply qilingan xabar ID
        reply_to_message_id = message.reply_to_message.message_id
        
        logger.info(f"🔍 Guruhda javob: reply_to={reply_to_message_id}, reply_type={type(message.reply_to_message)}")
        
        # Database dan murojaatni topish
        murojaat = await db.get_murojaat_by_group_msg(reply_to_message_id)
        
        if not murojaat:
            logger.warning(f"⚠️ Murojaat topilmadi: group_msg_id={reply_to_message_id}")
            
            # Debug: Database dagi barcha group_message_id larni ko'rsatish
            try:
                async with aiosqlite.connect(DB_PATH) as db_conn:
                    db_conn.row_factory = aiosqlite.Row
                    async with db_conn.execute(
                        "SELECT id, group_message_id, full_name FROM murojaatlar ORDER BY id DESC LIMIT 5"
                    ) as cursor:
                        recent = await cursor.fetchall()
                        logger.info(f"📊 Oxirgi 5 ta murojaat: {[dict(r) for r in recent]}")
            except Exception as debug_err:
                logger.error(f"Debug xatolik: {debug_err}")
            
            await message.reply(
                "❌ <b>Murojaat topilmadi!</b>\n\n"
                f"Reply qilingan xabar ID: <code>{reply_to_message_id}</code>\n\n"
                "<i>Ehtimol bu xabar murojaat emas yoki database da mavjud emas.</i>\n\n"
                "<b>Tekshirish:</b>\n"
                "• Murojaat xabariga to'g'ridan-to'g'ri reply qilyapsizmi?\n"
                "• Eski xabarlarga reply qilmang, database bo'sh bo'lishi mumkin.",
                parse_mode="HTML"
            )
            return
        
        murojaat_id = murojaat['id']
        user_id = murojaat['user_id']
        javob_text = message.text
        
        logger.info(f"✅ Murojaat topildi: #{murojaat_id}, user={user_id}")
        logger.info(f"🔍 DEBUG: Murojaat ma'lumotlari: {murojaat}")
        
        if not javob_text or len(javob_text.strip()) < 3:
            await message.reply("❌ Javob matni juda qisqa! Kamida 3 ta belgi kiriting.")
            return
        
        # Javob beruvchi ma'lumotlari
        admin_id = message.from_user.id
        admin_username = message.from_user.username or message.from_user.first_name or f"Admin{admin_id}"
        
        logger.info(f"👤 Javob beruvchi: {admin_username} (ID: {admin_id})")
        
        # Javobni database ga saqlash
        await db.add_javob(murojaat_id, admin_id, admin_username, javob_text)
        await db.update_status(murojaat_id, "Javob berildi")
        
        logger.info(f"💾 Javob database ga saqlandi")
        
        # Guruhga tasdiq
        await message.reply(
            f"✅ <b>JAVOB YUBORILDI!</b>\n\n"
            f"📋 Murojaat: #{murojaat_id}\n"
            f"👤 Admin: @{admin_username}\n"
            f"💬 Javob: {javob_text[:100]}{'...' if len(javob_text) > 100 else ''}\n\n"
            f"<i>✓ Bu so'rovga javob qaytarildi</i>",
            parse_mode="HTML"
        )
        
        # Foydalanuvchiga javob yuborish
        try:
            # Bot o'ziga xabar yuborishning oldini olish
            bot_info = await bot.get_me()
            
            # MUHIM: Agar user_id bot IDsi bo'lsa, bu xato!
            if user_id == bot_info.id:
                logger.error(f"❌ XATO: Database da user_id bot IDsi! user_id={user_id}, bot_id={bot_info.id}")
                logger.error(f"❌ Bu murojaat noto'g'ri saqlangan. Murojaat #{murojaat_id}")
                await message.reply(
                    f"❌ <b>DATABASE XATOLIGI!</b>\n\n"
                    f"Murojaat #{murojaat_id} noto'g'ri saqlangan:\n"
                    f"• User ID: <code>{user_id}</code> (bu bot IDsi!)\n"
                    f"• Bot ID: <code>{bot_info.id}</code>\n\n"
                    f"<b>Sabab:</b> Murojaat yuborilganda user_id noto'g'ri saqlangan.\n\n"
                    f"<b>Yechim:</b>\n"
                    f"1. Botni qayta ishga tushiring\n"
                    f"2. Yangi murojaat yuboring (endi to'g'ri saqlanadi)\n"
                    f"3. Eski murojaatlarga javob berib bo'lmaydi\n\n"
                    f"<i>Agar muammo davom etsa, dasturchiga murojaat qiling.</i>",
                    parse_mode="HTML"
                )
                return
            
            await bot.send_message(
                user_id,
                f"📬 <b>Sizning #{murojaat_id} raqamli murojaatingizga javob keldi!</b>\n\n"
                f"💬 <b>Javob:</b>\n{javob_text}\n\n"
                f"Rahmat! 🙏",
                parse_mode="HTML"
            )
            logger.info(f"✅ Javob foydalanuvchiga yuborildi: user={user_id}")
        except Exception as e:
            error_message = str(e)
            logger.error(f"❌ Foydalanuvchiga yuborishda xatolik: {error_message}")
            
            # Xatolik turini aniqlash
            if "bots can't send messages to bots" in error_message:
                error_text = "Bu murojaat bot tomonidan yuborilgan. Botlar bir-biriga xabar yubora olmaydi."
            elif "bot was blocked by the user" in error_message:
                error_text = "Foydalanuvchi botni bloklagan."
            elif "user is deactivated" in error_message:
                error_text = "Foydalanuvchi akkaunti o'chirilgan."
            elif "chat not found" in error_message:
                error_text = "Foydalanuvchi topilmadi yoki botni /start qilmagan."
            else:
                error_text = f"Noma'lum xatolik: {error_message}"
            
            await message.reply(
                f"⚠️ <b>Javob saqlandi, lekin foydalanuvchiga yuborilmadi</b>\n\n"
                f"📋 Murojaat: #{murojaat_id}\n"
                f"👤 User ID: <code>{user_id}</code>\n"
                f"❌ Sabab: {error_text}",
                parse_mode="HTML"
            )
    
    except Exception as e:
        logger.error(f"❌ Guruh handler xatolik: {e}")
        import traceback
        traceback.print_exc()
        await message.reply(
            f"❌ <b>Xatolik yuz berdi!</b>\n\n"
            f"<code>{str(e)}</code>",
            parse_mode="HTML"
        )

# ==================== MENING MUROJAATLARIM ====================
@dp.message(F.text == "📋 Mening murojaatlarim")
async def my_murojaatlar(message: Message, state: FSMContext):
    """Foydalanuvchining barcha murojaatlarini ko'rsatish"""
    await state.clear()
    
    murojaatlar = await db.get_user_murojaatlar(message.from_user.id)
    
    if not murojaatlar:
        await message.answer(
            "📋 <b>Sizda hali murojatlar yo'q.</b>\n\n"
            "Murojaat yuborish uchun \"✍️ Murojaat yuborish\" tugmasini bosing.",
            reply_markup=get_main_menu(),
            parse_mode="HTML"
        )
        return
    
    response = "📋 <b>SIZNING MUROJAATLARINGIZ:</b>\n\n"
    
    for m in murojaatlar[:10]:
        javob = await db.get_javob(m['id'])
        javob_status = "✅ Javob berildi" if javob else f"⏳ {m['status']}"
        
        response += (
            f"━━━━━━━━━━━━━━━\n"
            f"📋 <b>Murojaat #{m['id']}</b>\n"
            f"📂 Tur: {m['category']}\n"
            f"📝 Matn: {m['text'][:50]}...\n"
            f"📅 Sana: {m['created_at'][:16]}\n"
            f"📊 Holat: {javob_status}\n"
        )
        
        if javob:
            response += f"💬 Javob: {javob['javob_text'][:80]}...\n"
    
    response += "━━━━━━━━━━━━━━━\n\n"
    
    if len(murojaatlar) > 10:
        response += f"<i>Jami {len(murojaatlar)} ta. Oxirgi 10 tasi ko'rsatildi.</i>"
    
    await message.answer(response, parse_mode="HTML", reply_markup=get_main_menu())

# ==================== GURUH STATISTIKA VA EXPORT ====================
@dp.message(Command("statistics"))
async def cmd_statistics(message: Message):
    """Guruhda statistika ko'rsatish"""
    # Faqat guruhda ishlaydi
    if message.chat.id != GROUP_CHAT_ID:
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
        
        # Export tugmasi
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="📥 Excel formatda yuklab olish", callback_data="export_excel")]
            ]
        )
        
        await message.answer(response, parse_mode="HTML", reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"❌ Statistika xatolik: {e}")
        import traceback
        traceback.print_exc()
        await message.answer(f"❌ Xatolik: {e}")

@dp.callback_query(F.data == "export_excel")
async def export_excel_callback(callback: CallbackQuery):
    """Excel faylni export qilish"""
    # Faqat guruhda ishlaydi
    if callback.message.chat.id != GROUP_CHAT_ID:
        await callback.answer("❌ Bu funksiya faqat guruhda ishlaydi!", show_alert=True)
        return
    
    try:
        await callback.answer("📊 Excel fayl yaratilmoqda...", show_alert=True)
        
        # Excel faylni yaratish
        excel_path = await create_excel_report()
        
        if not excel_path or not os.path.exists(excel_path):
            await callback.message.answer("❌ Excel yaratishda xatolik yuz berdi.")
            return
        
        # Faylni yuborish
        excel_file = FSInputFile(excel_path)
        await callback.message.answer_document(
            document=excel_file,
            caption=(
                "📊 <b>MUROJAATLAR STATISTIKASI</b>\n\n"
                f"📅 Yaratildi: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                f"📁 Fayl: {os.path.basename(excel_path)}\n\n"
                "<i>Barcha murojaatlar va javoblar bu faylda mavjud.</i>"
            ),
            parse_mode="HTML"
        )
        
        logger.info(f"✅ Excel fayl yuborildi: {excel_path}")
        
        # Faylni o'chirish (ixtiyoriy)
        try:
            os.remove(excel_path)
            logger.info(f"🗑 Fayl o'chirildi: {excel_path}")
        except:
            pass
        
    except Exception as e:
        logger.error(f"❌ Excel export xatolik: {e}")
        import traceback
        traceback.print_exc()
        await callback.message.answer(f"❌ Xatolik: {e}")

# ==================== STATISTIKA (ADMIN) ====================
@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    """Statistika (admin uchun)"""
    try:
        pending = await db.get_pending_murojaatlar()
        
        response = (
            f"📊 <b>STATISTIKA</b>\n\n"
            f"⏳ Javob kutayotgan: <b>{len(pending)} ta</b>\n\n"
        )
        
        if pending:
            response += "<b>Eng eski 5 ta murojaat:</b>\n\n"
            for m in pending[:5]:
                response += (
                    f"📋 #{m['id']} - {m['category']}\n"
                    f"📅 {m['created_at'][:16]}\n\n"
                )
        
        await message.answer(response, parse_mode="HTML")
    
    except Exception as e:
        await message.answer(f"❌ Xatolik: {e}")

@dp.message(Command("debug"))
async def cmd_debug(message: Message):
    """Debug - oxirgi murojaatlarni ko'rish"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
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
        # Media papkasini yaratish (XATOLIK TUZATISH)
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
