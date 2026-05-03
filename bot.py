import os
import requests
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
BINANCE_URL = "https://p2p.binance.com/bapi/c2c/v2/friendly/c2c/adv/search"


def fetch_offers(trade_type="BUY", pages=5):
    offers = []

    for page in range(1, pages + 1):
        payload = {
            "page": page,
            "rows": 20,
            "asset": "USDT",
            "fiat": "USD",
            "tradeType": trade_type,
            "payTypes": ["ABA"],
            "publisherType": None
        }

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0"
        }

        response = requests.post(BINANCE_URL, json=payload, headers=headers, timeout=15)
        response.raise_for_status()

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
                "orders": advertiser.get("monthOrderCount", 0),
                "completion": advertiser.get("monthFinishRate", "N/A")
            })

    return offers


def aggregate_liquidity_by_price(offers):
    price_map = {}

    for offer in offers:
        price = round(offer["price"], 4)
        usdt_supply = offer["available_usdt"]

        if price not in price_map:
            price_map[price] = 0

        price_map[price] += usdt_supply

    return sorted(price_map.items(), key=lambda x: x[0])


def build_best_mix(offers, target_usd):
    remaining = target_usd
    selected = []

    offers = sorted(offers, key=lambda x: x["price"])

    for offer in offers:
        if remaining <= 0:
            break

        price = offer["price"]
        available_usdt = offer["available_usdt"]
        available_usd = available_usdt * price

        usable_max_usd = min(offer["max"], available_usd)

        if remaining < offer["min"]:
            continue

        take_usd = min(usable_max_usd, remaining)
        receive_usdt = take_usd / price

        selected.append({
            "name": offer["name"],
            "price": price,
            "take_usd": take_usd,
            "receive_usdt": receive_usdt,
            "available_usdt": available_usdt
        })

        remaining -= take_usd

    covered = target_usd - remaining

    avg_price = (
        sum(x["price"] * x["receive_usdt"] for x in selected)
        / sum(x["receive_usdt"] for x in selected)
        if selected else 0
    )

    return selected, covered, avg_price


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Binance P2P USDT/USD ABA Bot\n\n"
        "Commands:\n"
        "/buy 50\n"
        "/buy 15000\n"
        "/liquidity"
    )


async def liquidity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        offers = fetch_offers("BUY", pages=5)
        liquidity_data = aggregate_liquidity_by_price(offers)

        if not liquidity_data:
            await update.message.reply_text("No liquidity data found.")
            return

        # 🔥 only take top 5 best rates
        top_levels = liquidity_data[:5]

        msg = "📊 Top 5 Liquidity (ABA USDT/USD)\n\n"

        cumulative = 0

        for price, total_usdt in top_levels:
            cumulative += total_usdt
            usd_value = total_usdt * price

            msg += (
                f"{price:.4f} → {total_usdt:,.0f} USDT "
                f"(≈ ${usd_value:,.0f})\n"
                f"Cum: {cumulative:,.0f} USDT\n\n"
            )

        await update.message.reply_text(msg)

    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        amount = float(context.args[0])
    except:
        await update.message.reply_text("Example: /buy 50")
        return

    try:
        offers = fetch_offers("BUY", pages=5)
        selected, covered, avg_price = build_best_mix(offers, amount)

        if not selected:
            await update.message.reply_text("No suitable ABA offers found.")
            return

        msg = f"🟢 Best mix to buy USDT with ${amount:,.2f} via ABA\n\n"

        for i, item in enumerate(selected, start=1):
            msg += (
                f"{i}. Pay ${item['take_usd']:,.2f} @ {item['price']:.4f}\n"
                f"   Receive: {item['receive_usdt']:,.2f} USDT\n"
                f"   Seller: {item['name']}\n\n"
            )

        total_usdt = sum(x["receive_usdt"] for x in selected)

        msg += f"✅ Covered: ${covered:,.2f}"
        msg += f"\n💵 Total USDT: {total_usdt:,.2f}"
        msg += f"\n📊 Average rate: {avg_price:.4f}"

        if covered < amount:
            msg += f"\n⚠️ Not enough liquidity. Missing: ${amount - covered:,.2f}"

        await update.message.reply_text(msg)

    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


def main():
    if not BOT_TOKEN:
        raise ValueError("Missing TELEGRAM_BOT_TOKEN in .env file")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("buy", buy))
    app.add_handler(CommandHandler("liquidity", liquidity))

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()