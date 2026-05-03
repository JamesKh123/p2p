import os
import requests
from fastapi import FastAPI, Request
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")

BINANCE_URL = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"

app = FastAPI()
telegram_app = ApplicationBuilder().token(BOT_TOKEN).build()


# ================= FETCH =================
def fetch_offers(trade_type="BUY", pages=3):
    offers = []

    for page in range(1, pages + 1):
        payload = {
            "page": page,
            "rows": 20,
            "asset": "USDT",
            "fiat": "USD",
            "tradeType": trade_type,
            "payTypes": ["ABA"],
        }

        response = requests.post(BINANCE_URL, json=payload, timeout=10)
        data = response.json().get("data", [])

        for item in data:
            adv = item["adv"]
            advertiser = item["advertiser"]

            offers.append({
                "name": advertiser.get("nickName", "Unknown"),
                "price": float(adv["price"]),
                "min": float(adv["minSingleTransAmount"]),
                "max": float(adv["maxSingleTransAmount"]),
                "available_usdt": float(adv.get("surplusAmount", 0)),
            })

    return offers


# ================= LIQUIDITY =================
def aggregate_liquidity(offers):
    price_map = {}

    for o in offers:
        price = round(o["price"], 4)
        price_map[price] = price_map.get(price, 0) + o["available_usdt"]

    return sorted(price_map.items(), key=lambda x: x[0])


# ================= BEST MIX =================
def build_mix(offers, usd_amount):
    remaining = usd_amount
    selected = []

    offers = sorted(offers, key=lambda x: x["price"])

    for o in offers:
        if remaining <= 0:
            break

        if remaining < o["min"]:
            continue

        available_usd = o["available_usdt"] * o["price"]
        take = min(available_usd, remaining)

        selected.append({
            "name": o["name"],
            "price": o["price"],
            "usd": take,
            "usdt": take / o["price"]
        })

        remaining -= take

    covered = usd_amount - remaining
    avg_price = (
        sum(x["price"] * x["usdt"] for x in selected) /
        sum(x["usdt"] for x in selected)
        if selected else 0
    )

    return selected, covered, avg_price


# ================= COMMANDS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot working ✅\nUse /buy 50 or /liquidity")


async def liquidity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    offers = fetch_offers()
    data = aggregate_liquidity(offers)

    top = data[:5]

    msg = "📊 Top 5 Liquidity\n\n"
    cum = 0

    for price, usdt in top:
        cum += usdt
        msg += f"{price:.4f} → {usdt:,.0f} USDT (cum: {cum:,.0f})\n"

    await update.message.reply_text(msg)


async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(context.args[0])
    except:
        await update.message.reply_text("Use /buy 50")
        return

    offers = fetch_offers()
    selected, covered, avg = build_mix(offers, amount)

    msg = f"🟢 Buy ${amount}\n\n"

    for i, s in enumerate(selected, 1):
        msg += f"{i}. ${s['usd']:.0f} @ {s['price']}\n"

    msg += f"\nAvg: {avg:.4f}"

    await update.message.reply_text(msg)


telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(CommandHandler("buy", buy))
telegram_app.add_handler(CommandHandler("liquidity", liquidity))


# ================= WEBHOOK =================
@app.on_event("startup")
async def startup():
    await telegram_app.initialize()
    await telegram_app.bot.set_webhook(f"{WEBHOOK_URL}/webhook")


@app.post("/webhook")
async def webhook(req: Request):
    data = await req.json()
    update = Update.de_json(data, telegram_app.bot)
    await telegram_app.process_update(update)
    return {"ok": True}
