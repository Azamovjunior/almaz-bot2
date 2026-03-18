import os
import asyncio
import logging
import random
import time
from datetime import datetime, timezone
from dotenv import load_dotenv
from groq import Groq
import firebase_admin
from firebase_admin import credentials, firestore
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove,
    InputMediaPhoto
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    filters, ContextTypes, ConversationHandler
)

load_dotenv()
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ==================== CONFIG ====================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GROQ_API_KEY       = os.getenv("GROQ_API_KEY")
ADMIN_IDS          = [979542259, 6630267758]

# ===== MAJBURIY KANALLAR — yangi kanal qo'shish uchun yangi qator yozing =====
REQUIRED_CHANNELS = [
    "@Muzonoken",       # 1-kanal
    "@muzonalmaz",      # 2-kanal
    "@Muzon_shop",      # 3-kanal
    # "@yangi_kanal",   # 4-kanal (# ni olib tashlang)
]

EARN_AMOUNT        = 0.5
EARN_COOLDOWN      = 5 * 60
REFERRAL_BONUS     = 9.0
WITHDRAW_MIN       = 100.0
PROOF_CHANNEL      = "@muzon_almaz_tolovlar"
PROOF_CHANNEL_LINK = "https://t.me/muzon_almaz_tolovlar"

# ===== POST YUBORILADIGAN KANALLAR (admin broadcast) =====
BROADCAST_CHANNELS = [
    "@Muzonoken",
    "@muzonalmaz",
    "@Muzon_shop",
    # "@yangi_kanal",  # qo'shmoqchi bo'lsangiz shu yerga
]

DAILY_BONUS        = 5.0
GAME_COOLDOWN      = 60 * 60
TOURNAMENT_PRIZE   = 50.0   # turnir g'olibiga almaz

# Foydalanuvchi necha daqiqa kirmasa "sog'indik" xabari yuborilsin
MISS_YOU_MINUTES  = 10
MISS_YOU_INTERVAL = 60 * 10

PHONE, FF_ID = 1, 2

# ==================== DARAJALAR ====================
LEVELS = [
    (0,    "🥉 Bronza",    "Yangi o'yinchi"),
    (50,   "🥈 Kumush",    "Tajribali"),
    (200,  "🥇 Oltin",     "Professional"),
    (500,  "💎 Brilliant", "Master"),
    (1000, "👑 Legenda",   "Eng yaxshilar"),
]

def get_level(d):
    lvl = LEVELS[0]
    for mn, nm, ds in LEVELS:
        if d >= mn: lvl = (mn, nm, ds)
    return lvl

# ==================== RASMLAR ====================
PHOTO_URLS = {
    "start":    "https://i.ibb.co/SqK5h0y/image.jpg",
    "earn":     "https://i.ibb.co/SqK5h0y/image.jpg",
    "profile":  "https://i.ibb.co/SqK5h0y/image.jpg",
    "referral": "https://i.ibb.co/q3BF2Gc1/image.jpg",
    "top":      "https://i.ibb.co/SqK5h0y/image.jpg",
    "ai":       "https://i.ibb.co/SqK5h0y/image.jpg",
    "phone":    "https://i.ibb.co/SqK5h0y/image.jpg",
    "admin":    "https://i.ibb.co/SqK5h0y/image.jpg",
    "withdraw": "https://i.ibb.co/SqK5h0y/image.jpg",
    "game":     "https://i.ibb.co/SqK5h0y/image.jpg",
    "daily":    "https://i.ibb.co/SqK5h0y/image.jpg",
    "stats":    "https://i.ibb.co/SqK5h0y/image.jpg",
    "promo":    "https://i.ibb.co/SqK5h0y/image.jpg",
    "review":   "https://i.ibb.co/SqK5h0y/image.jpg",
    "proof":    "https://i.ibb.co/SqK5h0y/image.jpg",
}
IMAGES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")

def get_photo(key):
    fn_map = {
        "start": "start.jpg", "earn": "earn.jpg", "profile": "profile.jpg",
        "referral": "referral_jpg.jpg", "top": "top.jpg", "ai": "ai.jpg",
        "phone": "phone.jpg", "admin": "admin.jpg", "withdraw": "withdraw.jpg",
    }
    fn = fn_map.get(key)
    if fn:
        path = os.path.join(IMAGES_DIR, fn)
        if os.path.exists(path):
            return open(path, "rb")
    return PHOTO_URLS.get(key, PHOTO_URLS["start"])

def is_url(p): return isinstance(p, str)

async def send_photo(target, key, caption, kb, edit=False):
    photo = get_photo(key)
    if edit:
        try:
            await target.edit_message_media(
                media=InputMediaPhoto(media=photo, caption=caption, parse_mode="Markdown"),
                reply_markup=kb)
            if not is_url(photo): photo.close()
            return
        except:
            if not is_url(photo): photo.close()
    msg = target.message if hasattr(target, 'message') else target
    p2 = get_photo(key)
    await msg.reply_photo(photo=p2, caption=caption, parse_mode="Markdown", reply_markup=kb)
    if not is_url(p2): p2.close()

# ==================== XABARLAR ====================
GREETINGS = [
    "🔥 Voy-voy! *{name}* keldi! Bot ham xursand! 🎉",
    "💎 *{name}*! Seni ko'rganda yurak tezlashdi! 😄",
    "🎮 Chempion *{name}*! Bugun ham almaz yig'amizmi?! 💪",
    "⚡ *{name}* keldi! Bot to'liq ishga tushdi! 🚀",
    "🏆 Voy, *{name}*! Sen bo'lmasang bot yig'lab o'tirar edi! 😂",
    "💫 *{name}*! Seni kutib-kutib charchadim! Xush kelibsiz! 🌟",
    "🎯 *{name}* qaytdi! Bot: Nihoyat! deb hayqirdi! 😄",
    "👑 *{name}* bilan bot eng baxtli! Xush kelibsiz! 😊",
]

EARN_MSGS = [
    "💎 Zo'r! *{name}*, +*{amount}* almaz qo'lingizda! 😄",
    "✅ *{name}*! +*{amount}* almaz! Bot ham xursand! 🎉",
    "🔥 *{name}* yana almaz oldi! Ketdi-ketdi! 🚀",
    "💰 *{name}*, siz ishlab topish ustasi! +*{amount}* 💎",
    "⚡ Zoom! *{name}*ning hisobiga +*{amount}* almaz tushdi! 🎯",
]

WAIT_MSGS = [
    "⏳ *{name}*, sabr qiling! Almaz pishib yetilmoqda! 🌱",
    "😅 *{name}*! Hali *{min}:{sec}* qoldi!",
    "🕐 *{name}*, *{min}:{sec}* dan keyin almaz!",
    "⏰ *{name}*! *{min}:{sec}* sabr qiling!",
]

MISS_YOU_MSGS = [
    "😢 *{name}*, sizni juda sog'indik!\n\n💎 Almaz sizni kutmoqda!\n👇 Botga qaytib keling!",
    "🎮 *{name}*! Bot siz bo'lmay yig'lab qoldi! 😭\n\n💎 Almaz olishni unutdingizmi?",
    "⚡ *{name}*, qaerda qoldingiz?!\n\n💎 *{diamonds:.0f}* almaz sizni kutmoqda! 🔥",
    "🏆 *{name}*! Raqiblaringiz almaz yig'moqda!\n\n💪 Siz ham orqada qolmang!",
    "💫 *{name}*, biz sizni sog'indik! 🥺\n\n🎁 Kunlik bonus ham kutmoqda!",
    "🔥 *{name}*! Almaz yig'ish vaqti!\n\n⏰ Uzoq kirmadingiz... qaytib keling!",
    "👑 *{name}*, Top-10 ga kirmoqchimisiz?\n\n💎 Almaz yig'ishda davom eting!",
]

def greet(name): return random.choice(GREETINGS).format(name=name)
def earn_msg(name, amount): return random.choice(EARN_MSGS).format(name=name, amount=amount)
def wait_msg(name, mins, secs): return random.choice(WAIT_MSGS).format(name=name, min=mins, sec=f"{secs:02d}")
def miss_msg(name, diamonds): return random.choice(MISS_YOU_MSGS).format(name=name, diamonds=diamonds)

# ==================== GROQ AI ====================
groq_client = Groq(api_key=GROQ_API_KEY)
user_ai_history: dict = {}

FF_SYSTEM_PROMPT = """Sen Muzon Almaz Bot AI yordamchisisiz.
- O'zbek tilida javob ber (foydalanuvchi rus yozsa ruscha javob ber)
- Qisqa, aniq, qiziqarli, emoji ko'p ishlatib javob ber 🎮💎🔥
- BARCHA savollarga javob ber — Free Fire, hayot, texnologiya, o'yin, va h.k.
- Free Fire bo'yicha: taktika, qurol, sensitivity, DPI, grafika, FPS aniq raqamlar ber
- Bot haqida: har 5 daqiqada +0.5 almaz, referal +9 almaz, 100 almaz yechish, kunlik bonus +5 almaz
- Foydalanuvchiga har doim do'stona, qiziqarli, motivatsion munosabatda bo'l
- Agar bilmasang: dono va ijodiy javob ber, hech qachon 'bilmayman' dema"""

def ai_resp(uid, msg):
    if uid not in user_ai_history: user_ai_history[uid] = []
    h = user_ai_history[uid]
    h.append({"role": "user", "content": msg})
    if len(h) > 20: h = h[-20:]; user_ai_history[uid] = h
    try:
        r = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "system", "content": FF_SYSTEM_PROMPT}] + h,
            temperature=0.7, max_tokens=1024)
        ans = r.choices[0].message.content
        h.append({"role": "assistant", "content": ans})
        return ans
    except Exception as e: return f"❌ AI xatosi: {e}"

# ==================== FIREBASE ====================
import json as _json

# ===== 3 TA FIREBASE — AVTOMATIK ALMASHTIRISH =====
_FB_KEYS = [
    {"type": "service_account", "project_id": "almaz-bot-1-e35fb", "private_key_id": "b9501f7fa4d4b65915d72acef3dcacafb2e014fb", "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDSki9j80x9Qwm1\nV5NEsMjaLMNDmDyzQhRsLTVUsHk8o7CySmJweUbb03tv7NQPyAgTLMoAbuDq/PUx\n7rYWasq+Vg9i3QY6HwcxLe6b9f3xcyS949/pBE3DP5Gbjl+/j2zNSUJQCer3yHpO\n3yHFCocmFPL/0xyUVXCC/tYjWiHqxfKxOjrI6par8XMUNjy3z8FDiREaZElE41MC\napHPxQHs0aYTXKjckO99IjvufCaa+8JMtv7x+4YZXc1FOw+QtLrWFrdWLqsA4BPW\nHnGw8t4q+izVS8rVVyrllbn8YfDrYi2NPZpsyFfDVsf6OoanvB0NqhY18MClXT1P\nCV2Re6RJAgMBAAECggEAZZmmZxYeCnR9qzN5udOI3ghqIOPEKgQQwY9go5/Qp4sd\ntzD/5WAG6gtVDFCbk4/DIaljQCk/ufJaxoB0+EUH1SXGH8AggIu3Fyof7r2XDViu\n2jaos5BhivtRoNpl5ZJo/3ZBGkhmyK7BIOw1qZKmWiASjZBJwmKlOneGUCFtqw59\nwZmHFu4+ivtOkvfYj6YvJS10MemVktIPrhkNQDt7OQa5QTEK4S/S5R7ZnKxDC48R\nCe7NFDMX4D4lBGqo32DGsOrbsh6+N6vNG3/MqXXuLPMLBNS4CI1RDAGveQsssDTF\nS/Lh0Ti2Q7nyJDcnlJyAWjvQb8GBr+wNYNeGFd5JbwKBgQD+xEu1Ss0GLFUdHY4J\nVGEpqc8YoXm/8Dd6qpkSmWnpBAWMdvuTVKHv7rfoUn0VNKuIysjkjPDvLeZzKLtt\nxa+1TvurQwRALVmh9qVZshLhZSh955FBqc35QWqSoU6YBY6szrVhuAPIpW72pvPk\nzxaEO4ONP1OBCQZQhd50lTcTjwKBgQDTlx9bim89HD+lorumiuFxvvATWOc8z3d1\nGpzPmt3puBkA3/0Ri8gOmDm0pRnfCpygp9TotPxO2UAnLB0lD7gRGmZDkUHy7Lw2\n7vLlq5bPCWaTooJQ4Mjye9FDPWAGO6IpzVmWeXInBq9pW7emkF8PFPKAkDxa2Gyg\nkr2aDXr+pwKBgQCB4onGj7AfKZLrGRpE32P53bzbjdeIZ2uhekA4H0bDqW06w55W\n6pr0u/u+0e87VHLvdpMdEk3zYq9OnsGPoW2HPhFIqw4LuhMsY5bBN+wwRWZzag/A\nLlX4ccVnpB1xm8O1jl0iyLIFJXKBBXTqfjm4iK704AgujO9PNjDHtxsxOQKBgFQu\neeFXsG4lwQTLO9FEy/EPQEDSTB2bhTFoBx9pxARqpDf+5ZaHgG6eDcdbMHHWrP4W\nB9UVvJQ6RxXOrUHDgT38vNcBAbX+jdtlMepCXFu+p7rxGtvGsuwWaulPj9aq/xeW\nhaAibVItjLhkLyrroYZElT6lI/4YwQ8Zkqmp11ddAoGAVvXTSDkzV4mkrxZCT/M4\n2PEKso84r+yxVWrZykadd4CPPCXsQW55709usHYW2Lv+eBYIgAyRw6a+Y4D9g45B\nuIkZSJ/n3kTZHltCfH8/+veRhD6KXt8BPlOUkig0nQaX2pcND1Ozev1xQJxKdtZc\nLlBvq5ueL8zbJ88pl07Mh4c=\n-----END PRIVATE KEY-----\n", "client_email": "firebase-adminsdk-fbsvc@almaz-bot-1-e35fb.iam.gserviceaccount.com", "client_id": "107565744431103304068", "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token", "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs", "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/firebase-adminsdk-fbsvc%40almaz-bot-1-e35fb.iam.gserviceaccount.com", "universe_domain": "googleapis.com"},
    {"type": "service_account", "project_id": "almaz-bot-2", "private_key_id": "1d3ca9a1638c992ffa1b8b98c28a302139520dcb", "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQDEjGrKW6TZXBVP\nxTmV7baLQj8GP87QAbLjDMD/Zlvp2wtbt1NvUcZTDdWxivTZTCc9Dz9ClID+Qhxe\no7qqvlnAi7vHj/FM822GlbKHzAXD6X4mdMz+G6QYURzoaC+BEoekenyBZGsVhaAb\ncy0hi5lJ66UYeRnNpIcQa61tyFGZl7jNPang66RiTcB3g3pzKhT+aahrqcsLWF9y\nedBi3rdmk+6Np7ZsPCYHNvW+EsgLq8RI65yyC5oohrW/l8JDiHDxzFxQINOAgvZ5\n6vqhk65RON/kuFIDRPKEzpIi2zK2xvWKjmzzVt9leW1rLdXdkYyXXTqMCxmI9JhM\n3kFRwgF7AgMBAAECggEASgMQQZQh7uGgetHrPdxuRWFURz+m2qgRGzOVx3bdfKHJ\n1KcjiYMzGdpXUkxfqCXnjrQbn7A5JMVzVmX0KFCWjo1v0BWRiWcPIsNjH4TB1QSr\nRsLr4HI7KBb/OjrlTIbUQikHklfkhQ20/TExWPTu66mLGTyc7VWbsKDDhVgN9jZD\n9kOexzv+4kayMKeo2ULautAtRAo8UC8n1jqKs2U90Lhkil/f6A0shY/0F3u93XZL\nwgTtXZCnKNLDwFPfSvRZ4hRgnzTnDL3FPxo/woq1Q8XOiCQsyzO9g0uIoMk9H6fM\nFgm/eyebiTj4+R0IuuTvj5cJNw4/HJAtsLtTlQN6bQKBgQD/jdwgPGDhXU2+iriw\nqtnvo+TAdCidqvEfM3QEjy946miWg3Go1X+QIakKt6+48BmTI3SHbBXr3Dni/wyk\n9n17SO6WmxZWS7ewL42LaVkt7RBuBuG78cIIGGDfiIpucPlnm6GOaSqPmPNnLXFj\nFciNQy9lZxpEQnZ3fY3Zl4UpHwKBgQDE5DQA0FtAGWSv2icXOIJ6TgkmjsOsGqR8\nJLY2UiW0xflSFoUjEVV5IPk1ZHxd0vtEXsQTYAHSEisX5negdCN/5CB4nx8pHjE4\nJHnmhrwZM7f5JDWQ1MOvXLpWUAB3lUziq46TKuh1EoNF/XETrDCvaBxLDsyTioS5\nF6B8DkrwJQKBgQDJ9AKEWxK4pnJ85MWln68QqTVqPaGnT+KzJIdH3xvF84DpiUC2\nCtp/PYqIFLdCcEPVuowpROph9SytzZ7hcoWhevZJgI/7bGTiUAIMrRkzqQd12+xi\nCWCr4xATNqUnOBJwpVXb5BIlXtrjq87SXfGaaQC4ouzoCpnyPf9ueEZcQwKBgAya\nWuXOcHja50IGYcgvutJfWmCYdNf4YJz9sJgri/RVU884V89V1bXKMYmEZB2RWroW\notBmrdcniJCgFPo1VOxjytxNuy3jm9zvIMprx3CJifYtpiweImSAOAE8X7tH2EMO\nHjM3ZOfRhoudXHaY6AjiTiVTzi6HiFVcuM4YEB3tAoGBAJRweHx3yvrO2sOOYSeH\n8VBWB2gN/Kaax6ZMLVRBp+08KOo4WXsl/dUej6JtVYazSkTh3K++Fx1gZwemH9Qa\n1MfgSU44yHHIG3xexLjalcoasX6Lz5xLAjQ7+T6kr+kpyWfCO8mXfsENlsoQobT8\nwCP1ljs3njQ77yqPbgfrByrS\n-----END PRIVATE KEY-----\n", "client_email": "firebase-adminsdk-fbsvc@almaz-bot-2.iam.gserviceaccount.com", "client_id": "109436841748361470598", "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token", "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs", "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/firebase-adminsdk-fbsvc%40almaz-bot-2.iam.gserviceaccount.com", "universe_domain": "googleapis.com"},
    {"type": "service_account", "project_id": "almaz-bot-3", "private_key_id": "1087e567cbb5e1cd0c3e4fd3c3dfe7c67b836c9d", "private_key": "-----BEGIN PRIVATE KEY-----\nMIIEvAIBADANBgkqhkiG9w0BAQEFAASCBKYwggSiAgEAAoIBAQC6v3RoKjNrt5xW\nufyOo13PWVccD9w90RUvmPY5/vZxT1NWZjf7NP3HfjK/vr9LKytdMvBkVMgqIk5B\nHC7PTme4eYwmYbGMWXhf3onlU3gjhCo9RN9JZwK9pZWAo2ILclcFA+bYnnbVYgFv\ncJHZESBVQAf9ZSDjOpYDuRckOQg+ngIq0Z4/JKEwXV6ZC76lltJzXLNQOxYPZaJ3\nUWJAad/yQeiY+9RvwlRAMZnJBPQrrF9NpZIovobaEppNzJJCXJQqkh4r6DqJnZqU\np5h21cEqU0z5PoOuLyLyBR4lkN3pDGrQ7Z+NeKvVCbYsCgzkAkQLeHd30di7WrTr\nNfeojogtAgMBAAECggEADXKQcBjL25+c6Sza6C2Q6Ye6K1nkBuqJr0QBRRNcTTQE\nYQYa1WLPPICUqHSUo1XQOVWb9GmbgVc3kd4067YuZ10PT8s8pQnjTmoAvYwJbGtN\nvFw7hPZfPudP0PPS8VaSOBj8FFCy53I3fr4ZLouaa7Eg8ikIWXyERW/cX/4gXxvT\nh9c7wk9ac53xQKXMNjYBsSiFXBuAS/oPIQpQWDcGfmVkr9nHY15JysvMewCs9Ev7\nr8hrNnCXNKO2oLdbjWb9USxEcoaIIagwuNlP8zUuGGwytuOrqwaF1tYFLiRrUKrQ\nWo26t31C2NmZbvVUYtV8iG5KA322+YnylIesH3ojwQKBgQDz85974Jo/gyYRhfZs\ntiTyUjhTAy0jSjZ9qBWbCrsZ0juBv/GKYTOTD6N1KDY4Qrlq5rwOAQREV8BGZrE4\nsrGjKH/6IcD2okggL3NyooqOloSZEbrO2m/Szj4BwI9aHORhAVjKpLBXMOcMEGrZ\nvYZcSk3P57c/FppyVnoTIrZAQQKBgQDD+JTsmH8Hq7PwKPSJOZnHVIPVnUc1x1km\nyLoi/gGfjAVruvL6SzjccZPdVSqu5Hatn7A4H6fV3oDbMiSt29qVpi/xP+YNm1hV\nI8t6RodQDfCSZxtqXS66WOtVLmNxz25oXmEUeUEQU3KRH+Ek5uM5TeBokXYS/dA+\nG19F5lIM7QKBgE9Edyr6ZUSD6efBvru+R60ReEnI+26/G4ujBTo2t2sBe+KCKwsK\n4IZFi5hy84M+cx9AUBTA0dEfLlPx5F4G+l+ItmTheODrBEKpCHtUQ29nizhtoWS7\nZ6B48X8CQdJHFxJKLL7T2pTKSBkMcJvF0JXGcxg+M7XlM1Q5szrqiYvBAoGAHi+5\nSOSIlLbnJbQ5TrX3sROcpxft8yO84NOEkIVN3LSl1R1b9iAGJza7jxliVMROX5o8\ne7iskq4ObTVBHyLBfdG2itPL7QajyaGU40Xf6/3ps7N8Lpsh6oRt45YcrVhFaoA3\nNf8jfY9NE3u0o4mJMLeFPLZDWNON8zMmLs82jlUCgYBRjiMvO5OkyWv88SWhPKmB\ngi+gA/AM8L9u6hbxF/IlBls3wHqB97uU/fSxEnhKVatW+bOaHTVe3vYeUrPQLxe9\n5AYjjPosmIQ5q0/8b7GQ47XNnpTZQ8N+UvI1PxXC9Dp+s+v3fEXGTNaN99Ait2hP\nyatU6Y4Ka43mYXTqKjOlLA==\n-----END PRIVATE KEY-----\n", "client_email": "firebase-adminsdk-fbsvc@almaz-bot-3.iam.gserviceaccount.com", "client_id": "109841416145010385653", "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token", "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs", "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/firebase-adminsdk-fbsvc%40almaz-bot-3.iam.gserviceaccount.com", "universe_domain": "googleapis.com"},
]

_current_fb_index = 0
_fb_apps = []
_fb_dbs  = []

def _init_firebase():
    global _fb_apps, _fb_dbs
    for i, key_dict in enumerate(_FB_KEYS):
        try:
            app = firebase_admin.initialize_app(
                credentials.Certificate(key_dict),
                name=f"app_{i}"
            )
            _fb_apps.append(app)
            _fb_dbs.append(firestore.client(app=app))
            logger.info(f"Firebase {i+1} ulandi: {key_dict['project_id']}")
        except Exception as e:
            logger.error(f"Firebase {i+1} xato: {e}")

_init_firebase()

def get_db():
    global _current_fb_index
    return _fb_dbs[_current_fb_index]

def switch_firebase():
    global _current_fb_index
    _current_fb_index = (_current_fb_index + 1) % len(_fb_dbs)
    logger.warning(f"Firebase {_current_fb_index+1} ga o'tildi!")

def db_op(func):
    """Firebase quota xatosida avtomatik keyingi bazaga o'tish"""
    import functools
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        for attempt in range(len(_fb_dbs)):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if "Quota exceeded" in str(e) or "429" in str(e) or "ResourceExhausted" in str(e):
                    logger.warning(f"Quota tugadi! Keyingi Firebase ga o'tilmoqda...")
                    switch_firebase()
                else:
                    raise
        raise Exception("Barcha Firebase bazalari quota tugadi!")
    return wrapper

db = None  # db endi get_db() orqali ishlatiladi

def uref(uid): 
    return get_db().collection("users").document(str(uid))
def now_ts(): return datetime.now(timezone.utc)

async def check_subs(bot, uid):
    ns = []
    for ch in REQUIRED_CHANNELS:
        try:
            m = await bot.get_chat_member(ch, uid)
            if m.status in ("left", "kicked", "banned"): ns.append(ch)
        except: ns.append(ch)
    return ns

# Firebase cache — so'rovlarni kamaytirish
_user_cache = {}
_cache_time = {}
CACHE_TTL = 30  # 30 soniya cache

def get_user(uid):
    import time as _time
    now = _time.time()
    if uid in _user_cache and now - _cache_time.get(uid, 0) < CACHE_TTL:
        return _user_cache[uid]
    d = uref(uid).get()
    result = d.to_dict() if d.exists else None
    _user_cache[uid] = result
    _cache_time[uid] = now
    return result

def invalidate_cache(uid):
    _user_cache.pop(uid, None)
    _cache_time.pop(uid, None)

def create_user(uid, full_name, username, phone, ff_id, ref_by=None):
    uref(uid).set({
        "user_id": uid, "full_name": full_name, "username": username or "",
        "phone": phone, "ff_id": ff_id, "diamonds": 0.0,
        "last_earn_time": None, "last_daily": None, "last_game": None,
        "last_seen": now_ts(), "miss_you_sent": False,
        "referred_by": ref_by, "referral_count": 0, "referral_earnings": 0.0,
        "joined_at": now_ts(), "is_banned": False, "ai_chat_mode": False,
        "total_earned": 0.0, "game_wins": 0, "game_losses": 0, "review_left": False,
    })
    invalidate_cache(uid)
    if ref_by:
        try:
            if uref(ref_by).get().exists:
                uref(ref_by).update({
                    "diamonds": firestore.Increment(REFERRAL_BONUS),
                    "referral_count": firestore.Increment(1),
                    "referral_earnings": firestore.Increment(REFERRAL_BONUS),
                    "total_earned": firestore.Increment(REFERRAL_BONUS),
                })
        except Exception as e: logger.error(f"Referal: {e}")

def update_last_seen(uid):
    try:
        uref(uid).update({"last_seen": now_ts(), "miss_you_sent": False})
        invalidate_cache(uid)
    except: pass

def can_earn(data):
    last = data.get("last_earn_time")
    if last is None: return True, 0
    try:
        la = last if (hasattr(last, 'tzinfo') and last.tzinfo) else datetime.fromtimestamp(last.timestamp(), tz=timezone.utc)
        el = (now_ts() - la).total_seconds()
        if el >= EARN_COOLDOWN: return True, 0
        return False, int(EARN_COOLDOWN - el)
    except: return True, 0

def can_daily(data):
    last = data.get("last_daily")
    if last is None: return True
    try:
        la = last if (hasattr(last, 'tzinfo') and last.tzinfo) else datetime.fromtimestamp(last.timestamp(), tz=timezone.utc)
        return (now_ts() - la).total_seconds() >= 86400
    except: return True

def can_game(data):
    last = data.get("last_game")
    if last is None: return True, 0
    try:
        la = last if (hasattr(last, 'tzinfo') and last.tzinfo) else datetime.fromtimestamp(last.timestamp(), tz=timezone.utc)
        el = (now_ts() - la).total_seconds()
        if el >= GAME_COOLDOWN: return True, 0
        return False, int(GAME_COOLDOWN - el)
    except: return True, 0

# ==================== KLAVIATURA ====================
def sub_kb():
    b = []
    for i, ch in enumerate(REQUIRED_CHANNELS, 1):
        b.append([InlineKeyboardButton(f"📢 {i}-kanal", url=f"https://t.me/{ch.lstrip('@')}")])
    b.append([InlineKeyboardButton("✅ Obunani tekshirish", callback_data="check_sub")])
    return InlineKeyboardMarkup(b)

def main_menu(diamonds=0.0):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💎 Almaz ishlash", callback_data="earn")],
        [InlineKeyboardButton("💸 Almaz yechish", callback_data="withdraw")],
        [InlineKeyboardButton("🎁 Kunlik bonus",  callback_data="daily"),
         InlineKeyboardButton("🎰 Omad o'yini",   callback_data="game")],
        [InlineKeyboardButton("👤 Hisobim",        callback_data="profile"),
         InlineKeyboardButton("👥 Referal",        callback_data="referral")],
        [InlineKeyboardButton("📊 Statistika",     callback_data="stats"),
         InlineKeyboardButton("🏆 Reyting",        callback_data="top")],
        [InlineKeyboardButton("🎫 Promo kod",      callback_data="promo"),
         InlineKeyboardButton("💬 Izoh",           callback_data="review")],
        [InlineKeyboardButton("✅ Isbotlar",        callback_data="proofs")],
        [InlineKeyboardButton("🏆 Turnirga qatnashish", callback_data="tournament")],
        [InlineKeyboardButton("🤖 AI Maslahat",    callback_data="ai_menu"),
         InlineKeyboardButton("📱 Sozlamalar",     callback_data="phone_settings")],
    ])

def ai_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎮 O'yin maslahatlari",  callback_data="ai_tips")],
        [InlineKeyboardButton("📱 Telefon sozlamalari", callback_data="ai_phone")],
        [InlineKeyboardButton("💎 Almaz haqida",        callback_data="ai_diamonds")],
        [InlineKeyboardButton("💬 AI chat",             callback_data="ai_chat")],
        [InlineKeyboardButton("🔙 Menyu",               callback_data="menu")],
    ])

# ==================== BACKGROUND JOBS ====================
async def remind_job(context: ContextTypes.DEFAULT_TYPE):
    """Har 5 daqiqada almaz tayyor bo'lganlarga eslatma"""
    try:
        docs = get_db().collection("users").where("is_banned", "==", False).stream()
        for doc in docs:
            d = doc.to_dict()
            uid = d.get("user_id")
            if not uid: continue
            ok, _ = can_earn(d)
            if ok and d.get("last_earn_time") is not None:
                try:
                    name = d.get("full_name", "Do'st")
                    bal  = d.get("diamonds", 0)
                    _, lvl, _ = get_level(bal)
                    await context.bot.send_message(uid,
                        f"🔔 *{name}*, almaz olishga tayyor!\n\n"
                        f"💎 Balans: *{bal:.1f}* almaz\n"
                        f"🏅 {lvl}\n\n"
                        f"👇 /menu bosing!",
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("💎 Almaz olish", callback_data="earn")
                        ]]))
                except: pass
    except Exception as e: logger.error(f"Remind: {e}")

async def miss_you_job(context: ContextTypes.DEFAULT_TYPE):
    """Har MISS_YOU_INTERVAL sekundda uzoq kirmagan foydalanuvchilarga xabar"""
    try:
        docs = get_db().collection("users").where("is_banned", "==", False).stream()
        for doc in docs:
            d = doc.to_dict()
            uid = d.get("user_id")
            if not uid: continue
            if d.get("miss_you_sent", False): continue
            last_seen = d.get("last_seen")
            if last_seen is None: continue
            try:
                ls = last_seen if (hasattr(last_seen, 'tzinfo') and last_seen.tzinfo) \
                    else datetime.fromtimestamp(last_seen.timestamp(), tz=timezone.utc)
                elapsed = (now_ts() - ls).total_seconds()
                if elapsed >= MISS_YOU_MINUTES * 60:
                    name     = d.get("full_name", "Do'st")
                    diamonds = d.get("diamonds", 0)
                    _, lvl, _ = get_level(diamonds)
                    await context.bot.send_message(uid,
                        miss_msg(name, diamonds) +
                        f"\n\n🏅 Darajangiz: {lvl}\n"
                        f"💎 Balans: *{diamonds:.1f}* almaz",
                        parse_mode="Markdown",
                        reply_markup=InlineKeyboardMarkup([
                            [InlineKeyboardButton("💎 Almaz ishlash", callback_data="earn")],
                            [InlineKeyboardButton("🎁 Kunlik bonus",  callback_data="daily")],
                        ]))
                    uref(uid).update({"miss_you_sent": True})
            except: pass
    except Exception as e: logger.error(f"MissYou: {e}")

# ==================== /start ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user   = update.effective_user
    uid    = user.id
    args   = context.args
    ref_by = int(args[0]) if args and args[0].isdigit() and int(args[0]) != uid else None
    ex     = get_user(uid)
    if ex:
        if ex.get("is_banned"):
            await update.message.reply_photo(
                photo=get_photo("start"),
                caption="🚫 *Siz bloklangansiz!*\n\nMuammo bo'lsa admin bilan bog'laning:",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("📞 Adminga murojaat", url="https://t.me/Muzonoken")
                ]]))
            return ConversationHandler.END
        update_last_seen(uid)
        ns = await check_subs(context.bot, uid)
        if ns:
            await send_photo(update.message, "start", "📢 Kanallarga obuna bo'ling:", sub_kb())
            return ConversationHandler.END
        d = ex.get("diamonds", 0)
        _, lvl, _ = get_level(d)
        ok, sl = can_earn(ex)
        earn_st = "✅ Almaz olishga tayyor!" if ok else f"⏳ {sl//60}:{sl%60:02d} qoldi"
        await send_photo(update.message, "start",
            f"{greet(user.first_name)}\n\n"
            f"{lvl} | 💎 *{d:.1f}* almaz\n"
            f"💡 {earn_st}\n\n"
            f"Asosiy menyu:", main_menu(d))
        return ConversationHandler.END
    context.user_data["ref_by"] = ref_by
    btn = KeyboardButton("📱 Raqamni yuborish", request_contact=True)
    await send_photo(update.message, "start",
        "🎮 *MUZON ALMAZ BOT*\n\n"
        "💎 Har 5 daqiqada +0.5 almaz!\n"
        "🎁 Kunlik bonus +5 almaz!\n"
        "🎰 Omad o'yini!\n"
        "👥 Referal +9 almaz!\n"
        "💸 100 almaz yechib olish!\n"
        "🏅 5 daraja tizimi!\n"
        "🤖 AI Free Fire maslahat!\n\n"
        "📱 *1-qadam:* Telefon raqamingizni yuboring:",
        ReplyKeyboardMarkup([[btn]], resize_keyboard=True, one_time_keyboard=True))
    return PHONE

async def phone_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["phone"] = update.message.contact.phone_number
    await update.message.reply_text(
        "✅ Telefon qabul qilindi!\n\n"
        "🎮 *2-qadam:* Free Fire ID yozing:\n\n"
        "📌 FF ID: O'yinda Profil → ID raqam\n"
        "Masalan: `123456789`",
        parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
    return FF_ID

async def ff_id_received(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user  = update.effective_user
    ff_id = update.message.text.strip()
    if not ff_id.isdigit():
        await update.message.reply_text("❌ FF ID faqat raqam bo'lishi kerak! Qayta kiriting:")
        return FF_ID
    phone  = context.user_data.get("phone")
    ref_by = context.user_data.get("ref_by")
    create_user(user.id, user.full_name, user.username, phone, ff_id, ref_by)
    if ref_by:
        try:
            await context.bot.send_message(ref_by,
                f"🎉 *{user.first_name}* botga qo'shildi!\n"
                f"💎 *+{REFERRAL_BONUS} almaz* hisobingizga tushdi!",
                parse_mode="Markdown")
        except: pass
    ns = await check_subs(context.bot, user.id)
    if ns:
        await send_photo(update.message, "start",
            "✅ Ro'yxatdan o'tdingiz!\n\n📢 Kanallarga obuna bo'ling:", sub_kb())
        return ConversationHandler.END
    await send_photo(update.message, "start",
        f"🎉 *Ro'yxatdan muvaffaqiyatli o'tdingiz!*\n\n"
        f"{greet(user.first_name)}\n\n"
        f"🎮 FF ID: `{ff_id}`\n"
        f"🥉 Daraja: Bronza\n\n"
        f"👇 Asosiy menyu:", main_menu(0))
    return ConversationHandler.END

# ==================== PROFIL TAHRIRLASH ====================
async def edit_profile_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    await send_photo(q, "profile",
        "✏️ *Profil Tahrirlash*\n\nQaysi ma'lumotni o'zgartirmoqchisiz?",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("🎮 FF ID o'zgartirish", callback_data="edit_ff_id")],
            [InlineKeyboardButton("📛 Ism o'zgartirish",   callback_data="edit_name")],
            [InlineKeyboardButton("🔙 Orqaga",             callback_data="profile")],
        ]), edit=True)

async def edit_ff_id_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    context.user_data["edit_mode"] = "ff_id"
    await q.message.reply_text(
        "🎮 Yangi Free Fire ID raqamingizni yozing:\nMasalan: `987654321`",
        parse_mode="Markdown")

async def edit_name_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    context.user_data["edit_mode"] = "name"
    await q.message.reply_text("📛 Yangi ismingizni yozing:")

async def handle_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    text = update.message.text.strip()
    mode = context.user_data.pop("edit_mode", None)
    if not mode: return False
    if mode == "ff_id":
        if not text.isdigit():
            await update.message.reply_text("❌ FF ID faqat raqam bo'lishi kerak!")
            context.user_data["edit_mode"] = "ff_id"
            return True
        uref(uid).update({"ff_id": text})
        await update.message.reply_text(
            f"✅ FF ID yangilandi: `{text}`", parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Profil", callback_data="profile")]]))
    elif mode == "name":
        uref(uid).update({"full_name": text})
        await update.message.reply_text(
            f"✅ Ism yangilandi: *{text}*", parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Profil", callback_data="profile")]]))
    return True

# ==================== CALLBACKS ====================
async def check_sub_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    ns  = await check_subs(context.bot, uid)
    data = get_user(uid)
    d = data.get("diamonds", 0) if data else 0
    if ns:
        await send_photo(q, "start",
            "❌ Hali obuna bo'lmadingiz:\n" + "\n".join(f"• {c}" for c in ns),
            sub_kb(), edit=True)
    else:
        update_last_seen(uid)
        await send_photo(q, "start", "✅ *Obuna tasdiqlandi!*\n\nAsosiy menyu:", main_menu(d), edit=True)

async def earn_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; uid = q.from_user.id; await q.answer()
    data = get_user(uid)
    if not data: await q.answer("❌ /start bosing", show_alert=True); return
    ns = await check_subs(context.bot, uid)
    if ns:
        await send_photo(q, "earn", "📢 Avval kanallarga obuna bo'ling:", sub_kb(), edit=True); return
    update_last_seen(uid)
    ok, sl   = can_earn(data)
    name     = q.from_user.first_name
    d_before = data.get("diamonds", 0)
    extra_btns = []
    if not ok:
        m, s = sl // 60, sl % 60
        cap = f"{wait_msg(name, m, s)}\n\n💎 Balans: *{d_before:.1f}* almaz"
        if d_before >= WITHDRAW_MIN:
            extra_btns.append([InlineKeyboardButton("💸 Almaz yechish 🔥", callback_data="withdraw")])
    else:
        nb = round(d_before + EARN_AMOUNT, 1)
        te = round(data.get("total_earned", 0) + EARN_AMOUNT, 1)
        uref(uid).update({"diamonds": nb, "last_earn_time": now_ts(), "total_earned": te})
        _, lvl, _ = get_level(nb)
        extra = ""
        if nb >= WITHDRAW_MIN and d_before < WITHDRAW_MIN:
            extra = "\n\n🎊 *100 ALMAZ TO'LDINGIZ! ENDI ALMAZ YECHISH MUMKIN!* 🎉💎🔥"
        cap = (f"{earn_msg(name, EARN_AMOUNT)}\n\n"
               f"💰 Balans: *{nb:.1f}* 💎\n"
               f"🏅 {lvl}\n"
               f"⏱ 5 daqiqadan so'ng qayta oling!{extra}")
        if nb >= WITHDRAW_MIN:
            extra_btns.append([InlineKeyboardButton("💸 Almaz yechish 🔥", callback_data="withdraw")])
    kb = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔄 Qayta tekshirish", callback_data="earn")]]
        + extra_btns
        + [[InlineKeyboardButton("🔙 Menyu", callback_data="menu")]]
    )
    await send_photo(q, "earn", cap, kb, edit=True)

async def daily_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; uid = q.from_user.id; await q.answer()
    data = get_user(uid)
    if not data: return
    update_last_seen(uid)
    name = q.from_user.first_name
    if not can_daily(data):
        cap = (f"🎁 *Kunlik bonus*\n\n"
               f"⏳ *{name}*, bugun allaqachon oldingiz!\n"
               f"Ertaga qaytib keling 🌅\n\n"
               f"💎 Balans: *{data['diamonds']:.1f}*")
    else:
        nb = round(data.get("diamonds", 0) + DAILY_BONUS, 1)
        te = round(data.get("total_earned", 0) + DAILY_BONUS, 1)
        uref(uid).update({"diamonds": nb, "last_daily": now_ts(), "total_earned": te})
        _, lvl, _ = get_level(nb)
        cap = (f"🎁 *Kunlik bonus olindi!*\n\n"
               f"🎉 *{name}*, *+{DAILY_BONUS} almaz* olindi!\n"
               f"💰 Balans: *{nb:.1f}* 💎\n"
               f"🏅 {lvl}\n\nErtaga yana keling! 🌅")
    await send_photo(q, "daily", cap,
        InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menyu", callback_data="menu")]]), edit=True)

async def game_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; uid = q.from_user.id; await q.answer()
    data = get_user(uid)
    if not data: return
    update_last_seen(uid)
    name = q.from_user.first_name
    ok, sl = can_game(data)
    if not ok:
        m, s = sl // 60, sl % 60
        cap = (f"🎰 *Omad o'yini*\n\n"
               f"⏳ *{name}*, keyingi o'yin: *{m}:{s:02d}*\n\n"
               f"💎 Balans: *{data['diamonds']:.1f}*")
        await send_photo(q, "game", cap,
            InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menyu", callback_data="menu")]]), edit=True)
        return
    d = data.get("diamonds", 0)
    if d < 5:
        await send_photo(q, "game",
            f"🎰 *Omad o'yini*\n\n❌ *{name}*, o'yin uchun kamida *5 almaz* kerak!\n💎 Sizda: *{d:.1f}*",
            InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menyu", callback_data="menu")]]), edit=True)
        return
    cap = f"🎰 *Omad o'yini*\n\n🎲 *{name}*, qancha tikmoqchisiz?\n💎 Balansingiz: *{d:.1f}* almaz"
    await send_photo(q, "game", cap, InlineKeyboardMarkup([
        [InlineKeyboardButton("5 💎",  callback_data="game_5"),
         InlineKeyboardButton("10 💎", callback_data="game_10"),
         InlineKeyboardButton("20 💎", callback_data="game_20")],
        [InlineKeyboardButton("🔙 Menyu", callback_data="menu")],
    ]), edit=True)

async def game_play_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; uid = q.from_user.id; await q.answer()
    bet  = int(q.data.replace("game_", ""))
    data = get_user(uid)
    if not data: return
    name = q.from_user.first_name
    d    = data.get("diamonds", 0)
    if d < bet: await q.answer("❌ Yetarli almaz yo'q!", show_alert=True); return
    uref(uid).update({"last_game": now_ts()})
    win = random.random() < 0.45
    if win:
        nb = round(d + bet, 1)
        uref(uid).update({"diamonds": nb, "game_wins": firestore.Increment(1),
                          "total_earned": firestore.Increment(bet)})
        cap = (f"🎰 *G'ALABA!* 🎉\n\n*{name}*, zo'r!\n"
               f"🎯 Tikdingiz: *{bet}* 💎\n🏆 Yutdingiz: *+{bet}* 💎\n\n"
               f"💰 Balans: *{nb:.1f}* 💎\nOmadingiz bor! 🍀")
    else:
        nb = round(d - bet, 1)
        uref(uid).update({"diamonds": firestore.Increment(-bet), "game_losses": firestore.Increment(1)})
        cap = (f"🎰 *Yutqazdingiz!* 😢\n\n*{name}*, omadsizlik...\n"
               f"💸 Yoqotdingiz: *{bet}* 💎\n\n"
               f"💰 Balans: *{nb:.1f}* 💎\nOmad keyingisida! 💪")
    await send_photo(q, "game", cap, InlineKeyboardMarkup([
        [InlineKeyboardButton("🎰 Qayta o'ynash", callback_data="game")],
        [InlineKeyboardButton("🔙 Menyu",         callback_data="menu")],
    ]), edit=True)

async def stats_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; uid = q.from_user.id; await q.answer()
    data = get_user(uid)
    if not data: return
    update_last_seen(uid)
    joined = data.get("joined_at")
    try:
        if hasattr(joined, 'tzinfo') and joined.tzinfo:
            days = (now_ts() - joined).days
        else:
            days = (now_ts() - datetime.fromtimestamp(joined.timestamp(), tz=timezone.utc)).days
    except: days = 0
    d       = data.get("diamonds", 0)
    total   = data.get("total_earned", 0)
    wins    = data.get("game_wins", 0)
    losses  = data.get("game_losses", 0)
    refs    = data.get("referral_count", 0)
    _, lvl, ldesc = get_level(d)
    progress = min(int(d / WITHDRAW_MIN * 10), 10)
    bar = "🟩" * progress + "⬜" * (10 - progress)
    cap = (f"📊 *Shaxsiy Statistika*\n\n"
           f"📅 Botda: *{days}* kun\n"
           f"💎 Joriy balans: *{d:.1f}*\n"
           f"💰 Jami topilgan: *{total:.1f}*\n\n"
           f"🏅 Daraja: {lvl} — {ldesc}\n"
           f"📊 Progress: {bar} {d:.1f}/100\n\n"
           f"🎰 O'yinlar: ✅ {wins} | ❌ {losses}\n"
           f"👥 Referallar: *{refs}* ta\n"
           f"🎁 Referal daromad: *{data.get('referral_earnings', 0):.1f}* 💎")
    await send_photo(q, "stats", cap,
        InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menyu", callback_data="menu")]]), edit=True)

async def profile_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; uid = q.from_user.id; await q.answer()
    data = get_user(uid)
    if not data: return
    update_last_seen(uid)
    ok, sl = can_earn(data)
    es  = "✅ Tayyor!" if ok else f"⏳ {sl//60}:{sl%60:02d}"
    d   = data.get("diamonds", 0)
    progress = min(int(d / WITHDRAW_MIN * 10), 10)
    bar = "🟩" * progress + "⬜" * (10 - progress)
    _, lvl, _ = get_level(d)
    j = data.get("joined_at")
    cap = (f"👤 *Profilingiz*\n\n"
           f"📛 {data['full_name']}\n"
           f"📱 {data['phone']}\n"
           f"🎮 FF ID: `{data.get('ff_id', '—')}`\n"
           f"💎 Balans: *{d:.1f}* almaz\n"
           f"🏅 Daraja: {lvl}\n"
           f"📊 {bar} {d:.1f}/100\n"
           f"💡 Almaz: {es}\n"
           f"👥 Referallar: *{data.get('referral_count', 0)}* ta\n"
           f"🎁 Referal: *{data.get('referral_earnings', 0):.1f}* 💎\n"
           f"📅 {j.strftime('%d.%m.%Y') if j else '—'}")
    await send_photo(q, "profile", cap, InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ Profilni tahrirlash", callback_data="edit_profile")],
        [InlineKeyboardButton("🔙 Menyu", callback_data="menu")],
    ]), edit=True)

async def referral_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; uid = q.from_user.id; await q.answer()
    data = get_user(uid)
    if not data: return
    update_last_seen(uid)
    bi   = await context.bot.get_me()
    link = f"https://t.me/{bi.username}?start={uid}"
    cap  = (f"👥 *Referal tizimi*\n\n"
            f"Do'stingizni taklif qiling!\n"
            f"Ro'yxatdan o'tsa → *+{REFERRAL_BONUS} 💎* avtomatik!\n\n"
            f"🔗 Havolangiz:\n`{link}`\n\n"
            f"✅ Taklif: *{data.get('referral_count', 0)}* ta\n"
            f"💰 Daromad: *{data.get('referral_earnings', 0):.1f}* 💎")
    await send_photo(q, "referral", cap, InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 Ulashish", switch_inline_query=f"Muzon almaz botiga qo'shiling! {link}")],
        [InlineKeyboardButton("🔙 Menyu", callback_data="menu")],
    ]), edit=True)

async def top_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    update_last_seen(q.from_user.id)
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    docs   = get_db().collection("users").order_by("diamonds", direction=firestore.Query.DESCENDING).limit(10).stream()
    lines  = ["🏆 *Top 10 o'yinchi*\n"]
    for i, doc in enumerate(docs):
        d = doc.to_dict()
        _, lvl, _ = get_level(d.get("diamonds", 0))
        lines.append(f"{medals[i]} {d.get('full_name', '?')[:12]} {lvl} — {d.get('diamonds', 0):.1f} 💎")
    await send_photo(q, "top", "\n".join(lines),
        InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menyu", callback_data="menu")]]), edit=True)

async def proofs_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    cap = (f"✅ *Isbotlar kanali*\n\n"
           f"Almaz to'lovi tasdiqlangan foydalanuvchilarni\n"
           f"ko'rish uchun kanalga o'ting!\n\n"
           f"📢 {PROOF_CHANNEL_LINK}")
    await send_photo(q, "proof", cap, InlineKeyboardMarkup([
        [InlineKeyboardButton("💎 Isbotlar kanaliga o'tish", url=PROOF_CHANNEL_LINK)],
        [InlineKeyboardButton("🔙 Menyu", callback_data="menu")],
    ]), edit=True)

TOURNAMENT_MAX = 45  # Maksimal ishtirokchilar soni

def get_active_tournament():
    """Faol turnirni olish"""
    docs = list(get_db().collection("tournaments")
                .where("status", "==", "active").limit(1).stream())
    return docs[0].to_dict() if docs else None

def get_tournament_participants(tour_id):
    """Turnir ishtirokchilari"""
    docs = get_db().collection("tournaments").document(tour_id)             .collection("participants").stream()
    return [d.to_dict() for d in docs]

async def tournament_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; uid = q.from_user.id; await q.answer()
    data = get_user(uid)
    if not data: return
    update_last_seen(uid)

    tour = get_active_tournament()
    if not tour:
        await send_photo(q, "top",
            "🏆 *Turnir*\n\nHozirda faol turnir yo'q.\n\n"
            "📢 Yangi turnir e'lon qilinsa xabar beramiz!",
            InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menyu", callback_data="menu")]]),
            edit=True)
        return

    tour_id    = tour.get("tour_id")
    tour_name  = tour.get("name", "Muzon FF Turniri")
    max_slots  = tour.get("max_slots", TOURNAMENT_MAX)
    prize      = tour.get("prize", TOURNAMENT_PRIZE)
    participants = get_tournament_participants(tour_id)
    current    = len(participants)
    remaining  = max_slots - current

    # Foydalanuvchi allaqachon yozilganmi?
    already = any(p.get("user_id") == uid for p in participants)

    d     = data.get("diamonds", 0)
    uname = data.get("username", "")
    ff_id = data.get("ff_id", "—")
    name  = data.get("full_name", q.from_user.first_name)
    _, lvl, _ = get_level(d)

    # Progress bar
    filled = min(int(current / max_slots * 10), 10)
    bar = "🟥" * filled + "⬜" * (10 - filled)

    if already:
        cap = (f"🏆 *{tour_name}*\n\n"
               f"✅ Siz bu turnirga yozilgansiz!\n\n"
               f"👥 Ishtirokchilar: *{current}/{max_slots}*\n"
               f"📊 {bar}\n"
               f"🏅 O'rin qoldi: *{remaining}*\n"
               f"🎁 Sovrin: *{int(prize)} almaz*\n\n"
               f"⏳ Turnir boshlanishini kuting!")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menyu", callback_data="menu")]])
    elif current >= max_slots:
        cap = (f"🏆 *{tour_name}*\n\n"
               f"😔 Turnir to'ldi! Barcha o'rinlar band.\n\n"
               f"👥 *{current}/{max_slots}* ishtirokchi\n"
               f"📊 {bar}\n\n"
               f"📢 Keyingi turnir uchun botda qoling!")
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menyu", callback_data="menu")]])
    else:
        cap = (f"🏆 *{tour_name}*\n\n"
               f"👥 Ishtirokchilar: *{current}/{max_slots}*\n"
               f"📊 {bar}\n"
               f"🔥 O'rin qoldi: *{remaining}* ta!\n"
               f"🎁 Sovrin: *{int(prize)} almaz*\n\n"
               f"👤 Sizning ma'lumotlaringiz:\n"
               f"📛 Ism: *{name}*\n"
               f"🆔 TG ID: `{uid}`\n"
               f"🎮 FF ID: `{ff_id}`\n"
               f"🏅 Daraja: {lvl}\n\n"
               f"👇 Qatnashish uchun tugmani bosing!")
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"✅ Turnirga yozilish ({current}/{max_slots})",
                callback_data=f"tournament_join_{tour_id}")],
            [InlineKeyboardButton("🔙 Menyu", callback_data="menu")],
        ])
    await send_photo(q, "top", cap, kb, edit=True)

async def tournament_join_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; uid = q.from_user.id; await q.answer()
    data = get_user(uid)
    if not data: return
    update_last_seen(uid)

    # tour_id ni callback_data dan olish
    parts = q.data.split("_")
    tour_id = parts[-1] if len(parts) > 2 else None

    if not tour_id:
        await q.answer("❌ Turnir topilmadi!", show_alert=True); return

    tour = get_db().collection("tournaments").document(tour_id).get()
    if not tour.exists:
        await q.answer("❌ Turnir topilmadi!", show_alert=True); return
    tour_data  = tour.to_dict()
    tour_name  = tour_data.get("name", "Muzon FF Turniri")
    max_slots  = tour_data.get("max_slots", TOURNAMENT_MAX)
    prize      = tour_data.get("prize", TOURNAMENT_PRIZE)

    participants = get_tournament_participants(tour_id)
    current = len(participants)

    # Allaqachon yozilganmi?
    if any(p.get("user_id") == uid for p in participants):
        await q.answer("✅ Siz allaqachon yozilgansiz!", show_alert=True); return

    # To'ldimi?
    if current >= max_slots:
        await q.answer("😔 Turnir to'ldi!", show_alert=True); return

    name  = data.get("full_name", q.from_user.first_name)
    uname = data.get("username", "")
    ff_id = data.get("ff_id", "—")
    phone = data.get("phone", "—")
    d     = data.get("diamonds", 0)
    _, lvl, _ = get_level(d)

    # Ishtirokchini qo'shish
    participant_data = {
        "user_id":   uid,
        "full_name": name,
        "username":  uname,
        "ff_id":     ff_id,
        "phone":     phone,
        "diamonds":  d,
        "level":     lvl,
        "joined_at": now_ts(),
    }
    get_db().collection("tournaments").document(tour_id)      .collection("participants").document(str(uid)).set(participant_data)

    new_count = current + 1
    remaining = max_slots - new_count
    filled    = min(int(new_count / max_slots * 10), 10)
    bar       = "🟥" * filled + "⬜" * (10 - filled)

    # Adminga xabar
    for adm_id in ADMIN_IDS:
        try:
            await context.bot.send_message(adm_id,
                f"🏆 TURNIRGA YANGI ISHTIROKCHI!\n\n"
                f"Turnir: {tour_name}\n"
                f"👥 {new_count}/{max_slots} ({remaining} o'rin qoldi)\n"
                f"📊 {bar}\n\n"
                f"👤 Ism: {name}\n"
                f"🆔 TG ID: {uid}\n"
                f"👤 @{uname if uname else '—'}\n"
                f"📱 Tel: {phone}\n"
                f"🎮 FF ID: {ff_id}\n"
                f"🏅 {lvl}")
        except: pass

    # Turnir to'ldimi?
    if new_count >= max_slots:
        get_db().collection("tournaments").document(tour_id).update({"status": "full"})
        # Barcha ishtirokchilarga xabar
        all_p = get_tournament_participants(tour_id)
        bot_info = await context.bot.get_me()
        for p in all_p:
            try:
                await context.bot.send_message(p["user_id"],
                    f"🏆 *{tour_name} TO'LDI!*\n\n"
                    f"Barcha {max_slots} ta o'rin band bo'ldi!\n\n"
                    f"✅ Siz ishtirokchisiz!\n"
                    f"🎁 Sovrin: {int(prize)} almaz\n\n"
                    f"⏳ Turnir boshlanishi haqida xabar beramiz!",
                    parse_mode="Markdown")
            except: pass
        # Adminga ham turnir to'ldi xabari
        for adm_id in ADMIN_IDS:
            try:
                await context.bot.send_message(adm_id,
                    f"🔔 {tour_name} TO'LDI! {max_slots} ta ishtirokchi to'plandi!",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("📋 Ishtirokchilarni ko'rish",
                            callback_data="adm_tournament")
                    ]]))
            except: pass

        await send_photo(q, "top",
            f"🏆 *{tour_name}*\n\n"
            f"✅ Siz yozildingiz — {new_count}-ishtirokchi!\n\n"
            f"🎉 Turnir to'ldi! Barcha {max_slots} o'rin band!\n"
            f"🎁 Sovrin: *{int(prize)} almaz*\n\n"
            f"⏳ Turnir boshlanishi haqida xabar beramiz!",
            InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menyu", callback_data="menu")]]),
            edit=True)
    else:
        await send_photo(q, "top",
            f"✅ *Turnirga yozildingiz!*\n\n"
            f"🏆 {tour_name}\n"
            f"👥 Siz {new_count}-ishtirokchisiz!\n"
            f"📊 {bar} {new_count}/{max_slots}\n"
            f"🔥 Yana *{remaining}* o'rin bor\n"
            f"🎁 Sovrin: *{int(prize)} almaz*\n\n"
            f"⏳ Turnir boshlanishi haqida xabar beramiz!",
            InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menyu", callback_data="menu")]]),
            edit=True)

async def tour_accept_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id not in ADMIN_IDS: return
    await q.answer("✅ Qabul qilindi!")
    uid = int(q.data.replace("tour_accept_", ""))
    try:
        await context.bot.send_message(uid,
            "🏆 Tabriklaymiz! Turnirga qabul qilindingiz!\n\n"
            "Admin tez orada qo'shimcha ma'lumot yuboradi.\n"
            "📞 @Muzonoken")
    except: pass
    await q.edit_message_text(f"✅ {uid} turnirga qabul qilindi!")

async def tour_reject_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id not in ADMIN_IDS: return
    await q.answer("❌ Rad etildi!")
    uid = int(q.data.replace("tour_reject_", ""))
    try:
        await context.bot.send_message(uid,
            "❌ Afsuski turnirga qabul qilinmadingiz.\n\n"
            "Muammo bo'lsa: @Muzonoken")
    except: pass
    await q.edit_message_text(f"❌ {uid} rad etildi.")

async def promo_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    context.user_data["promo_mode"] = True
    await send_photo(q, "promo",
        "🎫 *Promo kod*\n\nPromo kodingizni yozing!\n\n📝 Masalan: `MUZON2024`",
        InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menyu", callback_data="menu")]]), edit=True)

async def review_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; uid = q.from_user.id; await q.answer()
    data = get_user(uid)
    if not data: return
    if data.get("review_left"):
        await send_photo(q, "review", "💬 *Izoh*\n\n✅ Siz allaqachon izoh qoldirdingiz!\nRahmat! 🙏",
            InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menyu", callback_data="menu")]]), edit=True)
        return
    context.user_data["review_mode"] = True
    await send_photo(q, "review",
        "💬 *Izoh qoldirish*\n\n"
        "Bot haqida fikringizni yozing!\n\n"
        "✅ Izoh uchun *+5 💎* olasiz!",
        InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menyu", callback_data="menu")]]), edit=True)

async def menu_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uid = q.from_user.id
    update_last_seen(uid)
    for k in ["ai_chat", "ai_phone_mode", "promo_mode", "review_mode", "edit_mode"]:
        context.user_data.pop(k, None)
    try: uref(uid).update({"ai_chat_mode": False})
    except: pass
    data = get_user(uid)
    d = data.get("diamonds", 0) if data else 0
    _, lvl, _ = get_level(d)
    await send_photo(q, "start",
        f"{greet(q.from_user.first_name)}\n\n{lvl} | 💎 *{d:.1f}* almaz\n\nAsosiy menyu:",
        main_menu(d), edit=True)

# ==================== ALMAZ YECHISH ====================
async def withdraw_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; uid = q.from_user.id; await q.answer()
    data = get_user(uid)
    if not data: return
    update_last_seen(uid)
    d = data.get("diamonds", 0)
    if d < WITHDRAW_MIN:
        progress = min(int(d / WITHDRAW_MIN * 10), 10)
        bar = "🟩" * progress + "⬜" * (10 - progress)
        await send_photo(q, "withdraw",
            f"❌ *Yechish uchun {int(WITHDRAW_MIN)} almaz kerak!*\n\n"
            f"💎 Sizda: *{d:.1f}* almaz\n"
            f"📊 {bar} {d:.1f}/{int(WITHDRAW_MIN)}\n"
            f"📈 Yana: *{WITHDRAW_MIN - d:.1f}* almaz kerak\n\n"
            f"💪 Almaz ishlashda davom eting!",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("💎 Almaz ishlash", callback_data="earn")],
                [InlineKeyboardButton("✅ Isbotlar",       callback_data="proofs")],
                [InlineKeyboardButton("🔙 Menyu",          callback_data="menu")],
            ]), edit=True)
        return
    amounts = [100, 200, 300, 400, 500, 600, 1000, 2000, 5000]
    btns = []
    row  = []
    for amt in amounts:
        if d >= amt:
            row.append(InlineKeyboardButton(f"💎 {amt}", callback_data=f"wd_{amt}"))
            if len(row) == 3:
                btns.append(row); row = []
    if row: btns.append(row)
    if d > 0:
        btns.append([InlineKeyboardButton(f"💎 Barchasi ({d:.1f})", callback_data="wd_all")])
    btns.append([InlineKeyboardButton("✅ Isbotlar", callback_data="proofs")])
    btns.append([InlineKeyboardButton("🔙 Menyu",   callback_data="menu")])
    await send_photo(q, "withdraw",
        f"💸 *Almaz Yechish*\n\n"
        f"💎 Sizda: *{d:.1f}* almaz\n"
        f"🎮 FF ID: `{data.get('ff_id', '—')}`\n\n"
        f"❓ *Necha almaz yechmoqchisiz?*\n"
        f"👇 Miqdorni tanlang:",
        InlineKeyboardMarkup(btns), edit=True)

async def wd_amount_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; uid = q.from_user.id; await q.answer()
    data = get_user(uid)
    if not data: return
    d   = data.get("diamonds", 0)
    raw = q.data.replace("wd_", "")
    amt = d if raw == "all" else float(raw)
    if amt > d: await q.answer("❌ Yetarli almaz yo'q!", show_alert=True); return
    context.user_data["wd_amount"] = amt
    await send_photo(q, "withdraw",
        f"💸 *Almaz Yechish Tasdiqlash*\n\n"
        f"💎 Yechiladi: *{amt:.1f}* almaz\n"
        f"🎮 FF ID: `{data.get('ff_id', '—')}`\n"
        f"📱 Tel: {data.get('phone', '—')}\n\n"
        f"⚠️ So'rov adminga yuboriladi.\n"
        f"✅ Tasdiqlangach almaz FF ga tushadi!\n\nTasdiqlaysizmi?",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Ha, tasdiqlash!", callback_data="wd_confirm")],
            [InlineKeyboardButton("🔙 Ortga",           callback_data="withdraw")],
        ]), edit=True)

async def wd_confirm_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; uid = q.from_user.id; await q.answer()
    data = get_user(uid)
    if not data: return
    amt = context.user_data.pop("wd_amount", data.get("diamonds", 0))
    if amt > data.get("diamonds", 0): await q.answer("❌ Yetarli almaz yo'q!", show_alert=True); return
    w_id = f"W{uid}_{int(time.time())}"
    get_db().collection("withdrawals").document(w_id).set({
        "w_id": w_id, "user_id": uid,
        "full_name": data.get("full_name"), "username": data.get("username"),
        "phone": data.get("phone"), "ff_id": data.get("ff_id"),
        "diamonds": amt, "status": "pending", "created_at": now_ts(),
    })
    admin_cap = (f"YANGI ALMAZ YECHISH SO'ROVI!\n\n"
                 f"Ism: {data.get('full_name')}\n"
                 f"Tel: {data.get('phone')}\n"
                 f"FF ID: {data.get('ff_id')}\n"
                 f"TG ID: {uid}\n"
                 f"Username: @{data.get('username', '—')}\n"
                 f"Miqdor: {amt:.1f} almaz\n"
                 f"So'rov: {w_id}")
    admin_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Qabul", callback_data=f"approve_{w_id}"),
        InlineKeyboardButton("❌ Rad",   callback_data=f"reject_{w_id}"),
    ]])
    for adm_id in ADMIN_IDS:
        try:
            p = get_photo("withdraw")
            await context.bot.send_photo(adm_id, photo=p, caption=admin_cap, reply_markup=admin_kb)
            if not is_url(p): p.close()
        except Exception as e: logger.error(f"Admin: {e}")
    name = q.from_user.first_name
    funny = random.choice([
        f"🎉 {name}, so'rovingiz adminga ketdi! Tez ko'radi! 😄",
        f"✅ {name}! So'rov yuborildi! Admin ko'rsin! ⏳",
        f"🚀 {name}! So'rovingiz uchib ketdi! Javob kutamiz! 🎯",
        f"💎 {name}, admin tez tasdiqlaydi! 🏆",
    ])
    await send_photo(q, "withdraw",
        f"{funny}\n\n💎 *{amt:.1f}* almaz\n🎮 FF ID: `{data.get('ff_id')}`\n\n⏳ Admin ko'rib chiqmoqda...",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Isbotlar", callback_data="proofs")],
            [InlineKeyboardButton("🔙 Menyu",   callback_data="menu")],
        ]), edit=True)

async def approve_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id not in ADMIN_IDS: await q.answer("❌", show_alert=True); return
    await q.answer("✅ Tasdiqlandi!")
    w_id  = q.data.replace("approve_", "")
    w_doc = get_db().collection("withdrawals").document(w_id).get()
    if not w_doc.exists: await q.message.reply_text("❌ Topilmadi."); return
    w = w_doc.to_dict()
    if w.get("status") != "pending": await q.message.reply_text("⚠️ Allaqachon ko'rilgan."); return
    uid = w["user_id"]
    amt = w["diamonds"]
    uref(uid).update({"diamonds": firestore.Increment(-amt)})
    get_db().collection("withdrawals").document(w_id).update({"status": "approved", "approved_at": now_ts()})
    context.user_data["proof_w_id"] = w_id
    await q.edit_message_caption(
        caption=f"TASDIQLANDI\n\n"
                f"Ism: {w.get('full_name', '—')}\n"
                f"FF ID: {w.get('ff_id', '—')}\n"
                f"Almaz: {amt:.1f}")
    await q.message.reply_text(
        f"Isbot yuborish\n\n"
        f"{w.get('full_name', 'Noma`lum')} ga {amt:.1f} almaz tasdiqlandi!\n\n"
        f"Endi isbot uchun rasm yoki video yuboring!\n"
        f"Foydalanuvchiga ham, {PROOF_CHANNEL_LINK} kanaliga ham avtomatik ketadi!\n\n"
        f"O'tkazib yuborish: /skip")

async def reject_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id not in ADMIN_IDS: await q.answer("❌", show_alert=True); return
    await q.answer("❌ Rad etildi!")
    w_id  = q.data.replace("reject_", "")
    w_doc = get_db().collection("withdrawals").document(w_id).get()
    if not w_doc.exists: return
    w = w_doc.to_dict()
    if w.get("status") != "pending": return
    get_db().collection("withdrawals").document(w_id).update({"status": "rejected", "rejected_at": now_ts()})
    try:
        await context.bot.send_message(w["user_id"],
            "Almaz yechish rad etildi\n\n"
            "Muammo bo'lsa admin bilan bog'laning: @Muzonoken")
    except: pass
    await q.edit_message_caption(
        caption=f"RAD ETILDI\n\n"
                f"Ism: {w.get('full_name', '—')}\n"
                f"Almaz: {w.get('diamonds', 0):.1f}")

# ==================== ADMIN MEDIA ====================
async def handle_admin_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if uid not in ADMIN_IDS: return
    msg = update.message
    cap = msg.caption or ""
    media_id = media_type = None
    if msg.photo:
        media_id = msg.photo[-1].file_id; media_type = "photo"
    elif msg.video:
        media_id = msg.video.file_id; media_type = "video"
    elif msg.document:
        media_id = msg.document.file_id; media_type = "document"
    if not media_id: return

    # BROADCAST
    if context.user_data.get("adm_action") == "broadcast":
        context.user_data.pop("adm_action", None)
        users = get_db().collection("users").where("is_banned", "==", False).stream()
        sent = failed = 0
        await msg.reply_text("📣 Media broadcast boshlanmoqda...")
        for doc in users:
            try:
                cid = doc.id
                txt = f"📣 {cap}" if cap else "📣"
                if media_type == "photo":
                    await context.bot.send_photo(cid, photo=media_id, caption=txt)
                elif media_type == "video":
                    await context.bot.send_video(cid, video=media_id, caption=txt)
                elif media_type == "document":
                    await context.bot.send_document(cid, document=media_id, caption=txt)
                sent += 1; await asyncio.sleep(0.05)
            except: failed += 1
        await msg.reply_text(f"✅ Tugadi! 📨 {sent} | ❌ {failed}")
        return

    # CHANNEL POST — barcha BROADCAST_CHANNELS ga post
    if context.user_data.get("adm_action") == "channel_post":
        context.user_data.pop("adm_action", None)
        sent = failed = 0
        await msg.reply_text(f"📢 Kanallarga post yuborilmoqda... ({len(BROADCAST_CHANNELS)} ta kanal)")
        for ch in BROADCAST_CHANNELS:
            try:
                txt = cap if cap else ""
                if media_type == "photo":
                    await context.bot.send_photo(ch, photo=media_id, caption=txt)
                elif media_type == "video":
                    await context.bot.send_video(ch, video=media_id, caption=txt)
                elif media_type == "document":
                    await context.bot.send_document(ch, document=media_id, caption=txt)
                else:
                    await context.bot.send_message(ch, txt)
                sent += 1
            except Exception as e:
                failed += 1
                logger.error(f"Kanal post xato {ch}: {e}")
        await msg.reply_text(
            f"✅ Kanal post tugadi!\n"
            f"✅ Yuborildi: {sent} ta\n"
            f"❌ Xato: {failed} ta")
        return


    # TURNIR BROADCAST (media)
    if context.user_data.get("adm_action") == "tour_broadcast":
        tour_id = context.user_data.pop("tour_id_msg", None)
        context.user_data.pop("adm_action", None)
        if not tour_id:
            await msg.reply_text("❌ Turnir ID topilmadi."); return
        participants = get_tournament_participants(tour_id)
        sent = failed = 0
        await msg.reply_text(f"📣 {len(participants)} ta ishtirokchiga xabar yuborilmoqda...")
        for p in participants:
            try:
                txt = cap if cap else "🏆 Turnir xabari"
                if media_type == "photo":
                    await context.bot.send_photo(p["user_id"], photo=media_id, caption=txt)
                elif media_type == "video":
                    await context.bot.send_video(p["user_id"], video=media_id, caption=txt)
                sent += 1; await asyncio.sleep(0.05)
            except: failed += 1
        await msg.reply_text(f"✅ Yuborildi: {sent} | ❌ {failed}")
        return

    # ISBOT
    w_id = context.user_data.get("proof_w_id")
    if not w_id: await msg.reply_text("❓ Avval so'rovni tasdiqlang."); return
    context.user_data.pop("proof_w_id", None)
    w_doc = get_db().collection("withdrawals").document(w_id).get()
    if not w_doc.exists: await msg.reply_text("❌ So'rov topilmadi."); return
    w        = w_doc.to_dict()
    user_id  = w.get("user_id")
    diamonds = w.get("diamonds", 0)
    bot_info = await context.bot.get_me()
    bot_username = f"@{bot_info.username}"

    # Foydalanuvchiga
    user_cap = (
        f"Tabriklaymiz! Almazingiz tasdiqlandi!\n\n"
        f"Almaz miqdori: {int(diamonds)}\n"
        f"Free fire ID raqami: {w.get('ff_id', '—')}\n\n"
        f"Rasmiy botimiz: {bot_username}\n\n"
        f"O'yinda ko'rmasangiz biroz kuting!"
    )
    try:
        if media_type == "photo":
            await context.bot.send_photo(user_id, photo=media_id, caption=user_cap)
        elif media_type == "video":
            await context.bot.send_video(user_id, video=media_id, caption=user_cap)
        elif media_type == "document":
            await context.bot.send_document(user_id, document=media_id, caption=user_cap)
    except Exception as e: logger.error(f"User xabar: {e}")

    # Isbotlar kanaliga — rasmdagidek format
    fname       = w.get("full_name", "Noaniq")
    uname       = w.get("username", "")
    uname_str   = "@" + uname if uname else "—"
    ff_id_proof = w.get("ff_id", "—")
    proof_cap = (
        f"{fname} foydalanuvchi almazi to'lab berildi.\n\n"
        f"Almaz miqdori: {int(diamonds)}\n"
        f"Free fire ID raqami: {ff_id_proof}\n\n"
        f"Rasmiy botimiz: {bot_username}"
    )
    try:
        if media_type == "photo":
            await context.bot.send_photo(PROOF_CHANNEL, photo=media_id, caption=proof_cap)
        elif media_type == "video":
            await context.bot.send_video(PROOF_CHANNEL, video=media_id, caption=proof_cap)
        elif media_type == "document":
            await context.bot.send_document(PROOF_CHANNEL, document=media_id, caption=proof_cap)
        await msg.reply_text("✅ Isbot kanaliga yuborildi va foydalanuvchiga xabar ketdi! 🎉")
    except Exception as e:
        await msg.reply_text(f"❌ Kanalga xato: {e}")

# ==================== AI CALLBACKS ====================
async def ai_menu_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    update_last_seen(q.from_user.id)
    await send_photo(q, "ai", "🤖 *AI Maslahat — Free Fire*\n\nNima haqida?", ai_kb(), edit=True)

async def ai_tips_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer("⏳...")
    ans = ai_resp(q.from_user.id, "Free Fire da g'alaba uchun eng yaxshi 5 maslahat ber. Emoji ko'p ishlatib yoz.")
    await send_photo(q, "ai", f"🎮 *Maslahatlari*\n\n{ans}",
        InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 Yangi maslahat", callback_data="ai_tips")],
            [InlineKeyboardButton("🔙 AI Menyu",       callback_data="ai_menu")],
        ]), edit=True)

async def ai_phone_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    context.user_data["ai_phone_mode"] = True
    await send_photo(q, "phone",
        "📱 *Telefon Sozlamalari*\n\nTelefoningiz modelini yozing!\n\nAI aniq sensitivity, DPI, grafika beradi! 🎯",
        InlineKeyboardMarkup([[InlineKeyboardButton("🔙 AI Menyu", callback_data="ai_menu")]]), edit=True)

async def ai_diamonds_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer("⏳...")
    ans = ai_resp(q.from_user.id, "Free Fire almaz nima va bu botda qanday ishlaydi?")
    await send_photo(q, "ai", f"💎 *Almaz haqida*\n\n{ans}",
        InlineKeyboardMarkup([[InlineKeyboardButton("🔙 AI Menyu", callback_data="ai_menu")]]), edit=True)

async def ai_chat_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    uref(q.from_user.id).update({"ai_chat_mode": True})
    context.user_data["ai_chat"] = True
    await send_photo(q, "ai", "💬 *AI Chat*\n\nFree Fire haqida savol bering! 🎮",
        InlineKeyboardMarkup([[InlineKeyboardButton("❌ Chiqish", callback_data="menu")]]), edit=True)

async def phone_settings_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query; await q.answer()
    context.user_data["ai_phone_mode"] = True
    await send_photo(q, "phone",
        "📱 *Telefon Sozlamalari*\n\nTelefoningiz modelini yozing!\n\nAI aniq sensitivity, DPI, grafika beradi! 🎯",
        InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menyu", callback_data="menu")]]), edit=True)

# ==================== MESSAGES ====================
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    text = update.message.text.strip()

    if uid in ADMIN_IDS:
        act = context.user_data.get("adm_action")
        if act: await admin_text_handler(update, context, act, text); return

    data = get_user(uid)
    if not data: await update.message.reply_text("❌ Avval /start bosing."); return

    update_last_seen(uid)

    if context.user_data.get("edit_mode"):
        handled = await handle_edit(update, context)
        if handled: return

    if context.user_data.get("promo_mode"):
        context.user_data.pop("promo_mode", None)
        pdoc = get_db().collection("promos").document(text.upper()).get()
        if not pdoc.exists: await update.message.reply_text("❌ Bunday promo kod yo'q!"); return
        p     = pdoc.to_dict()
        used  = p.get("used_by", [])
        limit = p.get("limit", 0)
        if uid in used: await update.message.reply_text("❌ Bu promo kodni allaqachon ishlatgansiz!"); return
        if limit <= len(used): await update.message.reply_text("❌ Bu promo kod tugagan!"); return
        bonus = p.get("bonus", 0)
        nb    = round(data.get("diamonds", 0) + bonus, 1)
        uref(uid).update({"diamonds": nb, "total_earned": firestore.Increment(bonus)})
        used.append(uid)
        new_used_count = len(used)
        get_db().collection("promos").document(text.upper()).update({"used_by": used})
        await send_photo(update.message, "promo",
            f"🎫 *Promo kod qabul qilindi!*\n\n✅ *+{bonus} almaz* qo'shildi!\n💰 Balans: *{nb:.1f}* 💎",
            InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menyu", callback_data="menu")]]))
        # Limit tugasa kanalga xabar yuborish
        if new_used_count >= limit:
            try:
                bot_info = await context.bot.get_me()
                bot_username = f"@{bot_info.username}"
                end_msg = (
                    f"🔔 Promokod limiti tugadi!\n\n"
                    f"🎟 Promokod: {text.upper()}\n"
                    f"💰 Miqdori: {int(bonus)} almaz\n"
                    f"👥 Foydalanildi: {new_used_count}/{limit} kishi\n\n"
                    f"🚀 {bot_username} dan uzoqlashmang! "
                    f"Aktiv bo'lib tursangiz hali juda ko'p promokodlar tashlaymiz!"
                )
                await context.bot.send_message(
                    PROOF_CHANNEL, end_msg,
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton("🤖 Botga o'tish", url=f"https://t.me/{bot_info.username}")
                    ]]))
            except Exception as e:
                logger.error(f"Promo end channel: {e}")
        return

    if context.user_data.get("review_mode"):
        context.user_data.pop("review_mode", None)
        nb = round(data.get("diamonds", 0) + 5, 1)
        uref(uid).update({"diamonds": nb, "review_left": True, "total_earned": firestore.Increment(5)})
        for adm_id in ADMIN_IDS:
            try:
                await context.bot.send_message(adm_id,
                    f"Yangi izoh!\n\n"
                    f"Ism: {data.get('full_name')}\n"
                    f"ID: {uid}\n\n"
                    f"Izoh: {text}")
            except: pass
        await send_photo(update.message, "review",
            f"✅ *Izohingiz qabul qilindi!*\n\n🎁 *+5 almaz* olindi!\n💰 Balans: *{nb:.1f}* 💎\n\nRahmat! 🙏",
            InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Menyu", callback_data="menu")]]))
        return

    if context.user_data.get("ai_phone_mode"):
        context.user_data.pop("ai_phone_mode", None)
        await context.bot.send_chat_action(uid, "typing")
        ans = ai_resp(uid,
            f"Telefonim: {text}\n"
            f"Free Fire uchun to'liq sozlamalar:\n"
            f"1. SENSITIVITY raqamlari\n2. DPI\n3. Grafika va FPS\n4. Optimizatsiya")
        await send_photo(update.message, "phone",
            f"📱 *{text} uchun FF Sozlamalari* 🎮\n\n{ans}",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("🔄 Boshqa model", callback_data="phone_settings")],
                [InlineKeyboardButton("🔙 Menyu",        callback_data="menu")],
            ]))
        return

    if context.user_data.get("ai_chat") or data.get("ai_chat_mode"):
        await context.bot.send_chat_action(uid, "typing")
        ans = ai_resp(uid, text)
        await send_photo(update.message, "ai", ans,
            InlineKeyboardMarkup([[InlineKeyboardButton("❌ Chiqish", callback_data="menu")]]))
        return

    d = data.get("diamonds", 0)
    _, lvl, _ = get_level(d)
    await send_photo(update.message, "start",
        f"{greet(update.effective_user.first_name)}\n\n{lvl} | 💎 *{d:.1f}* almaz\n\nAsosiy menyu:",
        main_menu(d))

# ==================== ADMIN PANEL ====================
async def admin_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    await send_photo(update.message, "admin", "👑 *Admin panel*", InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Statistika",              callback_data="adm_stats")],
        [InlineKeyboardButton("👥 Foydalanuvchilar",        callback_data="adm_users")],
        [InlineKeyboardButton("📣 Bot Broadcast",            callback_data="adm_bc")],
        [InlineKeyboardButton("📢 Kanallarga Post",          callback_data="adm_channel_post")],
        [InlineKeyboardButton("🚫 Ban",                      callback_data="adm_ban"),
         InlineKeyboardButton("✅ Unban",                     callback_data="adm_unban")],
        [InlineKeyboardButton("💎 Almaz qo'shish",           callback_data="adm_add")],
        [InlineKeyboardButton("💸 Kutayotgan so'rovlar",     callback_data="adm_pending")],
        [InlineKeyboardButton("🏆 Turnir ishtirokchilari",   callback_data="adm_tournament")],
        [InlineKeyboardButton("🎫 Promo kod yaratish",       callback_data="adm_promo")],
        [InlineKeyboardButton("🔍 Foydalanuvchi izlash",     callback_data="adm_search")],
        [InlineKeyboardButton("✅ Isbotlar kanaliga o'tish", url=PROOF_CHANNEL_LINK)],
    ]))

def admin_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Statistika",              callback_data="adm_stats")],
        [InlineKeyboardButton("👥 Foydalanuvchilar",        callback_data="adm_users")],
        [InlineKeyboardButton("📣 Bot Broadcast",            callback_data="adm_bc")],
        [InlineKeyboardButton("📢 Kanallarga Post",          callback_data="adm_channel_post")],
        [InlineKeyboardButton("🚫 Ban",                      callback_data="adm_ban"),
         InlineKeyboardButton("✅ Unban",                     callback_data="adm_unban")],
        [InlineKeyboardButton("💎 Almaz qo'shish",           callback_data="adm_add")],
        [InlineKeyboardButton("💸 Kutayotgan so'rovlar",     callback_data="adm_pending")],
        [InlineKeyboardButton("🏆 Turnir ishtirokchilari",   callback_data="adm_tournament")],
        [InlineKeyboardButton("🎫 Promo kod yaratish",       callback_data="adm_promo")],
        [InlineKeyboardButton("🔍 Foydalanuvchi izlash",     callback_data="adm_search")],
        [InlineKeyboardButton("✅ Isbotlar kanaliga o'tish", url=PROOF_CHANNEL_LINK)],
    ])


async def adm_stats_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id not in ADMIN_IDS: await q.answer("❌", show_alert=True); return
    await q.answer()
    total    = sum(1 for _ in get_db().collection("users").stream())
    banned   = sum(1 for _ in get_db().collection("users").where("is_banned", "==", True).stream())
    total_d  = sum(d.to_dict().get("diamonds", 0) for d in get_db().collection("users").stream())
    pending  = sum(1 for _ in get_db().collection("withdrawals").where("status", "==", "pending").stream())
    approved = sum(1 for _ in get_db().collection("withdrawals").where("status", "==", "approved").stream())
    await send_photo(q, "admin",
        f"📊 *Statistika*\n\n"
        f"👥 Jami foydalanuvchi: *{total}*\n"
        f"🚫 Bloklangan: *{banned}*\n"
        f"✅ Faol: *{total - banned}*\n\n"
        f"💎 Jami almaz: *{total_d:.1f}*\n"
        f"💸 Kutayotgan so'rovlar: *{pending}*\n"
        f"✅ Tasdiqlangan: *{approved}*",
        InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin", callback_data="adm_back")]]), edit=True)

async def adm_users_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id not in ADMIN_IDS: return
    await q.answer()
    docs  = get_db().collection("users").order_by("joined_at", direction=firestore.Query.DESCENDING).limit(5).stream()
    lines = ["👥 *So'nggi 5 foydalanuvchi*\n"]
    for doc in docs:
        d = doc.to_dict()
        uname = f"@{d.get('username')}" if d.get('username') else "—"
        _, lvl, _ = get_level(d.get("diamonds", 0))
        ban = "🚫" if d.get("is_banned") else "✅"
        lines.append(
            f"━━━━━━━━━\n"
            f"{ban} *{d.get('full_name', '?')}*\n"
            f"📱 {d.get('phone', '—')}\n"
            f"🎮 FF ID: {d.get('ff_id', '—')}\n"
            f"🆔 {d.get('user_id', '—')} | {uname}\n"
            f"💎 *{d.get('diamonds', 0):.1f}* | {lvl}"
        )
    await send_photo(q, "admin", "\n".join(lines),
        InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin", callback_data="adm_back")]]), edit=True)

async def adm_pending_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id not in ADMIN_IDS: return
    await q.answer()
    docs = list(get_db().collection("withdrawals").where("status", "==", "pending").stream())
    if not docs:
        await send_photo(q, "admin", "✅ Kutayotgan so'rovlar yo'q!",
            InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Admin", callback_data="adm_back")]]), edit=True)
        return
    lines    = [f"💸 *Kutayotgan: {len(docs)} ta*\n"]
    btn_rows = []
    for w_doc in docs[:5]:
        w = w_doc.to_dict()
        lines.append(
            f"━━━━━━━━━\n"
            f"👤 *{w.get('full_name', '?')}*\n"
            f"📱 {w.get('phone', '—')}\n"
            f"🎮 FF ID: {w.get('ff_id', '—')}\n"
            f"💎 *{w.get('diamonds', 0):.1f}* almaz\n"
            f"🆔 TG: {w.get('user_id', '—')}"
        )
        short_name = w.get("full_name", "?")[:10]
        btn_rows.append([
            InlineKeyboardButton(f"✅ {short_name}", callback_data=f"approve_{w.get('w_id')}"),
            InlineKeyboardButton("❌ Rad",            callback_data=f"reject_{w.get('w_id')}"),
        ])
    btn_rows.append([InlineKeyboardButton("🔙 Admin", callback_data="adm_back")])
    await send_photo(q, "admin", "\n".join(lines), InlineKeyboardMarkup(btn_rows), edit=True)

async def adm_search_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id not in ADMIN_IDS: return
    await q.answer()
    context.user_data["adm_action"] = "search_user"
    await q.message.reply_text("🔍 Foydalanuvchi Telegram ID sini yozing:")

async def adm_back_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id not in ADMIN_IDS: return
    await q.answer()
    await send_photo(q, "admin", "👑 *Admin panel*", admin_kb(), edit=True)

async def adm_bc_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id not in ADMIN_IDS: return
    await q.answer()
    context.user_data["adm_action"] = "broadcast"
    await q.message.reply_text(
        "📣 *Broadcast*\n\n"
        "Matn, rasm, video yoki fayl yuboring!\n\n"
        "Rasm + caption → barcha userlarga rasm\n"
        "Video + caption → barcha userlarga video\n"
        "Faqat matn → matn broadcast",
        parse_mode="Markdown")

async def adm_channel_post_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Barcha BROADCAST_CHANNELS ga post yuborish"""
    q = update.callback_query
    if q.from_user.id not in ADMIN_IDS: return
    await q.answer()
    context.user_data["adm_action"] = "channel_post"
    channels_list = "\n".join(f"• {ch}" for ch in BROADCAST_CHANNELS)
    await q.message.reply_text(
        f"📢 *Kanallarga Post Yuborish*\n\n"
        f"Quyidagi kanallarga post ketadi:\n{channels_list}\n\n"
        f"Matn, rasm, video yoki fayl yuboring!\n"
        f"Rasm + caption = rasmli post\n"
        f"Faqat matn = matn post",
        parse_mode="Markdown")

async def adm_tournament_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Turnir boshqaruvi — yaratish yoki ko'rish"""
    q = update.callback_query
    if q.from_user.id not in ADMIN_IDS: return
    await q.answer()

    tour = get_active_tournament()

    if not tour:
        # Faol turnir yo'q — yaratish tugmasini ko'rsat
        await send_photo(q, "admin",
            "🏆 *Turnir Boshqaruvi*\n\nHozirda faol turnir yo'q.\n\n"
            "Yangi turnir yaratish uchun tugmani bosing:",
            InlineKeyboardMarkup([
                [InlineKeyboardButton("➕ Yangi Turnir Yaratish", callback_data="adm_create_tour")],
                [InlineKeyboardButton("🔙 Admin", callback_data="adm_back")],
            ]), edit=True)
        return

    tour_id      = tour.get("tour_id")
    tour_name    = tour.get("name", "Turnir")
    max_slots    = tour.get("max_slots", TOURNAMENT_MAX)
    prize        = tour.get("prize", TOURNAMENT_PRIZE)
    status       = tour.get("status", "active")
    participants = get_tournament_participants(tour_id)
    current      = len(participants)
    remaining    = max_slots - current
    filled       = min(int(current / max_slots * 10), 10)
    bar          = "🟥" * filled + "⬜" * (10 - filled)

    status_emoji = "🟢 Faol" if status == "active" else ("🔴 To'lgan" if status == "full" else "⚫ Yakunlangan")

    lines = [
        f"🏆 *{tour_name}*\n",
        f"📊 Holat: {status_emoji}",
        f"👥 Ishtirokchilar: *{current}/{max_slots}*",
        f"📊 {bar}",
        f"🔥 Qolgan: *{remaining}* o'rin",
        f"🎁 Sovrin: *{int(prize)} almaz*",
        f"\n━━━━━━━━━ ISHTIROKCHILAR ━━━━━━━━━",
    ]
    for i, p in enumerate(participants[:15], 1):
        uname = f"@{p.get('username')}" if p.get('username') else "—"
        lines.append(
            f"{i}. *{p.get('full_name', '?')}* | "
            f"FF: {p.get('ff_id', '—')} | "
            f"TG: `{p.get('user_id', '—')}` | {uname}"
        )
    if current > 15:
        lines.append(f"\n... va yana *{current-15}* ta ishtirokchi")

    btns = [
        [InlineKeyboardButton("📣 Ishtirokchilarga xabar", callback_data=f"adm_tour_msg_{tour_id}")],
        [InlineKeyboardButton("🏁 Turnirni yakunlash",     callback_data=f"adm_tour_end_{tour_id}")],
        [InlineKeyboardButton("❌ Turnirni bekor qilish",  callback_data=f"adm_tour_cancel_{tour_id}")],
        [InlineKeyboardButton("🔙 Admin",                  callback_data="adm_back")],
    ]
    await send_photo(q, "admin", "\n".join(lines), InlineKeyboardMarkup(btns), edit=True)

async def adm_create_tour_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Yangi turnir yaratish"""
    q = update.callback_query
    if q.from_user.id not in ADMIN_IDS: return
    await q.answer()
    context.user_data["adm_action"] = "create_tournament"
    await q.message.reply_text(
        "🏆 *Yangi Turnir Yaratish*\n\n"
        "Format: NOM SOVRIN MAX_KISHI\n"
        "Masalan: `FreeFire_Turnir 500 45`\n\n"
        "• NOM — turnir nomi (bo'sh joy yo'q, _ ishlating)\n"
        "• SOVRIN — g'olib oladi (almaz)\n"
        "• MAX_KISHI — maksimal ishtirokchi (masalan 45)",
        parse_mode="Markdown")

async def adm_tour_msg_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Turnir ishtirokchilariga xabar yuborish"""
    q = update.callback_query
    if q.from_user.id not in ADMIN_IDS: return
    await q.answer()
    tour_id = q.data.replace("adm_tour_msg_", "")
    context.user_data["adm_action"]    = "tour_broadcast"
    context.user_data["tour_id_msg"]   = tour_id
    await q.message.reply_text(
        "📣 Turnir ishtirokchilariga yubormoqchi bo'lgan xabaringizni yozing:\n\n"
        "(Matn, rasm yoki video yuborishingiz mumkin)")

async def adm_tour_end_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Turnirni yakunlash"""
    q = update.callback_query
    if q.from_user.id not in ADMIN_IDS: return
    await q.answer()
    tour_id = q.data.replace("adm_tour_end_", "")
    tour_doc = get_db().collection("tournaments").document(tour_id).get()
    if not tour_doc.exists: return
    tour = tour_doc.to_dict()
    get_db().collection("tournaments").document(tour_id).update({"status": "ended"})
    participants = get_tournament_participants(tour_id)
    sent = 0
    for p in participants:
        try:
            await context.bot.send_message(p["user_id"],
                f"🏁 *{tour.get('name', 'Turnir')} yakunlandi!*\n\n"
                f"Qatnashganingiz uchun rahmat!\n"
                f"Natijalar tez orada e'lon qilinadi.\n"
                f"📢 @Muzonoken",
                parse_mode="Markdown")
            sent += 1
        except: pass
    await q.edit_message_caption(
        caption=f"🏁 Turnir yakunlandi! {sent} ta ishtirokchiga xabar yuborildi.")

async def adm_tour_cancel_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Turnirni bekor qilish"""
    q = update.callback_query
    if q.from_user.id not in ADMIN_IDS: return
    await q.answer()
    tour_id = q.data.replace("adm_tour_cancel_", "")
    get_db().collection("tournaments").document(tour_id).update({"status": "cancelled"})
    await q.edit_message_caption(caption="❌ Turnir bekor qilindi.")


async def adm_ban_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id not in ADMIN_IDS: return
    await q.answer()
    context.user_data["adm_action"] = "ban"
    await q.message.reply_text("🚫 Ban uchun Telegram ID yozing:")

async def adm_unban_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id not in ADMIN_IDS: return
    await q.answer()
    context.user_data["adm_action"] = "unban"
    await q.message.reply_text("✅ Unban uchun Telegram ID yozing:")

async def adm_add_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id not in ADMIN_IDS: return
    await q.answer()
    context.user_data["adm_action"] = "add_diamonds"
    await q.message.reply_text("💎 Format: user_id miqdor\nMasalan: 123456789 50")

async def adm_promo_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id not in ADMIN_IDS: return
    await q.answer()
    context.user_data["adm_action"] = "create_promo"
    await q.message.reply_text(
        "🎫 *Promo kod yaratish*\n\nFormat: KOD BONUS LIMIT\nMasalan: MUZON2024 20 100",
        parse_mode="Markdown")

async def admin_text_handler(update, context, action, text):
    context.user_data.pop("adm_action", None)
    if action == "broadcast":
        users = get_db().collection("users").where("is_banned", "==", False).stream()
        sent = failed = 0
        await update.message.reply_text("📣 Broadcast boshlanmoqda...")
        for doc in users:
            try:
                await context.bot.send_message(doc.id, f"📣 {text}")
                sent += 1; await asyncio.sleep(0.05)
            except: failed += 1
        await update.message.reply_text(f"✅ Tugadi! 📨 {sent} | ❌ {failed}")
    elif action == "ban":
        if text.isdigit():
            uref(int(text)).update({"is_banned": True})
            await update.message.reply_text(f"🚫 {text} bloklandi.")
            try:
                await context.bot.send_message(int(text),
                    "Siz bloklangansiz!\n\nMuammo bo'lsa admin bilan bog'laning: @Muzonoken")
            except: pass
        else: await update.message.reply_text("❌ Noto'g'ri ID.")
    elif action == "unban":
        if text.isdigit():
            uref(int(text)).update({"is_banned": False})
            await update.message.reply_text(f"✅ {text} blokdan chiqarildi.")
            try:
                await context.bot.send_message(int(text), "✅ Blokiniz olib tashlandi! /start bosing.")
            except: pass
        else: await update.message.reply_text("❌ Noto'g'ri ID.")
    elif action == "add_diamonds":
        # quick_add_uid dan kelgan bo'lsa (faqat miqdor yoziladi)
        quick_uid = context.user_data.pop("quick_add_uid", None)
        if quick_uid and text.replace(".", "").isdigit():
            try:
                amt = float(text)
                uref(quick_uid).update({
                    "diamonds": firestore.Increment(amt),
                    "total_earned": firestore.Increment(amt)
                })
                await update.message.reply_text(f"💎 {quick_uid} ga +{amt} almaz qo'shildi!")
                try:
                    await context.bot.send_message(quick_uid,
                        f"Admin tomonidan +{amt} almaz qo'shildi! 🎁\n\n"
                        f"💎 Yangi almaz hisobingizga tushdi!")
                except: pass
            except: await update.message.reply_text("❌ Xato miqdor.")
            return
        # Oddiy format: user_id miqdor
        parts = text.split()
        if len(parts) == 2 and parts[0].isdigit():
            try:
                amt = float(parts[1])
                uref(int(parts[0])).update({
                    "diamonds": firestore.Increment(amt),
                    "total_earned": firestore.Increment(amt)
                })
                udata = get_user(int(parts[0]))
                new_bal = udata.get("diamonds", 0) if udata else 0
                await update.message.reply_text(
                    f"💎 {parts[0]} ga +{amt} almaz qo'shildi!\n"
                    f"Yangi balans: {new_bal:.1f}")
                try:
                    await context.bot.send_message(int(parts[0]),
                        f"Admin tomonidan +{amt} almaz qo'shildi! 🎁\n\n"
                        f"💎 Yangi almaz hisobingizga tushdi!")
                except: pass
            except: await update.message.reply_text("❌ Xato format.")
        else: await update.message.reply_text("❌ Format: user_id miqdor\nMasalan: 123456789 50")
    elif action == "create_promo":
        parts = text.split()
        if len(parts) == 3:
            try:
                code, bonus, limit = parts[0].upper(), float(parts[1]), int(parts[2])
                get_db().collection("promos").document(code).set({
                    "code": code, "bonus": bonus, "limit": limit,
                    "used_by": [], "created_at": now_ts()
                })
                await update.message.reply_text(
                    f"✅ Promo yaratildi!\n🎫 `{code}`\n💎 {bonus} almaz | 👥 {limit} ta limit",
                    parse_mode="Markdown")
                # Kanalga promo haqida post yuborish
                try:
                    bot_info = await context.bot.get_me()
                    bot_username = f"@{bot_info.username}"
                    promo_msg = (
                        f"🎟 YANGI PROMOKOD!\n\n"
                        f"🔑 Promokod: {code}\n"
                        f"💰 Miqdori: {int(bonus)} almaz\n"
                        f"👥 Limit: {limit} kishi\n\n"
                        f"🚀 Tez bo'ling! Faqat {limit} ta o'rin bor!\n"
                        f"👇 Botga kiring va promokodni kiriting!"
                    )
                    await context.bot.send_message(
                        PROOF_CHANNEL, promo_msg,
                        reply_markup=InlineKeyboardMarkup([[
                            InlineKeyboardButton("🤖 Botga o'tish va ishlatish",
                                url=f"https://t.me/{bot_info.username}")
                        ]]))
                except Exception as e:
                    logger.error(f"Promo kanal: {e}")
            except: await update.message.reply_text("❌ Xato format.")
        else: await update.message.reply_text("❌ Format: KOD BONUS LIMIT")
    elif action == "create_tournament":
        parts = text.split()
        if len(parts) == 3:
            try:
                t_name, t_prize, t_max = parts[0].replace("_", " "), float(parts[1]), int(parts[2])
                tour_id = f"TOUR_{int(time.time())}"
                get_db().collection("tournaments").document(tour_id).set({
                    "tour_id":   tour_id,
                    "name":      t_name,
                    "prize":     t_prize,
                    "max_slots": t_max,
                    "status":    "active",
                    "created_at": now_ts(),
                    "created_by": update.effective_user.id,
                })
                await update.message.reply_text(
                    f"✅ Turnir yaratildi!\n\n"
                    f"🏆 Nom: {t_name}\n"
                    f"🎁 Sovrin: {int(t_prize)} almaz\n"
                    f"👥 Maksimal: {t_max} kishi\n\n"
                    f"Foydalanuvchilar menyusida ko'rinadi!")
                # Barcha foydalanuvchilarga xabar yuborish
                await update.message.reply_text("📣 Foydalanuvchilarga xabar yuborilmoqda...")
                docs = get_db().collection("users").where("is_banned", "==", False).stream()
                sent = failed = 0
                for doc in docs:
                    try:
                        d = doc.to_dict()
                        uid_t = d.get("user_id")
                        if not uid_t: continue
                        _, lvl, _ = get_level(d.get("diamonds", 0))
                        await context.bot.send_message(uid_t,
                            f"🏆 YANGI TURNIR E'LON QILINDI!\n\n"
                            f"Turnir: {t_name}\n"
                            f"🎁 Sovrin: {int(t_prize)} almaz\n"
                            f"👥 O'rinlar: {t_max} ta\n\n"
                            f"Tez bo'ling! O'rinlar cheklangan!",
                            reply_markup=InlineKeyboardMarkup([[
                                InlineKeyboardButton("🏆 Qatnashish", callback_data="tournament")
                            ]]))
                        sent += 1
                        await asyncio.sleep(0.05)
                    except: failed += 1
                await update.message.reply_text(f"✅ Xabar yuborildi: {sent} | ❌ {failed}")
            except Exception as e:
                await update.message.reply_text(f"❌ Xato: {e}\nFormat: NOM SOVRIN MAX_KISHI")
        else:
            await update.message.reply_text("❌ Format: NOM SOVRIN MAX_KISHI\nMasalan: FreeFire_Turnir 500 45")

    elif action == "tour_broadcast":
        tour_id = context.user_data.pop("tour_id_msg", None)
        if not tour_id:
            await update.message.reply_text("❌ Turnir ID topilmadi."); return
        participants = get_tournament_participants(tour_id)
        if not participants:
            await update.message.reply_text("❌ Ishtirokchilar yo'q."); return
        sent = failed = 0
        await update.message.reply_text(f"📣 {len(participants)} ta ishtirokchiga xabar yuborilmoqda...")
        for p in participants:
            try:
                await context.bot.send_message(p["user_id"], f"🏆 Turnir xabari:\n\n{text}")
                sent += 1; await asyncio.sleep(0.05)
            except: failed += 1
        await update.message.reply_text(f"✅ Yuborildi: {sent} | ❌ {failed}")

    elif action == "search_user":
        if text.isdigit():
            d = get_user(int(text))
            if d:
                uname = f"@{d.get('username')}" if d.get('username') else "—"
                _, lvl, ldesc = get_level(d.get("diamonds", 0))
                ban_st = "🚫 Ha" if d.get("is_banned") else "✅ Yoq"
                await update.message.reply_text(
                    f"Foydalanuvchi malumotlari\n\n"
                    f"Ism: {d.get('full_name')}\n"
                    f"Tel: {d.get('phone', '—')}\n"
                    f"FF ID: {d.get('ff_id', '—')}\n"
                    f"TG ID: {d.get('user_id')}\n"
                    f"Username: {uname}\n"
                    f"Almaz: {d.get('diamonds', 0):.1f}\n"
                    f"Jami: {d.get('total_earned', 0):.1f}\n"
                    f"Daraja: {lvl} — {ldesc}\n"
                    f"Ban: {ban_st}",
                    reply_markup=InlineKeyboardMarkup([
                        [InlineKeyboardButton("🚫 Ban",         callback_data=f"quick_ban_{d.get('user_id')}"),
                         InlineKeyboardButton("💎 Almaz qo'sh", callback_data=f"quick_add_{d.get('user_id')}")],
                    ]))
            else: await update.message.reply_text("❌ Foydalanuvchi topilmadi.")
        else: await update.message.reply_text("❌ Telegram ID raqam bo'lishi kerak.")


    elif action == "channel_post":
        # Matn post kanalga
        context.user_data.pop("adm_action", None)
        sent = failed = 0
        for ch in BROADCAST_CHANNELS:
            try:
                await context.bot.send_message(ch, text)
                sent += 1
            except Exception as e:
                failed += 1
                logger.error(f"Kanal matn xato {ch}: {e}")
        await update.message.reply_text(
            f"✅ Kanal post tugadi!\n✅ {sent} ta | ❌ {failed} ta")

async def quick_ban_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if q.from_user.id not in ADMIN_IDS: return
    await q.answer()
    uid = int(q.data.replace("quick_ban_", ""))
    uref(uid).update({"is_banned": True})
    await q.message.reply_text(f"🚫 {uid} bloklandi.")
    try:
        await context.bot.send_message(uid, "Siz bloklangansiz! @Muzonoken ga murojaat qiling.")
    except: pass

async def quick_add_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """quick_add tugmasi bosilganda almaz qo'shish"""
    q = update.callback_query
    if q.from_user.id not in ADMIN_IDS: return
    await q.answer()
    uid = int(q.data.replace("quick_add_", ""))
    context.user_data["adm_action"] = "add_diamonds"
    context.user_data["quick_add_uid"] = uid
    await q.message.reply_text(
        f"💎 {uid} ga qancha almaz qo'shish?\n\nFaqat miqdorni yozing (masalan: 50)")


async def menu_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    update_last_seen(uid)
    for k in ["ai_chat", "ai_phone_mode", "promo_mode", "review_mode", "edit_mode"]:
        context.user_data.pop(k, None)
    try: uref(uid).update({"ai_chat_mode": False})
    except: pass
    data = get_user(uid)
    d    = data.get("diamonds", 0) if data else 0
    _, lvl, _ = get_level(d)
    await send_photo(update.message, "start",
        f"{greet(update.effective_user.first_name)}\n\n{lvl} | 💎 *{d:.1f}* almaz\n\nAsosiy menyu:",
        main_menu(d))

async def skip_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    context.user_data.pop("proof_w_id", None)
    await update.message.reply_text("✅ Isbot yuborish o'tkazib yuborildi.")

# ==================== WEBHOOK SERVER ====================

# ==================== MAIN ====================
def main():
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            PHONE: [MessageHandler(filters.CONTACT, phone_received)],
            FF_ID: [MessageHandler(filters.TEXT & ~filters.COMMAND, ff_id_received)],
        },
        fallbacks=[CommandHandler("start", start)],
    )
    app.add_handler(conv)
    app.add_handler(CommandHandler("admin", admin_cmd))
    app.add_handler(CommandHandler("menu",  menu_cmd))
    app.add_handler(CommandHandler("skip",  skip_cmd))

    for pat, fn in [
        ("check_sub",      check_sub_cb),
        ("earn",           earn_cb),
        ("profile",        profile_cb),
        ("referral",       referral_cb),
        ("top",            top_cb),
        ("menu",           menu_cb),
        ("withdraw",       withdraw_cb),
        ("wd_confirm",     wd_confirm_cb),
        ("phone_settings", phone_settings_cb),
        ("ai_menu",        ai_menu_cb),
        ("ai_tips",        ai_tips_cb),
        ("ai_phone",       ai_phone_cb),
        ("ai_diamonds",    ai_diamonds_cb),
        ("ai_chat",        ai_chat_cb),
        ("daily",          daily_cb),
        ("game",           game_cb),
        ("stats",          stats_cb),
        ("promo",          promo_cb),
        ("review",         review_cb),
        ("proofs",         proofs_cb),
        ("tournament",     tournament_cb),
        ("tournament_join",tournament_join_cb),
        ("edit_profile",   edit_profile_cb),
        ("edit_ff_id",     edit_ff_id_cb),
        ("edit_name",      edit_name_cb),
        ("adm_stats",      adm_stats_cb),
        ("adm_back",       adm_back_cb),
        ("adm_bc",         adm_bc_cb),
        ("adm_channel_post", adm_channel_post_cb),
        ("adm_ban",        adm_ban_cb),
        ("adm_unban",      adm_unban_cb),
        ("adm_add",        adm_add_cb),
        ("adm_users",      adm_users_cb),
        ("adm_pending",    adm_pending_cb),
        ("adm_tournament",   adm_tournament_cb),
        ("adm_create_tour",  adm_create_tour_cb),
        ("adm_promo",        adm_promo_cb),
        ("adm_search",       adm_search_cb),
    ]:
        app.add_handler(CallbackQueryHandler(fn, pattern=f"^{pat}$"))

    app.add_handler(CallbackQueryHandler(wd_amount_cb,       pattern=r"^wd_\d+$|^wd_all$"))
    app.add_handler(CallbackQueryHandler(game_play_cb,       pattern=r"^game_\d+$"))
    app.add_handler(CallbackQueryHandler(approve_cb,         pattern=r"^approve_"))
    app.add_handler(CallbackQueryHandler(reject_cb,          pattern=r"^reject_"))
    app.add_handler(CallbackQueryHandler(quick_ban_cb,       pattern=r"^quick_ban_"))
    app.add_handler(CallbackQueryHandler(quick_add_cb,       pattern=r"^quick_add_"))
    app.add_handler(CallbackQueryHandler(tour_accept_cb,     pattern=r"^tour_accept_"))
    app.add_handler(CallbackQueryHandler(tour_reject_cb,     pattern=r"^tour_reject_"))
    app.add_handler(CallbackQueryHandler(tournament_join_cb, pattern=r"^tournament_join_"))
    app.add_handler(CallbackQueryHandler(adm_tour_msg_cb,    pattern=r"^adm_tour_msg_"))
    app.add_handler(CallbackQueryHandler(adm_tour_end_cb,    pattern=r"^adm_tour_end_"))
    app.add_handler(CallbackQueryHandler(adm_tour_cancel_cb, pattern=r"^adm_tour_cancel_"))

    app.add_handler(MessageHandler(
        (filters.PHOTO | filters.VIDEO | filters.Document.ALL) & filters.User(ADMIN_IDS),
        handle_admin_media))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Background jobs
    # app.job_queue.run_repeating(remind_job,   interval=EARN_COOLDOWN,     first=60)  # Firebase limit tejash
    # app.job_queue.run_repeating(miss_you_job, interval=MISS_YOU_INTERVAL, first=120)  # Firebase limit tejash

    WEBHOOK_URL = os.getenv("RAILWAY_PUBLIC_DOMAIN") or os.getenv("WEBHOOK_URL")
    PORT = int(os.environ.get("PORT", 8080))

    if WEBHOOK_URL:
        # WEBHOOK — eng tez usul
        webhook_url = f"https://{WEBHOOK_URL}/{TELEGRAM_BOT_TOKEN}"
        logger.info(f"🚀 Bot webhook da ishga tushdi: {webhook_url}")
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=TELEGRAM_BOT_TOKEN,
            webhook_url=webhook_url,
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES
        )
    else:
        # POLLING — local test uchun
        logger.info("🚀 Bot polling da ishga tushdi!")
        app.run_polling(
            drop_pending_updates=True,
            allowed_updates=Update.ALL_TYPES
        )

if __name__ == "__main__":
    main()
