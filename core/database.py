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


def _ensure_dirs():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def get_connection() -> sqlite3.Connection:
    _ensure_dirs()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")  # 複数プロセスからの読み書きに対応
    return conn


@contextmanager
def transaction():
    conn = get_connection()
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
    notion_id       TEXT UNIQUE,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_expenses_year_month ON expenses(year, month);
CREATE INDEX IF NOT EXISTS idx_revenue_year_month  ON revenue(year, month);
CREATE INDEX IF NOT EXISTS idx_expenses_date       ON expenses(date);
CREATE INDEX IF NOT EXISTS idx_revenue_date        ON revenue(date);
"""


def init_db():
    """データベースとテーブルを初期化する。"""
    with transaction() as conn:
        conn.executescript(SCHEMA_SQL)
    print(f"[DB] initialized: {DB_PATH}")


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
) -> str:
    dt = datetime.strptime(date[:10], "%Y-%m-%d")
    exp_id = str(uuid.uuid4())
    with transaction() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO expenses
               (id, name, amount, date, year, month, category_id,
                payment_method, payee, memo, is_recurring, receipt_path, notion_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (exp_id, name, amount, date[:10], dt.year, dt.month,
             category_id, payment_method, payee, memo,
             1 if is_recurring else 0, receipt_path, notion_id),
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
) -> str:
    dt = datetime.strptime(date[:10], "%Y-%m-%d")
    rev_id = str(uuid.uuid4())
    with transaction() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO revenue
               (id, name, amount, date, year, month, student_name, memo, notion_id)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (rev_id, name, amount, date[:10], dt.year, dt.month,
             student_name, memo, notion_id),
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
                   payment_method=None, payee=None, memo=None, is_recurring=False, receipt_path=None):
    dt = datetime.strptime(date[:10], "%Y-%m-%d")
    with transaction() as conn:
        conn.execute("""
            UPDATE expenses SET name=?, amount=?, date=?, year=?, month=?,
            category_id=?, payment_method=?, payee=?, memo=?, is_recurring=?, receipt_path=?
            WHERE id=?
        """, (name, float(amount), date[:10], dt.year, dt.month,
              category_id, payment_method, payee, memo,
              1 if is_recurring else 0, receipt_path, expense_id))


def delete_expense(expense_id: str):
    with transaction() as conn:
        conn.execute("DELETE FROM expenses WHERE id=?", (expense_id,))


def get_revenue_by_id(revenue_id: str) -> dict:
    conn = get_connection()
    row = conn.execute("SELECT * FROM revenue WHERE id=?", (revenue_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_revenue(revenue_id, name, amount, date, student_name=None, memo=None):
    dt = datetime.strptime(date[:10], "%Y-%m-%d")
    with transaction() as conn:
        conn.execute("""
            UPDATE revenue SET name=?, amount=?, date=?, year=?, month=?,
            student_name=?, memo=? WHERE id=?
        """, (name, float(amount), date[:10], dt.year, dt.month,
              student_name, memo, revenue_id))


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
