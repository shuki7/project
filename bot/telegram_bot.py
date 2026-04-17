"""
Telegramボット - 家計簿アプリのメインインターフェース

コマンド一覧:
  /start    - 使い方の説明
  /report   - 今月の収支レポート
  /report YYYY-MM - 指定月のレポート
  /pdf      - 今月のPDFレポートを生成・送信
  /pdf YYYY - 年次PDFを生成・送信
  /balance  - 現在の収支サマリー

写真を送信 → レシートを自動解析して記帳
"""

import asyncio
import io
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

from config import (
    TELEGRAM_TOKEN,
    TELEGRAM_ALLOWED_USERS,
    RECEIPTS_DIR,
    fmt_idr,
)
from core.database import (
    init_db,
    insert_expense,
    insert_revenue,
    get_all_categories,
    sum_expenses,
    sum_revenue,
    monthly_summary,
    upsert_category,
)
from bot.ocr import parse_receipt_from_bytes, classify_category
from reports.generator import build_monthly_report_text
from reports.pdf_export import export_monthly_pdf, export_annual_pdf
from obsidian.md_writer import write_all_notes
from sync.gdrive import sync_to_drive


# ─────────────────────────────────────────────────────────────────────────────
# 認証ガード
# ─────────────────────────────────────────────────────────────────────────────

def is_allowed(user_id: int) -> bool:
    if not TELEGRAM_ALLOWED_USERS:
        return True  # 未設定 = 全員許可
    return user_id in TELEGRAM_ALLOWED_USERS


async def auth_check(update: Update) -> bool:
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("このボットは許可されたユーザーのみ使用できます。")
        return False
    return True


# ─────────────────────────────────────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await auth_check(update):
        return
    text = (
        "家計簿ボットへようこそ！\n\n"
        "レシートの写真を送ると自動で記帳します。\n\n"
        "コマンド一覧:\n"
        "/report — 今月の収支レポート\n"
        "/report 2026-03 — 指定月のレポート\n"
        "/pdf — 今月のPDF出力\n"
        "/pdf 2026 — 2026年の年次PDF\n"
        "/balance — 収支サマリー\n"
    )
    await update.message.reply_text(text)


# ─────────────────────────────────────────────────────────────────────────────
# /balance
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await auth_check(update):
        return
    now = datetime.now()
    inc = sum_revenue(now.year, now.month)
    exp = sum_expenses(now.year, now.month)
    profit = inc - exp
    sign = "+" if profit >= 0 else ""
    text = (
        f"{now.year}年{now.month}月の収支\n"
        f"{'─' * 20}\n"
        f"収入: {fmt_idr(inc)}\n"
        f"支出: {fmt_idr(exp)}\n"
        f"損益: {sign}{fmt_idr(profit)}\n"
    )
    await update.message.reply_text(text)


# ─────────────────────────────────────────────────────────────────────────────
# /report [YYYY-MM]
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await auth_check(update):
        return
    now = datetime.now()
    year, month = now.year, now.month

    if context.args:
        try:
            parts = context.args[0].split("-")
            year = int(parts[0])
            month = int(parts[1]) if len(parts) > 1 else month
        except (ValueError, IndexError):
            await update.message.reply_text("形式が違います。例: /report 2026-03")
            return

    text = build_monthly_report_text(year, month)
    await update.message.reply_text(text, parse_mode="Markdown")


# ─────────────────────────────────────────────────────────────────────────────
# /pdf [YYYY or YYYY-MM]
# ─────────────────────────────────────────────────────────────────────────────

async def cmd_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await auth_check(update):
        return
    now = datetime.now()
    year, month = now.year, now.month

    annual = False
    if context.args:
        try:
            parts = context.args[0].split("-")
            year = int(parts[0])
            if len(parts) == 1:
                annual = True
            else:
                month = int(parts[1])
        except (ValueError, IndexError):
            await update.message.reply_text("形式が違います。例: /pdf 2026-03 または /pdf 2026")
            return

    await update.message.reply_text("PDFを生成中...")

    if annual:
        pdf_path = export_annual_pdf(year)
        caption = f"{year}年 年次レポート"
    else:
        pdf_path = export_monthly_pdf(year, month)
        caption = f"{year}年{month}月 月次レポート"

    with open(pdf_path, "rb") as f:
        await update.message.reply_document(
            document=f,
            filename=Path(pdf_path).name,
            caption=caption,
        )


# ─────────────────────────────────────────────────────────────────────────────
# レシート写真の処理
# ─────────────────────────────────────────────────────────────────────────────

# 一時的な解析結果を保持（ユーザーIDをキーとする）
_pending: dict[int, dict] = {}


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await auth_check(update):
        return

    await update.message.reply_text("レシートを解析中...")

    # 最高解像度の写真を取得
    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    image_bytes = await file.download_as_bytearray()

    # OCR解析
    result = parse_receipt_from_bytes(bytes(image_bytes), "image/jpeg")

    if "error" in result:
        await update.message.reply_text(
            f"解析に失敗しました: {result['error']}\n\n"
            "手動で入力してください（例）:\n支出 5000 食費 ランチ"
        )
        return

    # カテゴリを分類
    categories = [c["name"] for c in get_all_categories()]
    cat_name = classify_category(
        result.get("name", ""),
        result.get("payee", ""),
        result.get("category_hint", ""),
        categories,
    )

    # レシート画像を保存
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    receipt_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{photo.file_id[:8]}.jpg"
    receipt_path = RECEIPTS_DIR / receipt_filename
    with open(receipt_path, "wb") as f:
        f.write(image_bytes)

    # 解析結果を一時保存
    user_id = update.effective_user.id
    _pending[user_id] = {
        "result": result,
        "category": cat_name,
        "receipt_path": str(receipt_path),
    }

    # 確認メッセージを表示
    date_str = result.get("date") or datetime.now().strftime("%Y-%m-%d")
    text = (
        f"解析結果\n"
        f"{'─' * 20}\n"
        f"名目: {result.get('name', '不明')}\n"
        f"金額: {fmt_idr(result.get('amount', 0))}\n"
        f"日付: {date_str}\n"
        f"支払先: {result.get('payee', '')}\n"
        f"カテゴリ: {cat_name}\n"
        f"支払い: {result.get('payment_method', '不明')}\n"
        f"メモ: {result.get('memo', '')}\n\n"
        f"この内容で記帳しますか？"
    )

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("記帳する", callback_data="confirm_expense"),
            InlineKeyboardButton("キャンセル", callback_data="cancel_expense"),
        ]
    ])
    await update.message.reply_text(text, reply_markup=keyboard)


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    if query.data == "cancel_expense":
        _pending.pop(user_id, None)
        await query.edit_message_text("キャンセルしました。")
        return

    if query.data == "confirm_expense":
        pending = _pending.pop(user_id, None)
        if not pending:
            await query.edit_message_text("タイムアウトしました。もう一度送信してください。")
            return

        result = pending["result"]
        cat_name = pending["category"]
        receipt_path = pending["receipt_path"]

        # カテゴリIDを取得（なければ作成）
        cat_id = upsert_category(cat_name) if cat_name else None

        date_str = result.get("date") or datetime.now().strftime("%Y-%m-%d")

        insert_expense(
            name=result.get("name") or "（名目なし）",
            amount=float(result.get("amount") or 0),
            date=date_str,
            category_id=cat_id,
            payment_method=result.get("payment_method"),
            payee=result.get("payee"),
            memo=result.get("memo"),
            receipt_path=receipt_path,
        )

        # ObsidianのMarkdownを更新
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        write_all_notes(dt.year, dt.month)

        await query.edit_message_text(
            f"記帳しました！\n{result.get('name', '')} — {fmt_idr(result.get('amount', 0))}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# テキスト入力（簡易手動記帳）
# 形式: 支出 <金額> <カテゴリ> <メモ>
#       収入 <金額> <名前> <メモ>
# ─────────────────────────────────────────────────────────────────────────────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await auth_check(update):
        return

    text = update.message.text.strip()
    parts = text.split()

    if len(parts) < 3:
        return  # コマンドでもなく、フォーマットにも合わないテキストは無視

    record_type = parts[0]
    try:
        amount = float(parts[1].replace(",", "").replace(".", ""))
    except ValueError:
        await update.message.reply_text("金額は数値で入力してください。")
        return

    category_or_name = parts[2]
    memo = " ".join(parts[3:]) if len(parts) > 3 else ""
    today = datetime.now().strftime("%Y-%m-%d")

    if record_type in ("支出", "経費", "expense"):
        cat_id = upsert_category(category_or_name)
        insert_expense(
            name=memo or category_or_name,
            amount=amount,
            date=today,
            category_id=cat_id,
            memo=memo,
        )
        await update.message.reply_text(
            f"支出を記帳しました\n{category_or_name}: {fmt_idr(amount)}"
        )

    elif record_type in ("収入", "売上", "revenue"):
        insert_revenue(
            name=category_or_name,
            amount=amount,
            date=today,
            memo=memo,
        )
        await update.message.reply_text(
            f"収入を記帳しました\n{category_or_name}: {fmt_idr(amount)}"
        )
    else:
        # 認識できないテキストは無視
        pass


# ─────────────────────────────────────────────────────────────────────────────
# ボット起動
# ─────────────────────────────────────────────────────────────────────────────

def main():
    if not TELEGRAM_TOKEN:
        sys.exit(1)

    init_db()

    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("report", cmd_report))
    app.add_handler(CommandHandler("pdf", cmd_pdf))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
