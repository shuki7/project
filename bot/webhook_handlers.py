"""
Telegramボットのハンドラー定義（Webhook・Polling 共通）。

レシート写真はディスクに保存せず、圧縮後バイト列をメモリに保持し、
記帳確定時に Google Drive へ直接アップロードする。

フロー:
  1. 写真送信 → Gemini OCR → 解析結果を表示
  2. [💸 経費] [💰 売上] [✏️ 編集] [❌ キャンセル] の4択
  3. ✏️ 編集 → フィールド選択 → テキスト入力 → 戻る
  4. 確定 → Drive保存 → DB記帳（レシートの日付でyear/monthが決まる）
"""

import re
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

from config import TELEGRAM_ALLOWED_USERS, fmt_idr
from core.database import (
    insert_expense,
    insert_revenue,
    get_all_categories,
    sum_expenses,
    sum_revenue,
    upsert_category,
)
from bot.ocr import parse_receipt_from_bytes, classify_category, compress_image
from sync.gdrive import upload_receipt_bytes
from reports.generator import build_monthly_report_text
from reports.pdf_export import export_monthly_pdf, export_annual_pdf
from obsidian.md_writer import write_all_notes


# ── 金額パーサー ──────────────────────────────────────────────────────────────

def _parse_amount(text) -> float:
    """
    各種フォーマットの金額文字列を float に変換する。

    対応フォーマット:
      50000          → 50000.0
      50,000         → 50000.0  （カンマ千区切り）
      50.000         → 50000.0  （ドット千区切り・インドネシア式）
      1,500,000      → 1500000.0
      1.500.000      → 1500000.0
      1.500,50       → 1500.5   （欧州式：カンマが小数点）
      1500.50        → 1500.5   （ドットが小数点）
      Rp 1.500.000   → 1500000.0 （通貨記号付き）
    """
    if isinstance(text, (int, float)):
        return float(text)

    text = str(text).strip()
    # 通貨記号・スペース・IDR/Rp を除去
    text = re.sub(r'(?i)(idr|rp|¥|\$|€|£|\s)', '', text)
    if not text:
        return 0.0

    last_comma = text.rfind(',')
    last_dot   = text.rfind('.')

    if last_comma == -1 and last_dot == -1:
        # セパレータなし: "50000"
        return float(text)

    if last_comma > last_dot:
        # カンマが最後 → 欧州式小数点: "1.500,50" → 1500.50
        cleaned = text.replace('.', '').replace(',', '.')
    else:
        # ドットが最後
        after_dot = text[last_dot + 1:]
        if len(after_dot) <= 2:
            # 小数点付き: "1500.50" or "150.5"
            cleaned = text.replace(',', '')
        else:
            # 千区切り: "1.500.000" or "1,500.000"
            cleaned = text.replace(',', '').replace('.', '')

    return float(cleaned)


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
        "📷 レシートの写真を送ると自動で読み取ります。\n"
        "経費か売上か選んで記帳できます。\n\n"
        "✏️ 手動入力:\n"
        "  支出 50000 食費 ランチ\n"
        "  収入 100000 レッスン料 田中様\n\n"
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


# ── レシート写真 ──────────────────────────────────────────────────────────────

_pending: dict = {}

# フィールドの日本語ラベル
_FIELD_LABELS = {
    "name":    "名目",
    "amount":  "金額（数字のみ）",
    "date":    "日付（例: 2026-04-17）",
    "category":"カテゴリ",
    "payee":   "支払先",
    "method":  "支払方法（例: 現金・カード・TRANSFER）",
    "memo":    "メモ",
}


def _format_confirmation(pending: dict) -> str:
    """確認メッセージ本文を生成する。"""
    r = pending["result"]
    return (
        f"📋 解析結果\n{'─'*22}\n"
        f"📌 名目    : {r.get('name', '不明')}\n"
        f"💴 金額    : {fmt_idr(r.get('amount', 0))}\n"
        f"📅 日付    : {pending['date_str']}\n"
        f"🏪 支払先  : {r.get('payee', '') or '—'}\n"
        f"🗂 カテゴリ: {pending['category'] or '—'}\n"
        f"💳 支払方法: {r.get('payment_method', '') or '—'}\n"
        f"📝 メモ    : {r.get('memo', '') or '—'}\n"
        f"{'─'*22}\n"
        f"経費・売上どちらで記帳しますか？"
    )


def _confirm_keyboard() -> InlineKeyboardMarkup:
    """確認画面のボタン（4択）。"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💸 経費で記帳", callback_data="confirm_expense"),
            InlineKeyboardButton("💰 売上で記帳", callback_data="confirm_revenue"),
        ],
        [
            InlineKeyboardButton("✏️ 編集する",   callback_data="edit_menu"),
            InlineKeyboardButton("❌ キャンセル", callback_data="cancel"),
        ],
    ])


def _edit_keyboard() -> InlineKeyboardMarkup:
    """編集フィールド選択ボタン。"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📌 名目",     callback_data="edit_name"),
            InlineKeyboardButton("💴 金額",     callback_data="edit_amount"),
            InlineKeyboardButton("📅 日付",     callback_data="edit_date"),
        ],
        [
            InlineKeyboardButton("🗂 カテゴリ", callback_data="edit_category"),
            InlineKeyboardButton("🏪 支払先",   callback_data="edit_payee"),
            InlineKeyboardButton("💳 支払方法", callback_data="edit_method"),
        ],
        [
            InlineKeyboardButton("📝 メモ",     callback_data="edit_memo"),
            InlineKeyboardButton("← 戻る",      callback_data="back_to_confirm"),
        ],
    ])


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await auth_check(update):
        return

    await update.message.reply_text("🔍 レシートを解析中...")

    photo = update.message.photo[-1]
    file = await context.bot.get_file(photo.file_id)
    raw_bytes = bytes(await file.download_as_bytearray())

    # 圧縮（メモリ内のみ、ディスク保存なし）
    compressed = compress_image(raw_bytes)
    orig_kb = len(raw_bytes) // 1024
    comp_kb = len(compressed) // 1024

    # Gemini Flash で OCR
    result = parse_receipt_from_bytes(compressed)
    if "error" in result:
        await update.message.reply_text(
            f"❌ 解析に失敗しました: {result['error']}\n\n"
            "手動入力例: 支出 50000 食費 ランチ"
        )
        return

    # カテゴリ自動分類
    categories = [c["name"] for c in get_all_categories()]
    cat_name = classify_category(
        result.get("name", ""),
        result.get("payee", ""),
        result.get("category_hint", ""),
        categories,
    )

    # amount を float に正規化（Gemini が "1.500.000" などの文字列で返す場合に対応）
    try:
        result["amount"] = _parse_amount(result.get("amount", 0))
    except (ValueError, TypeError):
        result["amount"] = 0.0

    # レシートの日付を使用（なければ今日）→ 自動的に正しいyear/monthに記帳される
    date_str = result.get("date") or datetime.now().strftime("%Y-%m-%d")
    receipt_filename = (
        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{photo.file_id[:8]}.jpg"
    )

    # メモリに保持
    user_id = update.effective_user.id
    _pending[user_id] = {
        "result":           result,
        "category":         cat_name,
        "compressed_bytes": compressed,
        "receipt_filename": receipt_filename,
        "date_str":         date_str,
        "editing_field":    None,
        "image_info":       f"{orig_kb}KB → {comp_kb}KB",
    }

    await update.message.reply_text(
        _format_confirmation(_pending[user_id]),
        reply_markup=_confirm_keyboard(),
    )


# ── コールバック処理 ──────────────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    pending = _pending.get(user_id)

    # ── キャンセル
    if query.data == "cancel":
        _pending.pop(user_id, None)
        await query.edit_message_text("❌ キャンセルしました。")
        return

    # ── 編集メニューを表示
    if query.data == "edit_menu":
        if not pending:
            await query.edit_message_text("タイムアウトしました。もう一度写真を送ってください。")
            return
        await query.edit_message_text(
            _format_confirmation(pending) + "\n\n✏️ 編集するフィールドを選んでください：",
            reply_markup=_edit_keyboard(),
        )
        return

    # ── 編集メニューから確認画面に戻る
    if query.data == "back_to_confirm":
        if not pending:
            await query.edit_message_text("タイムアウトしました。もう一度写真を送ってください。")
            return
        pending["editing_field"] = None
        await query.edit_message_text(
            _format_confirmation(pending),
            reply_markup=_confirm_keyboard(),
        )
        return

    # ── フィールド編集開始（edit_name / edit_amount / ...）
    if query.data.startswith("edit_"):
        field = query.data[5:]  # "name", "amount", "date" など
        if not pending:
            await query.edit_message_text("タイムアウトしました。もう一度写真を送ってください。")
            return
        pending["editing_field"] = field
        label = _FIELD_LABELS.get(field, field)
        await query.edit_message_text(
            f"✏️ 新しい「{label}」を入力してください：\n"
            f"（現在の値: {_current_value(pending, field)}）"
        )
        return

    # ── 記帳確定（経費 or 売上）
    if query.data in ("confirm_expense", "confirm_revenue"):
        if not pending:
            await query.edit_message_text("タイムアウトしました。もう一度写真を送ってください。")
            return
        _pending.pop(user_id, None)

        result   = pending["result"]
        cat_name = pending["category"]
        date_str = pending["date_str"]
        cat_id   = upsert_category(cat_name) if cat_name else None

        # Google Drive へアップロード（日付フォルダに保存）
        drive_id = upload_receipt_bytes(
            pending["compressed_bytes"],
            pending["receipt_filename"],
            date_str,
        )
        receipt_ref = f"gdrive:{drive_id}" if drive_id else ""

        name   = result.get("name") or "（名目なし）"
        amount = float(result.get("amount") or 0)
        payee  = result.get("payee") or ""
        memo   = result.get("memo") or ""
        method = result.get("payment_method") or ""

        if query.data == "confirm_expense":
            insert_expense(
                name=name,
                amount=amount,
                date=date_str,
                category_id=cat_id,
                payment_method=method,
                payee=payee,
                memo=memo,
                receipt_path=receipt_ref,
            )
            type_label = "💸 経費"
        else:
            insert_revenue(
                name=name,
                amount=amount,
                date=date_str,
                student_name=payee,  # 売上の場合は支払先→student_name
                memo=memo,
                receipt_path=receipt_ref,
            )
            type_label = "💰 売上"

        # レシートの日付でObsidianノートを更新
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            write_all_notes(dt.year, dt.month)
        except Exception:
            pass

        drive_note = " ☁️" if drive_id else ""
        await query.edit_message_text(
            f"✅ {type_label}で記帳しました！{drive_note}\n"
            f"{'─'*22}\n"
            f"📌 {name}\n"
            f"💴 {fmt_idr(amount)}\n"
            f"📅 {date_str}（{date_str[:7]} に記帳）"
        )


def _current_value(pending: dict, field: str) -> str:
    """現在のフィールド値を文字列で返す（編集ヒント表示用）。"""
    r = pending["result"]
    mapping = {
        "name":     r.get("name", ""),
        "amount":   str(int(_parse_amount(r.get("amount", 0)))),
        "date":     pending.get("date_str", ""),
        "category": pending.get("category", ""),
        "payee":    r.get("payee", ""),
        "method":   r.get("payment_method", ""),
        "memo":     r.get("memo", ""),
    }
    return mapping.get(field, "") or "（未設定）"


# ── テキスト入力処理（フィールド編集 & 手動記帳）────────────────────────────

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await auth_check(update):
        return

    user_id = update.effective_user.id
    pending = _pending.get(user_id)
    text_input = update.message.text.strip()

    # ─ フィールド編集中の入力を受け取る
    if pending and pending.get("editing_field"):
        field = pending["editing_field"]
        r = pending["result"]

        if field == "name":
            r["name"] = text_input
        elif field == "amount":
            try:
                r["amount"] = _parse_amount(text_input)
            except (ValueError, TypeError):
                await update.message.reply_text(
                    "❌ 金額の形式が正しくありません。\n"
                    "入力例: 50000 / 50,000 / 1.500.000 / 1,500,000"
                )
                return
        elif field == "date":
            # YYYY-MM-DD 形式に正規化
            raw = text_input.replace("/", "-").replace(".", "-")
            try:
                datetime.strptime(raw[:10], "%Y-%m-%d")
                pending["date_str"] = raw[:10]
            except ValueError:
                await update.message.reply_text("❌ 日付は YYYY-MM-DD 形式で入力してください（例: 2026-04-17）")
                return
        elif field == "category":
            pending["category"] = text_input
        elif field == "payee":
            r["payee"] = text_input
        elif field == "method":
            r["payment_method"] = text_input
        elif field == "memo":
            r["memo"] = text_input

        pending["editing_field"] = None

        # 更新後の確認画面を再表示
        await update.message.reply_text(
            "✅ 更新しました。\n\n" + _format_confirmation(pending),
            reply_markup=_confirm_keyboard(),
        )
        return

    # ─ 手動テキスト記帳（例: 支出 50000 食費 ランチ）
    parts = text_input.split()
    if len(parts) < 3:
        return

    record_type = parts[0]
    try:
        amount = _parse_amount(parts[1])
    except (ValueError, TypeError):
        await update.message.reply_text(
            "❌ 金額の形式が正しくありません。\n"
            "入力例: 支出 50000 食費 / 支出 1.500.000 食費"
        )
        return

    label = parts[2]
    memo  = " ".join(parts[3:]) if len(parts) > 3 else ""
    today = datetime.now().strftime("%Y-%m-%d")

    if record_type in ("支出", "経費", "expense"):
        cat_id = upsert_category(label)
        insert_expense(name=memo or label, amount=amount, date=today,
                       category_id=cat_id, memo=memo)
        await update.message.reply_text(
            f"💸 支出を記帳しました\n{label}: {fmt_idr(amount)}"
        )

    elif record_type in ("収入", "売上", "revenue"):
        insert_revenue(name=label, amount=amount, date=today, memo=memo)
        await update.message.reply_text(
            f"💰 収入を記帳しました\n{label}: {fmt_idr(amount)}"
        )


# ── ハンドラー登録 ────────────────────────────────────────────────────────────

def register_handlers(app: Application):
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("report",  cmd_report))
    app.add_handler(CommandHandler("pdf",     cmd_pdf))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(CallbackQueryHandler(handle_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
