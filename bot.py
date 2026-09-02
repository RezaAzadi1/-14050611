# -*- coding: utf-8 -*-
"""
ربات تلگرامی محاسبه‌گر تهاتر هات رول به ورق رنگی

از کاربر سه ورودی می‌گیرد:
  1) قیمت هات رول (تومان/کیلوگرم)
  2) وزن ورق رنگی مورد نیاز (تن)
  3) نرخ کارمزد تبدیل (تومان/کیلوگرم)

و بر اساس درصدهای ثابت ضایعات فرایند (طبق داده‌های کارخانه)، محاسبه می‌کند:
  - مقدار هات رولی که باید مشتری تحویل دهد
  - ریز ضایعات تولیدی (نوع، وزن، ارزش) که به مشتری برگردانده می‌شود
  - افت اسیدشویی (بدون بازگشت)
  - هزینه‌های نقدی (کارمزد + حمل)
  - هزینه خالص و قیمت تمام‌شده هر کیلوگرم ورق رنگی

اجرا:
    pip install python-telegram-bot==21.*
    export TELEGRAM_BOT_TOKEN="توکن ربات شما"
    python bot.py
"""

import os
import logging
from decimal import Decimal, InvalidOperation

from telegram import Update, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ثابت‌های فرایند (طبق اطلاعات کارخانه) — این‌ها از کاربر پرسیده نمی‌شوند
# ---------------------------------------------------------------------------
TRANSPORT_PRICE = Decimal("2500")  # تومان بر کیلوگرم

WASTE_ITEMS = [
    # (کلید, عنوان فارسی, درصد از کل هات رول, قیمت فروش هر کیلو در بازار یا None اگر بازگشتی نیست)
    {"key": "acid", "title": "افت اسیدشویی (نابود می‌شود - بدون بازگشت)", "pct": Decimal("0.005"), "price": None},
    {"key": "galv_semi", "title": "نیمچه کویل گالوالوم", "pct": Decimal("0.01"), "price": Decimal("110000")},
    {"key": "col_semi", "title": "نیمچه کویل رنگی", "pct": Decimal("0.01"), "price": Decimal("130000")},
    {"key": "fh_semi", "title": "نیمچه کویل فول‌هارد", "pct": Decimal("0.05"), "price": Decimal("100000")},
    {"key": "galv_trim", "title": "سرقیچی گالوالوم", "pct": Decimal("0.005"), "price": Decimal("85000")},
    {"key": "col_trim", "title": "سرقیچی رنگی", "pct": Decimal("0.005"), "price": Decimal("100000")},
]

TOTAL_LOSS_PCT = sum(item["pct"] for item in WASTE_ITEMS)
OUTPUT_PCT = Decimal("1") - TOTAL_LOSS_PCT  # درصد ورق رنگی خروجی از هات رول ورودی

# ---------------------------------------------------------------------------
# مراحل مکالمه
# ---------------------------------------------------------------------------
ASK_HR_PRICE, ASK_WEIGHT, ASK_FEE = range(3)


def fmt(n: Decimal, decimals: int = 0) -> str:
    """قالب‌بندی عدد با جداکننده هزارگان به سبک فارسی/انگلیسی."""
    q = Decimal(10) ** -decimals
    n = n.quantize(q)
    s = f"{n:,.{decimals}f}"
    return s


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "سلام! 👋\n"
        "این ربات هزینه‌ها و ریز محاسبات تهاتر «هات رول ← ورق رنگی» را بر اساس "
        "درصدهای ضایعات فرایند کارخانه محاسبه می‌کند.\n\n"
        "برای شروع، *قیمت هات رول* را به تومان بر کیلوگرم وارد کنید (مثلاً 121000):",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ASK_HR_PRICE


async def ask_hr_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().replace(",", "")
    try:
        price = Decimal(text)
        if price <= 0:
            raise InvalidOperation
    except InvalidOperation:
        await update.message.reply_text("لطفاً یک عدد معتبر و مثبت برای قیمت هات رول وارد کنید (مثلاً 121000):")
        return ASK_HR_PRICE

    context.user_data["hr_price"] = price
    await update.message.reply_text(
        "وزن *ورق رنگی* مورد نیاز مشتری را به *تن* وارد کنید (مثلاً 386):",
        parse_mode="Markdown",
    )
    return ASK_WEIGHT


async def ask_weight(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().replace(",", "")
    try:
        weight_ton = Decimal(text)
        if weight_ton <= 0:
            raise InvalidOperation
    except InvalidOperation:
        await update.message.reply_text("لطفاً یک عدد معتبر و مثبت برای وزن ورق رنگی (به تن) وارد کنید (مثلاً 386):")
        return ASK_WEIGHT

    context.user_data["output_ton"] = weight_ton
    await update.message.reply_text(
        "نرخ *کارمزد تبدیل* را به تومان بر کیلوگرم وارد کنید (مثلاً 70000):",
        parse_mode="Markdown",
    )
    return ASK_FEE


async def ask_fee(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip().replace(",", "")
    try:
        fee_price = Decimal(text)
        if fee_price <= 0:
            raise InvalidOperation
    except InvalidOperation:
        await update.message.reply_text("لطفاً یک عدد معتبر و مثبت برای کارمزد وارد کنید (مثلاً 70000):")
        return ASK_FEE

    context.user_data["fee_price"] = fee_price

    hr_price = context.user_data["hr_price"]
    output_ton = context.user_data["output_ton"]

    result_text = calculate(hr_price=hr_price, fee_price=fee_price, output_ton=output_ton)
    await update.message.reply_text(result_text, parse_mode="Markdown")

    await update.message.reply_text(
        "برای یک محاسبه‌ی جدید، دستور /start را بزنید."
    )
    return ConversationHandler.END


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("محاسبه لغو شد. برای شروع دوباره /start را بزنید.", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END


def calculate(hr_price: Decimal, fee_price: Decimal, output_ton: Decimal) -> str:
    output_kg = output_ton * 1000
    hr_kg = output_kg / OUTPUT_PCT
    hr_ton = hr_kg / 1000

    lines = []
    lines.append("📊 *نتیجه محاسبات تهاتر هات رول ← ورق رنگی*\n")
    lines.append(f"▪️ بازده تبدیل فرایند: *{(OUTPUT_PCT*100).normalize()}٪*  (کل ضایعات: {(TOTAL_LOSS_PCT*100).normalize()}٪)")
    lines.append(f"▪️ ورق رنگی درخواستی: *{fmt(output_ton, 3)} تن* ({fmt(output_kg)} کیلوگرم)")
    lines.append(f"▪️ هات رول موردنیاز از مشتری: *{fmt(hr_ton, 3)} تن* ({fmt(hr_kg)} کیلوگرم)\n")

    lines.append("——— ریز ضایعات فرایند ———")
    scrap_value_total = Decimal("0")
    acid_value = Decimal("0")
    for item in WASTE_ITEMS:
        qty_kg = hr_kg * item["pct"]
        if item["price"] is None:
            acid_value = qty_kg * hr_price
            lines.append(
                f"• {item['title']}: {fmt(qty_kg)} کیلوگرم "
                f"— ارزش ازدست‌رفته: {fmt(acid_value)} تومان (بدون بازگشت)"
            )
        else:
            value = qty_kg * item["price"]
            scrap_value_total += value
            lines.append(
                f"• {item['title']}: {fmt(qty_kg)} کیلوگرم × {fmt(item['price'])} تومان "
                f"= {fmt(value)} تومان"
            )

    lines.append(f"\n💰 جمع ارزش ضایعات بازگشتی به مشتری: *{fmt(scrap_value_total)} تومان*")
    lines.append(f"💸 ارزش هات رول ازدست‌رفته در اسیدشویی: *{fmt(acid_value)} تومان*\n")

    lines.append("——— هزینه‌های نقدی مشتری ———")
    hr_value = hr_kg * hr_price
    fee_cost = hr_kg * fee_price
    transport_cost = hr_kg * TRANSPORT_PRICE

    lines.append(f"• ارزش هات رول ورودی: {fmt(hr_kg)} کیلوگرم × {fmt(hr_price)} تومان = {fmt(hr_value)} تومان")
    lines.append(f"• کارمزد تبدیل: {fmt(hr_kg)} کیلوگرم × {fmt(fee_price)} تومان = {fmt(fee_cost)} تومان")
    lines.append(f"• هزینه حمل: {fmt(hr_kg)} کیلوگرم × {fmt(TRANSPORT_PRICE)} تومان = {fmt(transport_cost)} تومان")

    total_gross = hr_value + fee_cost + transport_cost
    total_net = total_gross - scrap_value_total
    per_kg_net = total_net / output_kg
    per_kg_cash_only = (fee_cost + transport_cost - scrap_value_total) / output_kg

    lines.append(f"\n➕ جمع کل (هات رول + کارمزد + حمل): {fmt(total_gross)} تومان")
    lines.append(f"➖ کسر ارزش ضایعات بازگشتی: {fmt(scrap_value_total)} تومان")
    lines.append(f"✅ هزینه خالص کل: *{fmt(total_net)} تومان*\n")

    lines.append("——— قیمت تمام‌شده هر کیلوگرم ورق رنگی ———")
    lines.append(f"• با احتساب ارزش هات رول ورودی: *{fmt(per_kg_net)} تومان/کیلوگرم*")
    lines.append(
        f"• اگر هات رول قبلاً در اختیار مشتری بوده (فقط کارمزد+حمل منهای ضایعات): "
        f"*{fmt(per_kg_cash_only)} تومان/کیلوگرم*"
    )

    return "\n".join(lines)


# ⚠️ هشدار امنیتی: توکن مستقیماً اینجا نوشته شده. این فایل را جایی عمومی
# (گیت‌هاب، پیام‌رسان، ایمیل و ...) به اشتراک نگذارید — هرکس این توکن را
# ببیند می‌تواند کنترل کامل ربات را در دست بگیرد. اگر توکن قبلاً جایی لو رفته،
# از طریق @BotFather با دستور /revoke یک توکن جدید بگیرید و همان را اینجا جایگزین کنید.
HARDCODED_TOKEN = "8711583126:AAGj_c5gfH5XS6irFXBaiVLux2MgrH4iyrY"


def main() -> None:
    # اگر متغیر محیطی TELEGRAM_BOT_TOKEN ست شده باشد، همان اولویت دارد؛
    # در غیر این صورت از توکن هاردکد شده بالا استفاده می‌شود.
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or HARDCODED_TOKEN
    if not token:
        raise SystemExit(
            "توکن ربات تنظیم نشده است.\n"
            "یا آن را در متغیر HARDCODED_TOKEN بالای فایل بگذارید، "
            "یا export TELEGRAM_BOT_TOKEN='توکن شما' را قبل از اجرا اجرا کنید."
        )

    application = Application.builder().token(token).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            ASK_HR_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_hr_price)],
            ASK_WEIGHT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_weight)],
            ASK_FEE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_fee)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    application.add_handler(conv_handler)

    logger.info("ربات در حال اجراست...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
