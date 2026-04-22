import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── ローカルパス ──────────────────────────────────────────────
# 優先順位:
#   1. GDRIVE_LOCAL_PATH  — Google Drive同期フォルダ
#   2. DATA_DIR           — 任意のデータ保存先（サーバーのpublic_html外推奨）
#   3. デフォルト         — プロジェクト直下の data/
#
# cPanelサーバーでの推奨設定 (.env):
#   DATA_DIR=/home/ordp5944/keiri_data
_gdrive_local = os.getenv("GDRIVE_LOCAL_PATH", "")
_data_dir     = os.getenv("DATA_DIR", "")
BASE_DIR = (
    Path(_gdrive_local) if _gdrive_local
    else Path(_data_dir) if _data_dir
    else Path(__file__).parent / "data"
)

DB_PATH        = BASE_DIR / "kakeibo.db"
PROJECTS_FILE  = BASE_DIR / "projects.json"
RECEIPTS_DIR   = BASE_DIR / "receipts"
OBSIDIAN_DIR   = BASE_DIR / "Obsidian"
REPORTS_DIR    = BASE_DIR / "reports"

# ── Notion ────────────────────────────────────────────────────
NOTION_TOKEN = os.getenv("NOTION_TOKEN", "")

# NotionデータベースID（DB本体）
NOTION_DB = {
    "category":        "1bf2fd7eb8c881ec87ade2ca408306bf",
    "expense_2025":    "1bf2fd7eb8c881a28bddf9c00e47ff26",
    "expense_2026":    "1c52fd7eb8c8800e8989e9208a9b598c",
    "revenue_2025":    "1bf2fd7eb8c88120b122c14c5db69ef4",
    "revenue_2026":    "1c52fd7eb8c880f385edd3b9da956358",
}

# ── Telegram ──────────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
_allowed = os.getenv("TELEGRAM_ALLOWED_USERS", "")
TELEGRAM_ALLOWED_USERS: list[int] = [int(x) for x in _allowed.split(",") if x.strip()]

# ── Google Gemini ─────────────────────────────────────────────
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# ── Google Drive API ──────────────────────────────────────────
GDRIVE_FOLDER_ID = os.getenv("GDRIVE_FOLDER_ID", "")
GDRIVE_CREDENTIALS_PATH = Path(__file__).parent / "credentials.json"
GDRIVE_TOKEN_PATH       = Path(__file__).parent / "token.json"
# サーバー向け: サービスアカウント JSON のパス（.env 相対 or 絶対）
_sa = os.getenv("GDRIVE_SERVICE_ACCOUNT", "")
GDRIVE_SERVICE_ACCOUNT_PATH = (
    Path(_sa) if _sa and Path(_sa).is_absolute()
    else (Path(__file__).parent / _sa) if _sa
    else None
)

# ── 認証 ──────────────────────────────────────────────────────
LOGIN_EMAIL    = os.getenv("LOGIN_EMAIL", "uemurashuki@gmail.com")
LOGIN_PASSWORD = os.getenv("LOGIN_PASSWORD", "Enrichno1@")
LOGIN_RESET_TOKEN = os.getenv("LOGIN_RESET_TOKEN", "")

# ── コース設定（人数カウント用キーワード）────────────────────────
COURSE_KEYWORDS = {
    "特定技能": os.getenv("KEYWORD_TOKUTEI", "特定技能"),
    "JOB Matting": os.getenv("KEYWORD_JOB", "JOB"),
}

# ── 会社情報 ──────────────────────────────────────────────────
COMPANY_NAME    = "SSP PROJECT"
COMPANY_CAPITAL = 940_000_000  # IDR

# ── 通貨 ──────────────────────────────────────────────────────
CURRENCY        = "IDR"
CURRENCY_SYMBOL = "Rp"

def fmt_idr(amount: float) -> str:
    """金額をIDR表記にフォーマット。例: Rp 1.500.000"""
    if amount is None:
        return "Rp 0"
    # インドネシア式：千区切りにピリオドを使用
    return f"Rp {int(amount):,}".replace(",", ".")
