# 🚂 RAILWAY DEPLOY - TELEGRAM MUROJAAT BOTI

## 🎯 BU PAKET HAQIDA

Railway.app uchun tayyor deploy package. Barcha kerakli fayllar mavjud!

---

## 📦 PAKET TARKIBI

### Asosiy fayllar:
1. **bot_railway_full.py** - To'liq bot kodi (env variables bilan)
2. **requirements.txt** - Python dependencies
3. **Procfile** - Railway start komandasi
4. **railway.json** - Railway config
5. **nixpacks.toml** - Build settings
6. **RAILWAY_SETUP.md** - To'liq yo'riqnoma

---

## ⚡ 5 DAQIQADA DEPLOY

### Qadamlar:

```bash
# 1. GitHub repository yarating
git init
git add .
git commit -m "Bot deploy"
git remote add origin https://github.com/USERNAME/bot.git
git push -u origin main

# 2. Railway.app ga kiring
# https://railway.app

# 3. New Project → Deploy from GitHub repo

# 4. Variables qo'shing:
# BOT_TOKEN = your_token_here
# GROUP_CHAT_ID = -100xxx

# 5. Deploy bosing!
```

---

## 🔧 ENVIRONMENT VARIABLES

Railway **Variables** bo'limida sozlang:

| O'zgaruvchi | Qiymat | Majburiy |
|-------------|--------|----------|
| BOT_TOKEN | Bot tokeningiz | ✅ HA |
| GROUP_CHAT_ID | Admin guruh ID | ✅ HA |
| DAILY_LIMIT | 5 | ❌ Yo'q |
| REMINDER_DAYS | 15 | ❌ Yo'q |

---

## ✅ ISHGA TUSHGACH

1. Railway **Logs** da tekshiring:
```
✅ Bot ishga tushdi!
```

2. Telegram da test qiling:
```
/start
```

3. Murojaat yuboring va guruhda ko'ring!

---

## 📊 AFZALLIKLAR

✅ **Bepul** - 500 soat/oy  
✅ **Tez** - 2-3 daqiqada deploy  
✅ **Oson** - GitHub integration  
✅ **Auto-deploy** - Har push da yangilanadi  
✅ **Monitoring** - Real-time logs va metrics  

---

## 🐛 XATOLARNI HAL QILISH

### "Cannot start bot"
→ `BOT_TOKEN` to'g'ri ekanligini tekshiring

### "Database error"  
→ Railway **Volumes** qo'shing (Settings → Volumes)

### "Module not found"
→ `requirements.txt` faylda kutubxona borligini tekshiring

---

## 📁 FAYL STRUKTURASI

```
telegram-bot/
├── bot_railway_full.py     ← Asosiy bot
├── requirements.txt        ← Dependencies
├── Procfile               ← Start command
├── railway.json           ← Config
├── nixpacks.toml          ← Build
├── RAILWAY_SETUP.md       ← To'liq guide
└── README_RAILWAY.md      ← Bu fayl
```

---

## 🔄 BOTNI YANGILASH

Kodni o'zgartirganingizda:

```bash
git add .
git commit -m "Yangilandi"
git push
```

Railway **avtomatik** deploy qiladi! 🚀

---

## 💾 DATABASE SAQLASH

Persistent storage uchun:

1. Railway → Settings → Volumes
2. Add Volume
3. Mount Path: `/app/data`
4. Botda:
```python
DB_PATH = "/app/data/murojaatlar.db"
```

---

## 📚 QO'SHIMCHA MA'LUMOT

- **To'liq yo'riqnoma:** `RAILWAY_SETUP.md`
- **Railway Docs:** https://docs.railway.app/
- **Telegram Bot API:** https://core.telegram.org/bots/api

---

## ⚠️ MUHIM

🔒 **Bot tokenni GitHub ga yuklaMASLIK!**  
✅ Faqat environment variables ishlatish  
✅ `.gitignore` da `.env` ignore

---

## 🎉 TAYYOR!

Barcha fayllar tayyor. Faqat GitHub ga yuklang va Railway ga deploy qiling!

**Omad! 🚀**
