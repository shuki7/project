"""
SQLiteデータベースの初期化とCRUD操作。
kakeibo.db はGoogle Driveの同期フォルダ内に保存される。
"""

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import DB_PATH


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    # 優先順位: 1. 引数 2. flask.g.db_path 3. デフォルトDB_PATH
    target_db = db_path
    if not target_db:
        try:
            from flask import g, has_app_context
            if has_app_context():
                target_db = getattr(g, "db_path", None)
        except (ImportError, RuntimeError):
            pass
    
    if not target_db:
        target_db = DB_PATH

    target_db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target_db)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def transaction(db_path: Optional[Path] = None):
    conn = get_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# スキーマ定義
# ─────────────────────────────────────────────────────────────────────────────

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS budgets (
    id          TEXT PRIMARY KEY,
    category_id TEXT NOT NULL,
    year        INTEGER NOT NULL,
    month       INTEGER NOT NULL DEFAULT 0,
    amount      REAL NOT NULL DEFAULT 0,
    UNIQUE(category_id, year, month),
    FOREIGN KEY (category_id) REFERENCES categories(id)
);

CREATE TABLE IF NOT EXISTS categories (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    notion_id   TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS expenses (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,          -- 名目
    amount          REAL NOT NULL DEFAULT 0, -- 金額 (IDR)
    date            TEXT NOT NULL,           -- YYYY-MM-DD
    year            INTEGER NOT NULL,
    month           INTEGER NOT NULL,
    category_id     TEXT,
    payment_method  TEXT,                   -- CASH / TRANSFER / DEBUT / 立替え
    payee           TEXT,                   -- 支払先
    memo            TEXT,
    is_recurring    INTEGER DEFAULT 0,      -- 定期フラグ (1=true)
    receipt_path    TEXT,                   -- レシート画像のローカルパス
    notion_id       TEXT UNIQUE,            -- NotionページID（重複防止）
    contact_id      TEXT,                   -- 取引先ID (NEW)
    job_id          TEXT,                   -- 案件ID (NEW)
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (category_id) REFERENCES categories(id)
);

CREATE TABLE IF NOT EXISTS revenue (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,          -- 名前
    amount          REAL NOT NULL DEFAULT 0, -- 金額 (IDR)
    date            TEXT NOT NULL,           -- YYYY-MM-DD
    year            INTEGER NOT NULL,
    month           INTEGER NOT NULL,
    student_name    TEXT,                   -- 生徒名
    memo            TEXT,
    receipt_path    TEXT,
    notion_id       TEXT UNIQUE,
    contact_id      TEXT,                   -- 顧客ID (NEW)
    job_id          TEXT,                   -- 案件ID (NEW)
    category_id     TEXT,                   -- 売上カテゴリ (NEW)
    created_at      TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (category_id) REFERENCES categories(id)
);

CREATE TABLE IF NOT EXISTS tasks (
    id              TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    description     TEXT,
    status          TEXT DEFAULT 'todo',    -- todo, done
    priority        TEXT DEFAULT 'middle',  -- low, middle, high
    due_date        TEXT,
    is_archived     INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS contacts (
    id              TEXT PRIMARY KEY,
    type            TEXT NOT NULL,          -- vendor, customer
    name            TEXT NOT NULL,
    contact_person  TEXT,
    phone           TEXT,
    email           TEXT,
    address         TEXT,
    bank_info       TEXT,
    memo            TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS project_info (
    id              TEXT PRIMARY KEY,       -- 'main'
    bank_info       TEXT,                   -- SWIFTコード等
    facility_info   TEXT,                   -- 住所・公共料金情報等
    emergency_info  TEXT,                   -- 緊急連絡先等
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS jobs (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    start_date      TEXT,
    status          TEXT DEFAULT 'active',  -- active, closed
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    emoji       TEXT,
    color       TEXT,
    description TEXT,
    status      TEXT DEFAULT 'active',
    is_group    INTEGER DEFAULT 0,      -- グループ/マスターフラグ (1=true)
    sort_order  INTEGER DEFAULT 0,
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);

-- Phase 3: プロジェクト重要情報（カテゴリ別、複数件OK）
CREATE TABLE IF NOT EXISTS project_info_items (
    id          TEXT PRIMARY KEY,
    project_id  INTEGER NOT NULL,
    category    TEXT NOT NULL,    -- address, wifi, bank, utility, emergency, contract, other
    label       TEXT,             -- ユーザー定義ラベル（例: メイン銀行）
    fields_json TEXT,             -- JSON: フィールドの key/value
    sort_order  INTEGER DEFAULT 0,
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);

-- Phase 3: プロジェクト添付ファイル（Google Drive 上）
CREATE TABLE IF NOT EXISTS project_attachments (
    id            TEXT PRIMARY KEY,
    project_id    INTEGER NOT NULL,
    info_item_id  TEXT,             -- project_info_items.id（任意、紐付け用）
    staff_id      TEXT,             -- project_staff.id（任意、紐付け用）
    category      TEXT,             -- contract, photo, document, other
    filename      TEXT NOT NULL,
    drive_file_id TEXT,
    drive_url     TEXT,
    mime_type     TEXT,
    size_bytes    INTEGER,
    notes         TEXT,
    uploaded_at   TEXT DEFAULT (datetime('now'))
);

-- Phase 4: プロジェクトスタッフ
CREATE TABLE IF NOT EXISTS project_staff (
    id               TEXT PRIMARY KEY,
    project_id       INTEGER NOT NULL,
    name             TEXT NOT NULL,         -- 氏名
    name_kana        TEXT,                  -- フリガナ/ローマ字
    position         TEXT,                  -- 役職/職種
    employment_type  TEXT,                  -- 正社員/契約/パート/インターン/その他
    status           TEXT DEFAULT 'active', -- active / inactive
    whatsapp         TEXT,
    email            TEXT,
    phone            TEXT,
    address          TEXT,
    birthday         TEXT,                  -- YYYY-MM-DD
    hire_date        TEXT,                  -- 入社日
    termination_date TEXT,                  -- 退社日
    working_hours    TEXT,                  -- 勤務時間（自由記述）
    salary           TEXT,                  -- 給与（自由記述：例 Rp 5,000,000 / 月）
    bank_info        TEXT,                  -- 振込先（自由記述）
    emergency_contact TEXT,                 -- 緊急連絡先
    photo_url        TEXT,                  -- 顔写真URL
    memo             TEXT,
    sort_order       INTEGER DEFAULT 0,
    created_at       TEXT DEFAULT (datetime('now')),
    updated_at       TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_expenses_year_month ON expenses(year, month);
CREATE INDEX IF NOT EXISTS idx_revenue_year_month  ON revenue(year, month);
CREATE INDEX IF NOT EXISTS idx_expenses_date       ON expenses(date);
CREATE INDEX IF NOT EXISTS idx_revenue_date        ON revenue(date);
"""


def init_db(db_path=None):
    """データベースとテーブルを初期化する。"""
    with transaction(db_path) as conn:
        conn.executescript(SCHEMA_SQL)
        # マイグレーション: 既存テーブルへのカラム追加
        for sql in [
            "ALTER TABLE revenue ADD COLUMN receipt_path TEXT",
            "ALTER TABLE expenses ADD COLUMN contact_id TEXT",
            "ALTER TABLE expenses ADD COLUMN job_id TEXT",
            "ALTER TABLE revenue ADD COLUMN contact_id TEXT",
            "ALTER TABLE revenue ADD COLUMN job_id TEXT",
            "ALTER TABLE revenue ADD COLUMN category_id TEXT",
            # Phase 2: タスクをプロジェクトに紐づける
            "ALTER TABLE tasks ADD COLUMN project_id INTEGER",
            "ALTER TABLE tasks ADD COLUMN sort_order INTEGER DEFAULT 0",
            "ALTER TABLE tasks ADD COLUMN updated_at TEXT",
            "ALTER TABLE tasks ADD COLUMN assignee TEXT",
            # Phase 4: 添付ファイルをスタッフにも紐付け可能に
            "ALTER TABLE project_attachments ADD COLUMN staff_id TEXT",
            # Phase 4.1: プロジェクトに開始日・依頼者・担当者を追加
            "ALTER TABLE projects ADD COLUMN start_date TEXT",
            "ALTER TABLE projects ADD COLUMN client_name TEXT",
            "ALTER TABLE projects ADD COLUMN manager_name TEXT",
            "ALTER TABLE projects ADD COLUMN is_group INTEGER DEFAULT 0",
        ]:
            try:
                conn.execute(sql)
            except Exception:
                pass  # already exists

        # プロジェクトのシード（初回のみ BALI JAPAN DREAM を作成）
        row = conn.execute("SELECT COUNT(*) FROM projects").fetchone()
        if row[0] == 0:
            conn.execute(
                "INSERT INTO projects (name, emoji, color, description, sort_order) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    "BALI JAPAN DREAM",
                    "🇮🇩",
                    "#e2c97e",
                    "PT BALI JAPAN DREAM — 特定技能・JOB Matching事業",
                    0,
                ),
            )


# ─────────────────────────────────────────────────────────────────────────────
# カテゴリ
# ─────────────────────────────────────────────────────────────────────────────

def upsert_category(name: str, notion_id: str = None) -> str:
    """カテゴリをINSERT OR IGNOREして、そのIDを返す。"""
    with transaction() as conn:
        row = conn.execute("SELECT id FROM categories WHERE name = ?", (name,)).fetchone()
        if row:
            return row["id"]
        cat_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO categories (id, name, notion_id) VALUES (?, ?, ?)",
            (cat_id, name, notion_id),
        )
        return cat_id


def get_all_categories() -> list[dict]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM categories ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# 支出（経費）
# ─────────────────────────────────────────────────────────────────────────────

def insert_expense(
    name: str,
    amount: float,
    date: str,
    category_id: str = None,
    payment_method: str = None,
    payee: str = None,
    memo: str = None,
    is_recurring: bool = False,
    receipt_path: str = None,
    notion_id: str = None,
    contact_id: str = None,
    job_id: str = None,
) -> str:
    dt = datetime.strptime(date[:10], "%Y-%m-%d")
    exp_id = str(uuid.uuid4())
    with transaction() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO expenses
               (id, name, amount, date, year, month, category_id,
                payment_method, payee, memo, is_recurring, receipt_path, notion_id, contact_id, job_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (exp_id, name, amount, date[:10], dt.year, dt.month,
             category_id, payment_method, payee, memo,
             1 if is_recurring else 0, receipt_path, notion_id, contact_id, job_id),
        )
    return exp_id


def get_expenses(year: int = None, month: int = None) -> list[dict]:
    conn = get_connection()
    if year and month:
        rows = conn.execute(
            "SELECT e.*, c.name as category_name FROM expenses e "
            "LEFT JOIN categories c ON e.category_id = c.id "
            "WHERE e.year=? AND e.month=? ORDER BY e.date",
            (year, month),
        ).fetchall()
    elif year:
        rows = conn.execute(
            "SELECT e.*, c.name as category_name FROM expenses e "
            "LEFT JOIN categories c ON e.category_id = c.id "
            "WHERE e.year=? ORDER BY e.date",
            (year,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT e.*, c.name as category_name FROM expenses e "
            "LEFT JOIN categories c ON e.category_id = c.id "
            "ORDER BY e.date"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def sum_expenses(year: int, month: int = None) -> float:
    conn = get_connection()
    if month:
        row = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM expenses WHERE year=? AND month=?",
            (year, month),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM expenses WHERE year=?", (year,)
        ).fetchone()
    conn.close()
    return row[0]


def sum_expenses_by_category(year: int, month: int = None) -> list[dict]:
    conn = get_connection()
    q = """
        SELECT c.name as category, COALESCE(SUM(e.amount),0) as total
        FROM expenses e
        LEFT JOIN categories c ON e.category_id = c.id
        WHERE e.year = ?
    """
    params = [year]
    if month:
        q += " AND e.month = ?"
        params.append(month)
    q += " GROUP BY c.name ORDER BY total DESC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# 売上（収入）
# ─────────────────────────────────────────────────────────────────────────────

def insert_revenue(
    name: str,
    amount: float,
    date: str,
    student_name: str = None,
    memo: str = None,
    notion_id: str = None,
    receipt_path: str = None,
    contact_id: str = None,
    job_id: str = None,
    category_id: str = None,
) -> str:
    dt = datetime.strptime(date[:10], "%Y-%m-%d")
    rev_id = str(uuid.uuid4())
    with transaction() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO revenue
               (id, name, amount, date, year, month, student_name, memo, notion_id, receipt_path, contact_id, job_id, category_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (rev_id, name, amount, date[:10], dt.year, dt.month,
             student_name, memo, notion_id, receipt_path, contact_id, job_id, category_id),
        )
    return rev_id


def get_revenue(year: int = None, month: int = None) -> list[dict]:
    conn = get_connection()
    if year and month:
        rows = conn.execute(
            "SELECT * FROM revenue WHERE year=? AND month=? ORDER BY date",
            (year, month),
        ).fetchall()
    elif year:
        rows = conn.execute(
            "SELECT * FROM revenue WHERE year=? ORDER BY date", (year,)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM revenue ORDER BY date").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def sum_revenue(year: int, month: int = None) -> float:
    conn = get_connection()
    if month:
        row = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM revenue WHERE year=? AND month=?",
            (year, month),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COALESCE(SUM(amount),0) FROM revenue WHERE year=?", (year,)
        ).fetchone()
    conn.close()
    return row[0]


# ─────────────────────────────────────────────────────────────────────────────
# 月次サマリー
# ─────────────────────────────────────────────────────────────────────────────

def monthly_summary(year: int) -> list[dict]:
    """年間の月次損益サマリーを返す。"""
    result = []
    for month in range(1, 13):
        inc = sum_revenue(year, month)
        exp = sum_expenses(year, month)
        result.append({
            "year": year,
            "month": month,
            "revenue": inc,
            "expenses": exp,
            "profit": inc - exp,
        })
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Web CRUD 拡張
# ─────────────────────────────────────────────────────────────────────────────

def get_expense_by_id(expense_id: str) -> dict:
    conn = get_connection()
    row = conn.execute(
        "SELECT e.*, c.name as category_name FROM expenses e "
        "LEFT JOIN categories c ON e.category_id = c.id "
        "WHERE e.id = ?", (expense_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_expense(expense_id, name, amount, date, category_id=None,
                   payment_method=None, payee=None, memo=None, is_recurring=False, receipt_path=None,
                   contact_id=None, job_id=None):
    dt = datetime.strptime(date[:10], "%Y-%m-%d")
    with transaction() as conn:
        conn.execute("""
            UPDATE expenses SET name=?, amount=?, date=?, year=?, month=?,
            category_id=?, payment_method=?, payee=?, memo=?, is_recurring=?, receipt_path=?,
            contact_id=?, job_id=?
            WHERE id=?
        """, (name, float(amount), date[:10], dt.year, dt.month,
              category_id, payment_method, payee, memo,
              1 if is_recurring else 0, receipt_path, contact_id, job_id, expense_id))


def delete_expense(expense_id: str):
    with transaction() as conn:
        conn.execute("DELETE FROM expenses WHERE id=?", (expense_id,))


def get_revenue_by_id(revenue_id: str) -> dict:
    conn = get_connection()
    row = conn.execute("SELECT * FROM revenue WHERE id=?", (revenue_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_revenue(revenue_id, name, amount, date, student_name=None, memo=None, receipt_path=None,
                   contact_id=None, job_id=None, category_id=None):
    dt = datetime.strptime(date[:10], "%Y-%m-%d")
    with transaction() as conn:
        conn.execute("""
            UPDATE revenue SET name=?, amount=?, date=?, year=?, month=?,
            student_name=?, memo=?, receipt_path=?, contact_id=?, job_id=?, category_id=? WHERE id=?
        """, (name, float(amount), date[:10], dt.year, dt.month,
              student_name, memo, receipt_path, contact_id, job_id, category_id, revenue_id))


def delete_revenue(revenue_id: str):
    with transaction() as conn:
        conn.execute("DELETE FROM revenue WHERE id=?", (revenue_id,))


def update_category(cat_id: str, name: str):
    with transaction() as conn:
        conn.execute("UPDATE categories SET name=? WHERE id=?", (name, cat_id))


def delete_category(cat_id: str):
    with transaction() as conn:
        conn.execute("DELETE FROM categories WHERE id=?", (cat_id,))


def get_category_by_id(cat_id: str) -> dict:
    conn = get_connection()
    row = conn.execute("SELECT * FROM categories WHERE id=?", (cat_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_categories_with_count() -> list[dict]:
    """カテゴリと各カテゴリの経費件数を返す。"""
    conn = get_connection()
    rows = conn.execute("""
        SELECT c.*, COUNT(e.id) as expense_count
        FROM categories c
        LEFT JOIN expenses e ON e.category_id = c.id
        GROUP BY c.id
        ORDER BY c.name
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_tatekae_expenses() -> list[dict]:
    """payment_method = '立替え' の未精算経費を返す（日付降順）。"""
    conn = get_connection()
    rows = conn.execute(
        "SELECT e.*, c.name as category_name FROM expenses e "
        "LEFT JOIN categories c ON e.category_id = c.id "
        "WHERE e.payment_method = ? ORDER BY e.date DESC",
        ("立替え",),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_recent_expenses(limit: int = 20) -> list[dict]:
    """直近の経費を返す（日付降順）。"""
    conn = get_connection()
    rows = conn.execute(
        "SELECT e.*, c.name as category_name FROM expenses e "
        "LEFT JOIN categories c ON e.category_id = c.id "
        "ORDER BY e.date DESC, e.created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def settle_expense(expense_id: str):
    """立替えを精算済み（TRANSFER）に変更する。"""
    with transaction() as conn:
        conn.execute(
            "UPDATE expenses SET payment_method = 'TRANSFER' WHERE id = ?",
            (expense_id,),
        )


def get_category_totals(year: int, month: int = None) -> list[dict]:
    """カテゴリ別支出合計（ドーナツチャート用）。"""
    conn = get_connection()
    q = ("SELECT COALESCE(c.name,'未分類') as category, SUM(e.amount) as total "
         "FROM expenses e LEFT JOIN categories c ON e.category_id = c.id WHERE e.year=?")
    params = [year]
    if month:
        q += " AND e.month=?"
        params.append(month)
    q += " GROUP BY COALESCE(c.name,'未分類') ORDER BY total DESC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_prev_month_totals(year: int, month: int) -> dict:
    """前月の収入・支出を返す。"""
    py, pm = (year - 1, 12) if month == 1 else (year, month - 1)
    return {"revenue": sum_revenue(py, pm), "expenses": sum_expenses(py, pm)}


def get_revenue_ranking(year: int, month: int = None, limit: int = 10) -> list[dict]:
    """生徒名別収入ランキング。"""
    conn = get_connection()
    q = ("SELECT COALESCE(NULLIF(student_name,''), name) as label, "
         "SUM(amount) as total, COUNT(*) as cnt FROM revenue WHERE year=?")
    params = [year]
    if month:
        q += " AND month=?"
        params.append(month)
    q += f" GROUP BY label ORDER BY total DESC LIMIT {limit}"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_recurring_summary(year: int, month: int = None) -> dict:
    """定期支出（is_recurring=1）の合計と一覧。"""
    conn = get_connection()
    q = ("SELECT e.*, c.name as category_name FROM expenses e "
         "LEFT JOIN categories c ON e.category_id = c.id WHERE e.is_recurring=1")
    params = []
    if year and month:
        q += " AND e.year=? AND e.month=?"
        params = [year, month]
    elif year:
        q += " AND e.year=?"
        params = [year]
    q += " ORDER BY e.date DESC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    items = [dict(r) for r in rows]
    return {"items": items, "total": sum(r["amount"] for r in items)}


def count_course_students(year: int, month: int, keyword: str) -> int:
    """指定キーワードを含む収入の人数（DISTINCT student_name）を返す。"""
    conn = get_connection()
    row = conn.execute(
        "SELECT COUNT(DISTINCT COALESCE(NULLIF(student_name,''), name)) "
        "FROM revenue WHERE year=? AND month=? AND name LIKE ?",
        (year, month, f"%{keyword}%"),
    ).fetchone()
    conn.close()
    return row[0] if row else 0


def get_financial_statement(year: int, end_date: str = None) -> dict:
    """決算書（P&L）データを返す。end_date='YYYY-MM-DD' で期間指定。"""
    conn = get_connection()
    if end_date:
        rev_rows = conn.execute(
            "SELECT name, SUM(amount) as total FROM revenue "
            "WHERE year=? AND date<=? GROUP BY name ORDER BY total DESC",
            (year, end_date),
        ).fetchall()
        exp_rows = conn.execute(
            "SELECT COALESCE(c.name,'未分類') as category, SUM(e.amount) as total "
            "FROM expenses e LEFT JOIN categories c ON e.category_id=c.id "
            "WHERE e.year=? AND e.date<=? GROUP BY category ORDER BY total DESC",
            (year, end_date),
        ).fetchall()
        from datetime import datetime as _dt
        end_m = _dt.strptime(end_date, "%Y-%m-%d").month
    else:
        rev_rows = conn.execute(
            "SELECT name, SUM(amount) as total FROM revenue "
            "WHERE year=? GROUP BY name ORDER BY total DESC", (year,),
        ).fetchall()
        exp_rows = conn.execute(
            "SELECT COALESCE(c.name,'未分類') as category, SUM(e.amount) as total "
            "FROM expenses e LEFT JOIN categories c ON e.category_id=c.id "
            "WHERE e.year=? GROUP BY category ORDER BY total DESC", (year,),
        ).fetchall()
        end_m = 12
    conn.close()

    rev_bd = [dict(r) for r in rev_rows]
    exp_bd = [dict(r) for r in exp_rows]
    total_rev = sum(r["total"] for r in rev_bd)
    total_exp = sum(r["total"] for r in exp_bd)

    monthly = []
    cum_rev = cum_exp = 0.0
    for m in range(1, end_m + 1):
        r = sum_revenue(year, m)
        e = sum_expenses(year, m)
        cum_rev += r
        cum_exp += e
        monthly.append({"month": m, "revenue": r, "expenses": e,
                         "profit": r - e, "cum_revenue": cum_rev,
                         "cum_expenses": cum_exp, "cum_profit": cum_rev - cum_exp})

    # 前年同期
    prev_total_rev = sum(sum_revenue(year - 1, m) for m in range(1, end_m + 1))
    prev_total_exp = sum(sum_expenses(year - 1, m) for m in range(1, end_m + 1))

    return {
        "year": year, "end_date": end_date, "end_month": end_m,
        "revenue_breakdown": rev_bd, "expense_breakdown": exp_bd,
        "total_revenue": total_rev, "total_expenses": total_exp,
        "net_profit": total_rev - total_exp, "monthly": monthly,
        "prev_total_revenue": prev_total_rev, "prev_total_expenses": prev_total_exp,
        "prev_net_profit": prev_total_rev - prev_total_exp,
    }


def get_budget_progress(year: int, month: int) -> list[dict]:
    """カテゴリ別 予算 vs 実績（progress bar用）。"""
    conn = get_connection()
    rows = conn.execute("""
        SELECT c.id, c.name,
            COALESCE(b.amount, 0) as budget,
            COALESCE(SUM(e.amount), 0) as actual
        FROM categories c
        LEFT JOIN budgets b ON b.category_id=c.id AND b.year=? AND b.month=?
        LEFT JOIN expenses e ON e.category_id=c.id AND e.year=? AND e.month=?
        GROUP BY c.id ORDER BY actual DESC
    """, (year, month, year, month)).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["pct"] = min(round(d["actual"] / d["budget"] * 100), 200) if d["budget"] > 0 else None
        d["over"] = d["actual"] > d["budget"] if d["budget"] > 0 else False
        result.append(d)
    return result


def get_budgets(year: int, month: int = 0) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT b.*, c.name as category_name FROM budgets b "
        "JOIN categories c ON b.category_id=c.id WHERE b.year=? AND b.month=? ORDER BY c.name",
        (year, month),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_budget(category_id: str, year: int, month: int, amount: float):
    with transaction() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO budgets (id, category_id, year, month, amount) "
            "VALUES (COALESCE((SELECT id FROM budgets WHERE category_id=? AND year=? AND month=?),?),?,?,?,?)",
            (category_id, year, month, str(uuid.uuid4()), category_id, year, month, amount),
        )


def search_expenses(q: str) -> list[dict]:
    """経費をキーワード検索する（名目・支払先・メモ・カテゴリ）。"""
    like = f"%{q}%"
    conn = get_connection()
    rows = conn.execute(
        "SELECT e.*, c.name as category_name FROM expenses e "
        "LEFT JOIN categories c ON e.category_id = c.id "
        "WHERE e.name LIKE ? OR e.payee LIKE ? OR e.memo LIKE ? OR c.name LIKE ? "
        "ORDER BY e.date DESC LIMIT 200",
        (like, like, like, like),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def search_revenue(q: str) -> list[dict]:
    """収入をキーワード検索する（名前・生徒名・メモ）。"""
    like = f"%{q}%"
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM revenue WHERE name LIKE ? OR student_name LIKE ? OR memo LIKE ? "
        "ORDER BY date DESC LIMIT 200",
        (like, like, like),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# タスク管理 (Tasks)
# ─────────────────────────────────────────────────────────────────────────────

def get_tasks(include_archived=False) -> list[dict]:
    conn = get_connection()
    q = "SELECT * FROM tasks"
    if not include_archived:
        q += " WHERE is_archived = 0"
    q += " ORDER BY status DESC, priority='high' DESC, priority='middle' DESC, created_at DESC"
    rows = conn.execute(q).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def insert_task(title, description=None, priority='middle', due_date=None):
    with transaction() as conn:
        id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO tasks (id, title, description, priority, due_date) VALUES (?,?,?,?,?)",
            (id, title, description, priority, due_date)
        )
    return id

def update_task(task_id, title, description, status, priority, due_date, is_archived=0):
    with transaction() as conn:
        conn.execute(
            "UPDATE tasks SET title=?, description=?, status=?, priority=?, due_date=?, is_archived=? WHERE id=?",
            (title, description, status, priority, due_date, is_archived, task_id)
        )

def delete_task(task_id):
    with transaction() as conn:
        conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))

# ─────────────────────────────────────────────────────────────────────────────
# 取引先・顧客管理 (Contacts)
# ─────────────────────────────────────────────────────────────────────────────

def get_contacts(contact_type=None) -> list[dict]:
    conn = get_connection()
    if contact_type:
        rows = conn.execute("SELECT * FROM contacts WHERE type=? ORDER BY name", (contact_type,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM contacts ORDER BY name").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def insert_contact(contact_type, name, contact_person=None, phone=None, email=None, address=None, bank_info=None, memo=None):
    with transaction() as conn:
        id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO contacts (id, type, name, contact_person, phone, email, address, bank_info, memo) VALUES (?,?,?,?,?,?,?,?,?)",
            (id, contact_type, name, contact_person, phone, email, address, bank_info, memo)
        )
    return id

def update_contact(contact_id, contact_type, name, contact_person, phone, email, address, bank_info, memo):
    with transaction() as conn:
        conn.execute(
            "UPDATE contacts SET type=?, name=?, contact_person=?, phone=?, email=?, address=?, bank_info=?, memo=? WHERE id=?",
            (contact_type, name, contact_person, phone, email, address, bank_info, memo, contact_id)
        )

def delete_contact(contact_id):
    with transaction() as conn:
        conn.execute("DELETE FROM contacts WHERE id=?", (contact_id,))

# ─────────────────────────────────────────────────────────────────────────────
# プロジェクト重要情報 (Project Info)
# ─────────────────────────────────────────────────────────────────────────────

def get_project_info() -> dict:
    conn = get_connection()
    row = conn.execute("SELECT * FROM project_info WHERE id='main'").fetchone()
    conn.close()
    if row:
        return dict(row)
    return {"bank_info": "", "facility_info": "", "emergency_info": ""}

def save_project_info(bank_info, facility_info, emergency_info):
    with transaction() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO project_info (id, bank_info, facility_info, emergency_info, updated_at) VALUES ('main', ?, ?, ?, datetime('now'))",
            (bank_info, facility_info, emergency_info)
        )

# ─────────────────────────────────────────────────────────────────────────────
# 案件利益管理 (Jobs)
# ─────────────────────────────────────────────────────────────────────────────

def get_jobs(status=None) -> list[dict]:
    conn = get_connection()
    if status:
        rows = conn.execute("SELECT * FROM jobs WHERE status=? ORDER BY created_at DESC", (status,)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM jobs ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_job_by_id(job_id) -> dict:
    conn = get_connection()
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def insert_job(name, start_date=None, status='active'):
    with transaction() as conn:
        id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO jobs (id, name, start_date, status) VALUES (?,?,?,?)",
            (id, name, start_date, status)
        )
    return id

def update_job(job_id, name, start_date, status):
    with transaction() as conn:
        conn.execute(
            "UPDATE jobs SET name=?, start_date=?, status=? WHERE id=?",
            (name, start_date, status, job_id)
        )

def delete_job(job_id):
    with transaction() as conn:
        conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))

# ─────────────────────────────────────────────────────────────────────────────
# プロジェクト管理 (Projects)
# ─────────────────────────────────────────────────────────────────────────────

def get_all_projects(include_archived: bool = False) -> list[dict]:
    conn = get_connection()
    if include_archived:
        rows = conn.execute(
            "SELECT * FROM projects ORDER BY sort_order ASC, created_at ASC"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM projects WHERE status='active' "
            "ORDER BY sort_order ASC, created_at ASC"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_project_by_id(project_id: int) -> dict:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM projects WHERE id=?", (project_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def insert_project(name: str, emoji: str = "", color: str = "#16213e",
                   description: str = "", sort_order: int = 0,
                   start_date: str = "", client_name: str = "",
                   manager_name: str = "", is_group: int = 0) -> int:
    with transaction() as conn:
        cur = conn.execute(
            "INSERT INTO projects (name, emoji, color, description, sort_order, "
            "start_date, client_name, manager_name, is_group) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, emoji, color, description, sort_order,
             start_date or None, client_name or None, manager_name or None,
             is_group),
        )
        return cur.lastrowid


def update_project(project_id: int, name: str, emoji: str, color: str,
                   description: str, status: str = "active",
                   sort_order: int = 0, start_date: str = "",
                   client_name: str = "", manager_name: str = "",
                   is_group: int = 0):
    with transaction() as conn:
        conn.execute(
            "UPDATE projects SET name=?, emoji=?, color=?, description=?, "
            "status=?, sort_order=?, start_date=?, client_name=?, manager_name=?, "
            "is_group=?, updated_at=datetime('now') WHERE id=?",
            (name, emoji, color, description, status, sort_order,
             start_date or None, client_name or None, manager_name or None,
             is_group, project_id),
        )


def delete_project(project_id: int):
    with transaction() as conn:
        conn.execute("DELETE FROM projects WHERE id=?", (project_id,))


# ─────────────────────────────────────────────────────────────────────────────
# プロジェクト・タスク (Phase 2)
#   status: pending(未着手) / in_progress(進行中) / done(完了) / on_hold(保留) / rejected(却下)
#   priority: low / middle / high
# ─────────────────────────────────────────────────────────────────────────────

TASK_STATUSES = [
    ("pending",     "未着手", "#6c757d"),
    ("in_progress", "進行中", "#0d6efd"),
    ("done",        "完了",   "#2d6a4f"),
    ("on_hold",     "保留",   "#fd7e14"),
    ("rejected",    "却下",   "#c1121f"),
]

TASK_PRIORITIES = [
    ("high",   "高", "#c1121f"),
    ("middle", "中", "#0d6efd"),
    ("low",    "低", "#6c757d"),
]


def get_tasks_by_project(project_id: int, include_archived: bool = False) -> list[dict]:
    conn = get_connection()
    q = "SELECT * FROM tasks WHERE project_id=?"
    if not include_archived:
        q += " AND COALESCE(is_archived,0) = 0"
    q += " ORDER BY sort_order ASC, created_at DESC"
    rows = conn.execute(q, (project_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_task_by_id(task_id: str) -> dict:
    conn = get_connection()
    row = conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def insert_project_task(project_id: int, title: str, description: str = "",
                        status: str = "pending", priority: str = "middle",
                        due_date: str = None, assignee: str = "",
                        sort_order: int = 0) -> str:
    task_id = str(uuid.uuid4())
    with transaction() as conn:
        conn.execute(
            "INSERT INTO tasks (id, project_id, title, description, status, "
            "priority, due_date, assignee, sort_order, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?, datetime('now'))",
            (task_id, project_id, title, description, status,
             priority, due_date, assignee, sort_order),
        )
    return task_id


def update_project_task(task_id: str, title: str, description: str,
                        status: str, priority: str, due_date: str = None,
                        assignee: str = "", sort_order: int = 0,
                        is_archived: int = 0):
    with transaction() as conn:
        conn.execute(
            "UPDATE tasks SET title=?, description=?, status=?, priority=?, "
            "due_date=?, assignee=?, sort_order=?, is_archived=?, "
            "updated_at=datetime('now') WHERE id=?",
            (title, description, status, priority, due_date, assignee,
             sort_order, is_archived, task_id),
        )


def update_task_status(task_id: str, status: str):
    with transaction() as conn:
        conn.execute(
            "UPDATE tasks SET status=?, updated_at=datetime('now') WHERE id=?",
            (status, task_id),
        )


# ─────────────────────────────────────────────────────────────────────────────
# プロジェクト重要情報 (Phase 3)
# ─────────────────────────────────────────────────────────────────────────────

INFO_CATEGORIES = [
    ("address",   "🏠 住所",        ["line1", "line2", "city", "postal", "country", "notes"]),
    ("wifi",      "📶 Wi-Fi",       ["ssid", "password", "location", "notes"]),
    ("bank",      "🏦 銀行口座",     ["bank_name", "branch", "account_no", "holder", "swift", "notes"]),
    ("utility",   "💡 公共料金",     ["provider", "service", "account_no", "amount", "notes"]),
    ("emergency", "🚨 緊急連絡先",   ["name", "role", "phone", "email", "notes"]),
    ("contract",  "📄 契約書",       ["title", "party", "start_date", "end_date", "notes"]),
    ("url",       "🔗 関連URL",      ["title", "url", "description", "notes"]),
    ("other",     "📝 その他",       ["label", "value", "notes"]),
]

INFO_FIELD_LABELS = {
    "line1":      "住所1",
    "line2":      "住所2",
    "city":       "市区町村",
    "postal":     "郵便番号",
    "country":    "国",
    "ssid":       "SSID",
    "password":   "パスワード",
    "location":   "設置場所",
    "bank_name":  "銀行名",
    "branch":     "支店",
    "account_no": "口座番号",
    "holder":     "口座名義",
    "swift":      "SWIFT/BIC",
    "provider":   "事業者",
    "service":    "サービス種別",
    "amount":     "月額目安",
    "name":       "氏名",
    "role":       "役割/関係",
    "phone":      "電話/WhatsApp",
    "email":      "メール",
    "title":      "タイトル/名前",
    "party":      "契約相手",
    "start_date": "開始日",
    "end_date":   "終了日",
    "url":        "URL",
    "description":"説明/概要",
    "label":      "項目名",
    "value":      "内容",
    "notes":      "メモ",
}


def get_project_info_items(project_id: int, category: str = None) -> list[dict]:
    conn = get_connection()
    if category:
        rows = conn.execute(
            "SELECT * FROM project_info_items WHERE project_id=? AND category=? "
            "ORDER BY sort_order ASC, created_at ASC",
            (project_id, category),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM project_info_items WHERE project_id=? "
            "ORDER BY category, sort_order ASC, created_at ASC",
            (project_id,),
        ).fetchall()
    conn.close()
    import json
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["fields"] = json.loads(d.get("fields_json") or "{}")
        except Exception:
            d["fields"] = {}
        out.append(d)
    return out


def get_project_info_item(item_id: str) -> dict:
    conn = get_connection()
    row = conn.execute("SELECT * FROM project_info_items WHERE id=?", (item_id,)).fetchone()
    conn.close()
    if not row:
        return None
    import json
    d = dict(row)
    try:
        d["fields"] = json.loads(d.get("fields_json") or "{}")
    except Exception:
        d["fields"] = {}
    return d


def insert_project_info_item(project_id: int, category: str, label: str,
                             fields: dict, sort_order: int = 0) -> str:
    import json
    item_id = str(uuid.uuid4())
    with transaction() as conn:
        conn.execute(
            "INSERT INTO project_info_items (id, project_id, category, label, "
            "fields_json, sort_order, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, datetime('now'))",
            (item_id, project_id, category, label,
             json.dumps(fields, ensure_ascii=False), sort_order),
        )
    return item_id


def update_project_info_item(item_id: str, label: str, fields: dict,
                             sort_order: int = 0):
    import json
    with transaction() as conn:
        conn.execute(
            "UPDATE project_info_items SET label=?, fields_json=?, sort_order=?, "
            "updated_at=datetime('now') WHERE id=?",
            (label, json.dumps(fields, ensure_ascii=False), sort_order, item_id),
        )


def delete_project_info_item(item_id: str):
    with transaction() as conn:
        # 関連添付も削除
        conn.execute("DELETE FROM project_attachments WHERE info_item_id=?", (item_id,))
        conn.execute("DELETE FROM project_info_items WHERE id=?", (item_id,))


def get_project_attachments(project_id: int, info_item_id: str = None,
                            category: str = None) -> list[dict]:
    conn = get_connection()
    q = "SELECT * FROM project_attachments WHERE project_id=?"
    params = [project_id]
    if info_item_id:
        q += " AND info_item_id=?"
        params.append(info_item_id)
    if category:
        q += " AND category=?"
        params.append(category)
    q += " ORDER BY uploaded_at DESC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def insert_project_attachment(project_id: int, filename: str,
                              drive_file_id: str = "", drive_url: str = "",
                              mime_type: str = "", size_bytes: int = 0,
                              notes: str = "", info_item_id: str = None,
                              category: str = "other") -> str:
    att_id = str(uuid.uuid4())
    with transaction() as conn:
        conn.execute(
            "INSERT INTO project_attachments (id, project_id, info_item_id, "
            "category, filename, drive_file_id, drive_url, mime_type, "
            "size_bytes, notes) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (att_id, project_id, info_item_id, category, filename,
             drive_file_id, drive_url, mime_type, size_bytes, notes),
        )
    return att_id


def get_project_attachment(att_id: str) -> dict:
    conn = get_connection()
    row = conn.execute("SELECT * FROM project_attachments WHERE id=?", (att_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_project_attachment(att_id: str):
    with transaction() as conn:
        conn.execute("DELETE FROM project_attachments WHERE id=?", (att_id,))


# ─────────────────────────────────────────────────────────────────────────────
# プロジェクトスタッフ (Phase 4)
# ─────────────────────────────────────────────────────────────────────────────

STAFF_EMPLOYMENT_TYPES = [
    ("seishain",  "正社員"),
    ("keiyaku",   "契約社員"),
    ("part",      "パート/アルバイト"),
    ("intern",    "インターン"),
    ("itaku",     "業務委託"),
    ("other",     "その他"),
]

STAFF_STATUSES = [
    ("active",   "🟢 在職中", "#2d6a4f"),
    ("leave",    "🟡 休職中", "#c9982e"),
    ("inactive", "⚫ 退職",   "#777777"),
]

STAFF_FIELD_LABELS = {
    "name":              "氏名",
    "name_kana":         "フリガナ / ローマ字",
    "position":          "役職 / 職種",
    "employment_type":   "雇用形態",
    "status":            "ステータス",
    "whatsapp":          "WhatsApp",
    "email":             "メール",
    "phone":             "電話",
    "address":           "住所",
    "birthday":          "生年月日",
    "hire_date":         "入社日",
    "termination_date":  "退社日",
    "working_hours":     "勤務時間",
    "salary":            "給与",
    "bank_info":         "振込先",
    "emergency_contact": "緊急連絡先",
    "memo":              "メモ",
}


def get_staff_by_project(project_id: int, include_inactive: bool = True) -> list[dict]:
    conn = get_connection()
    if include_inactive:
        rows = conn.execute(
            "SELECT * FROM project_staff WHERE project_id=? "
            "ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'leave' THEN 1 ELSE 2 END, "
            "sort_order ASC, created_at ASC",
            (project_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM project_staff WHERE project_id=? AND status='active' "
            "ORDER BY sort_order ASC, created_at ASC",
            (project_id,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_staff_by_id(staff_id: str) -> dict:
    conn = get_connection()
    row = conn.execute("SELECT * FROM project_staff WHERE id=?", (staff_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def insert_staff(project_id: int, name: str, **kwargs) -> str:
    staff_id = str(uuid.uuid4())
    cols = ["id", "project_id", "name"]
    vals = [staff_id, project_id, name]
    for k in (
        "name_kana", "position", "employment_type", "status",
        "whatsapp", "email", "phone", "address",
        "birthday", "hire_date", "termination_date",
        "working_hours", "salary", "bank_info",
        "emergency_contact", "photo_url", "memo", "sort_order",
    ):
        if k in kwargs and kwargs[k] is not None:
            cols.append(k)
            vals.append(kwargs[k])
    placeholders = ",".join(["?"] * len(vals))
    sql = f"INSERT INTO project_staff ({','.join(cols)}) VALUES ({placeholders})"
    with transaction() as conn:
        conn.execute(sql, vals)
    return staff_id


def update_staff(staff_id: str, **kwargs):
    allowed = {
        "name", "name_kana", "position", "employment_type", "status",
        "whatsapp", "email", "phone", "address",
        "birthday", "hire_date", "termination_date",
        "working_hours", "salary", "bank_info",
        "emergency_contact", "photo_url", "memo", "sort_order",
    }
    sets = []
    vals = []
    for k, v in kwargs.items():
        if k in allowed:
            sets.append(f"{k}=?")
            vals.append(v)
    if not sets:
        return
    sets.append("updated_at=datetime('now')")
    vals.append(staff_id)
    sql = f"UPDATE project_staff SET {', '.join(sets)} WHERE id=?"
    with transaction() as conn:
        conn.execute(sql, vals)


def delete_staff(staff_id: str):
    with transaction() as conn:
        # 関連添付（写真など）も削除
        conn.execute("DELETE FROM project_attachments WHERE staff_id=?", (staff_id,))
        conn.execute("DELETE FROM project_staff WHERE id=?", (staff_id,))


def count_staff_by_status(project_id: int) -> dict:
    conn = get_connection()
    rows = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM project_staff "
        "WHERE project_id=? GROUP BY status",
        (project_id,),
    ).fetchall()
    conn.close()
    return {r["status"]: r["cnt"] for r in rows}


def count_tasks_by_status(project_id: int) -> dict:
    conn = get_connection()
    rows = conn.execute(
        "SELECT status, COUNT(*) as cnt FROM tasks "
        "WHERE project_id=? AND COALESCE(is_archived,0)=0 GROUP BY status",
        (project_id,),
    ).fetchall()
    conn.close()
    return {r["status"]: r["cnt"] for r in rows}


def get_job_summary(job_id) -> dict:
    """案件ごへの支出・収入・粗利を集計する。"""
    conn = get_connection()
    # 支出
    exp_sum = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM expenses WHERE job_id=?", (job_id,)).fetchone()[0]
    # 収入
    rev_sum = conn.execute("SELECT COALESCE(SUM(amount), 0) FROM revenue WHERE job_id=?", (job_id,)).fetchone()[0]
    
    # 支出内訳
    exp_details = conn.execute(
        "SELECT e.*, c.name as category_name, co.name as vendor_name FROM expenses e "
        "LEFT JOIN categories c ON e.category_id = c.id "
        "LEFT JOIN contacts co ON e.contact_id = co.id "
        "WHERE e.job_id=? ORDER BY e.date", (job_id,)
    ).fetchall()
    
    # 収入内訳
    rev_details = conn.execute(
        "SELECT r.*, c.name as category_name, co.name as customer_name FROM revenue r "
        "LEFT JOIN categories c ON r.category_id = c.id "
        "LEFT JOIN contacts co ON r.contact_id = co.id "
        "WHERE r.job_id=? ORDER BY r.date", (job_id,)
    ).fetchall()
    
    conn.close()
    return {
        "expenses_total": exp_sum,
        "revenue_total": rev_sum,
        "profit": rev_sum - exp_sum,
        "expenses": [dict(r) for r in exp_details],
        "revenue": [dict(r) for r in rev_details]
    }
