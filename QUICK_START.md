# ⚡ TEZKOR BOSHLASH - RAILWAY DEPLOY

## 🎯 3 DAQIQADA DEPLOY QILISH

### QADAMLAR:

---

## 1️⃣ GITHUB TAYYORLASH (1 daqiqa)

```bash
# Terminal/CMD da:

# a) Repository yaratish
git init
git add .
git commit -m "Initial deploy"

# b) GitHub ga yuklash
git remote add origin https://github.com/USERNAME/telegram-bot.git
git push -u origin main
```

**YoKI:** GitHub Web UI da repository ochib, fayllarni drag & drop qiling.

---

## 2️⃣ RAILWAY GA DEPLOY (1 daqiqa)

1. **https://railway.app** ga kiring
2. **Login with GitHub** bosing
3. **New Project** tugmasini bosing
4. **Deploy from GitHub repo** ni tanlang
5. Repository ni toping va tanlang
6. **Deploy Now** bosing

Railway avtomatik:
- Python muhitini o'rnatadi
- Kutubxonalarni yuklab oladi (requirements.txt)
- Botni ishga tushiradi

---

## 3️⃣ SOZLAMALAR (1 daqiqa)

Railway da **Variables** tabga o'ting va qo'shing:

```
BOT_TOKEN = 8311683221:AAFWy1J5sq-9-_Kdp5qf3c7kMl9upEQoj4k
GROUP_CHAT_ID = -1003773765959
```

**Qo'shish:**
- **New Variable** tugmasi
- Name va Value kiriting
- **Add** bosing

Har safar variable qo'shganingizda bot avtomatik restart bo'ladi.

---

## ✅ TEKSHIRISH

### Railway Logs da:
```
✅ Bot ishga tushdi!
🤖 Bot ishga tushmoqda...
📊 Kunlik limit: 5
⏰ Eslatma: 15 kun
👥 Guruh ID: -1003773765959
✅ Bot ishga tushdi!
```

### Telegram da:
1. Botni oching
2. `/start` yuboring
3. Javob kelishi kerak! ✅

---

## 🎉 TAYYOR!

Bot ishlayapti! Railway da 24/7 ishlab turadi.

---

## 📝 KEYINGI QADAMLAR

### Botni yangilash:
```bash
git add .
git commit -m "Yangilandi"
git push
```
Railway avtomatik deploy qiladi!

### Database saqlash:
Railway → Settings → Volumes → Add Volume

### Monitoring:
Railway → Metrics (CPU, RAM, Network)

---

## ⚠️ MUHIM ESLATMALAR

1. ✅ **Bot tokenni kodga yozMANG!** Faqat env variables
2. ✅ **.gitignore** da `.env` faylni ignore qiling
3. ✅ **Logs** ni doimiy tekshirib turing
4. ✅ **Bepul limit:** 500 soat/oy (etarli!)

---

## 📚 BATAFSIL MA'LUMOT

- **To'liq yo'riqnoma:** `RAILWAY_SETUP.md`
- **README:** `README.md`

---

## 🆘 YORDAM KERAKMI?

**Xatolar:**
- `RAILWAY_SETUP.md` da "Troubleshooting" bo'limi
- Railway Logs ni tekshiring
- Environment variables to'g'ri ekanligini tasdiqlang

**Savol-javob:**
- Railway Discord: https://discord.gg/railway
- Railway Docs: https://docs.railway.app/

---

**OMAD! 🚀**

Bot muvaffaqiyatli deploy bo'lsin!
