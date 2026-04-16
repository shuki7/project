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
    pass  # DB initialized


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
