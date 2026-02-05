# 🚂 RAILWAY.APP GA BOT NI JOYLASHTIRISH

## ✨ RAILWAY AFZALLIKLARI

✅ **Bepul:** 500 soat/oy (1 loyiha uchun yetadi)  
✅ **Tez:** 2-3 daqiqada deploy  
✅ **Oson:** GitHub dan avtomatik deploy  
✅ **Ishonchli:** 24/7 ishlaydi  
✅ **Telegram API:** To'g'ridan-to'g'ri ulanadi (proxy yo'q!)

---

## 📋 TEZKOR BOSQICHLAR

### 1️⃣ GITHUB REPOSITORY YARATISH

1. https://github.com/new ga o'ting
2. Repository nomi: `telegram-murojaat-bot`
3. **Create repository** bosing
4. Fayllarni yuklang (drag & drop yoki git)

### 2️⃣ RAILWAY GA ULASH

1. https://railway.app ga kiring
2. **Login with GitHub** bosing
3. **New Project** → **Deploy from GitHub repo**
4. Repository tanlang
5. **Deploy Now** bosing

### 3️⃣ ENVIRONMENT VARIABLES

Railway **Variables** da qo'shing:

```
BOT_TOKEN = 8311683221:AAFWy1J5sq-9-_Kdp5qf3c7kMl9upEQoj4k
GROUP_CHAT_ID = -1003773765959
DAILY_LIMIT = 5
REMINDER_DAYS = 15
```

### 4️⃣ TAYYOR! ✅

Bot **Logs** da `✅ Bot ishga tushdi!` yozuvini ko'rish kerak.

---

## 📁 KERAKLI FAYLLAR

Railway uchun quyidagi fayllar kerak:

1. **bot_railway_full.py** - Asosiy bot kodi
2. **requirements.txt** - Python dependencies
3. **Procfile** - Start komandasi
4. **railway.json** - Konfiguratsiya
5. **nixpacks.toml** - Build settings

Barcha fayllar tayyor - faqat GitHub ga yuklang!

---

## 🔄 YANGILASH

Kodni o'zgartirganingizda:

```bash
git add .
git commit -m "Yangilandi"
git push
```

Railway avtomatik deploy qiladi!

---

## 💾 DATABASE SAQLASH

Railway **Volumes** qo'shing:

1. Settings → Volumes
2. Mount Path: `/app/data`
3. Bot kodida:
```python
DB_PATH = "/app/data/murojaatlar.db"
```

---

## 🐛 MUAMMOLARNI HAL QILISH

| Muammo | Yechim |
|--------|--------|
| Bot javob bermayapti | Environment variables tekshiring |
| "Module not found" | requirements.txt tekshiring |
| Database yo'qoladi | Volumes qo'shing |
| Bot to'xtaydi | Logs da xatolarni ko'ring |

---

## 📊 MONITORING

Railway Dashboard:
- **Metrics** - CPU, RAM
- **Logs** - Real-time
- **Deployments** - Tarix

---

## ✅ TAYYOR QILISH

1. GitHub repository yarating
2. Fayllarni yuklang
3. Railway ga ulang
4. Variables sozlang
5. Deploy!

**Jami vaqt: 5 daqiqa** ⏱️

---

**OMAD! 🚀**
