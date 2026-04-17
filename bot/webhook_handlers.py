"""
Telegramボットのハンドラー定義（Webhook・Polling 共通）。
telegram_bot.py のPollingモードと、app.py のWebhookモードの両方で使用する。
"""

import sys
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

import io as _io

from PIL import Image as _Image

from config import TELEGRAM_ALLOWED_USERS, RECEIPTS_DIR, fmt_idr
from sync.gdrive import upload_receipt
from core.database import (
    insert_expense,
    insert_revenue,
    get_all_categories,
    sum_expenses,
    sum_revenue,
    upsert_category,
)
from bot.ocr import parse_receipt_from_bytes, classify_category
from reports.generator import build_monthly_report_text
from reports.pdf_export import export_monthly_pdf, export_annual_pdf
from obsidian.md_writer import write_all_notes


# ── 認証 ─────────────────────────────────────────────────────────────────────

def is_allowed(user_id: int) -> bool:
    if not TELEGRAM_ALLOWED_USERS:
        return True
    return user_id in TELEGRAM_ALLOWED_USERS


async def auth_check(update: Update) -> bool:
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("このボットは許可されたユーザーのみ使用できます。")
        return False
    return True


# ── /start ───────────────────────────────────────────────────────────────────

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


# ── /balance ─────────────────────────────────────────────────────────────────

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
        f"{'─'*20}\n"
        f"収入: {fmt_idr(inc)}\n"
        f"支出: {fmt_idr(exp)}\n"
        f"損益: {sign}{fmt_idr(profit)}\n"
    )
    await update.message.reply_text(text)


# ── /report ──────────────────────────────────────────────────────────────────

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
            await update.message.reply_text("形式: /report 2026-03")
            return
    text = build_monthly_report_text(year, month)
    await update.message.reply_text(text, parse_mode="Markdown")


# ── /pdf ─────────────────────────────────────────────────────────────────────

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
            await update.message.reply_text("形式: /pdf 2026-03 または /pdf 2026")
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


# ── 画像圧縮ユーティリティ ─────────────────────────────────────────────────────

def _compress_image(image_bytes: bytes,
                    max_px: int = 1600,
                    quality: int = 83) -> bytes:
    """
    画質を保ちながらファイルサイズを圧縮する。

    - 長辺を max_px 以下にリサイズ（それ以下なら変更なし）
    - EXIF の回転情報を反映
    - RGBA/P モードを RGB に変換
    - JPEG quality=83 で再エンコード（原画の 20〜40% 程度になる）
    """
    try:
        img = _Image.open(_io.BytesIO(image_bytes))

        # EXIF 回転補正
        try:
            exif = img._getexif()
            if exif:
                orientation = exif.get(274)  # 274 = Orientation tag
                if orientation == 3:
                    img = img.rotate(180, expand=True)
                elif orientation == 6:
                    img = img.rotate(270, expand=True)
                elif orientation == 8:
                    img = img.rotate(90, expand=True)
        except Exception:
            pass

        # RGB 変換
        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")

        # リサイズ（大きすぎる場合のみ）
        img.thumbnail((max_px, max_px), _Image.LANCZOS)

        buf = _io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        compressed = buf.getvalue()

        # 圧縮後のほうが大きい稀なケースはオリジナルを返す
        return compressed if len(compressed) < len(image_bytes) else image_bytes

    except Exception:
        return image_bytes  # 失敗時はオリジナルをそのまま使用


# ── レシート写真 ──────────────────────────────────────────────────────────────

_pending: dict[int, dict] = {}


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await auth_check(update):
        return

    await update.message.reply_text("レシートを解析中...")

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    image_bytes = await file.download_as_bytearray()

    result = parse_receipt_from_bytes(bytes(image_bytes), "image/jpeg")

    if "error" in result:
        await update.message.reply_text(
            f"解析に失敗しました: {result['error']}\n\n"
            "手動入力: 支出 50000 食費 ランチ"
        )
        return

    categories = [c["name"] for c in get_all_categories()]
    cat_name = classify_category(
        result.get("name", ""),
        result.get("payee", ""),
        result.get("category_hint", ""),
        categories,
    )

    # レシート画像を圧縮して保存
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    receipt_filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{photo.file_id[:8]}.jpg"
    receipt_path = RECEIPTS_DIR / receipt_filename
    compressed_bytes = _compress_image(bytes(image_bytes))
    with open(receipt_path, "wb") as f:
        f.write(compressed_bytes)

    # 圧縮率をログ
    ratio = len(compressed_bytes) / max(len(image_bytes), 1) * 100
    orig_kb  = len(image_bytes) // 1024
    comp_kb  = len(compressed_bytes) // 1024

    user_id = update.effective_user.id
    date_str = result.get("date") or datetime.now().strftime("%Y-%m-%d")
    _pending[user_id] = {
        "result": result,
        "category": cat_name,
        "receipt_path": str(receipt_path),
        "date_str": date_str,
    }

    text = (
        f"解析結果\n{'─'*20}\n"
        f"名目: {result.get('name', '不明')}\n"
        f"金額: {fmt_idr(result.get('amount', 0))}\n"
        f"日付: {date_str}\n"
        f"支払先: {result.get('payee', '')}\n"
        f"カテゴリ: {cat_name}\n"
        f"支払い: {result.get('payment_method', '不明')}\n"
        f"メモ: {result.get('memo', '')}\n"
        f"{'─'*20}\n"
        f"画像: {orig_kb}KB → {comp_kb}KB ({ratio:.0f}%)\n\n"
        f"この内容で記帳しますか？"
    )
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("記帳する", callback_data="confirm_expense"),
        InlineKeyboardButton("キャンセル", callback_data="cancel_expense"),
    ]])
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

        result    = pending["result"]
        cat_name  = pending["category"]
        date_str  = pending.get("date_str") or datetime.now().strftime("%Y-%m-%d")
        cat_id    = upsert_category(cat_name) if cat_name else None

        insert_expense(
            name=result.get("name") or "（名目なし）",
            amount=float(result.get("amount") or 0),
            date=date_str,
            category_id=cat_id,
            payment_method=result.get("payment_method"),
            payee=result.get("payee"),
            memo=result.get("memo"),
            receipt_path=pending["receipt_path"],
        )

        # Google Drive にレシートをアップロード
        drive_ok = upload_receipt(Path(pending["receipt_path"]), date_str)

        dt = datetime.strptime(date_str, "%Y-%m-%d")
        write_all_notes(dt.year, dt.month)

        drive_note = " ☁️Drive保存済" if drive_ok else ""
        await query.edit_message_text(
            f"記帳しました！{drive_note}\n"
            f"{result.get('name', '')} — {fmt_idr(result.get('amount', 0))}"
        )


# ── テキスト手動入力 ──────────────────────────────────────────────────────────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await auth_check(update):
        return
    parts = update.message.text.strip().split()
    if len(parts) < 3:
        return

    record_type = parts[0]
    try:
        amount = float(parts[1].replace(",", "").replace(".", ""))
    except ValueError:
        await update.message.reply_text("金額は数値で入力してください。")
        return

    label = parts[2]
    memo = " ".join(parts[3:]) if len(parts) > 3 else ""
    today = datetime.now().strftime("%Y-%m-%d")

    if record_type in ("支出", "経費", "expense"):
        cat_id = upsert_category(label)
        insert_expense(name=memo or label, amount=amount, date=today,
                       category_id=cat_id, memo=memo)
        await update.message.reply_text(f"支出を記帳しました\n{label}: {fmt_idr(amount)}")

    elif record_type in ("収入", "売上", "revenue"):
        insert_revenue(name=label, amount=amount, date=today, memo=memo)
        await update.message.reply_text(f"収入を記帳しました\n{label}: {fmt_idr(amount)}")


# ── ハンドラー登録 ────────────────────────────────────────────────────────────

def register_handlers(app: Application):
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("report",  cmd_report))
    app.add_handler(CommandHandler("pdf",     cmd_pdf))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
