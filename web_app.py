"""
Flask Blueprint — 家計簿 Web CRUD インターフェース
"""

import os
import uuid
from datetime import datetime
from pathlib import Path

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, send_from_directory, abort,
)
from werkzeug.utils import secure_filename

from config import RECEIPTS_DIR, fmt_idr, COMPANY_NAME
from core.database import (
    # カテゴリ
    get_all_categories, get_category_by_id, upsert_category,
    update_category, delete_category, get_categories_with_count,
    # 経費
    get_expenses, get_expense_by_id, insert_expense,
    update_expense, delete_expense,
    # 収入
    get_revenue, get_revenue_by_id, insert_revenue,
    update_revenue, delete_revenue,
    # サマリー
    monthly_summary, sum_expenses, sum_revenue,
)

web = Blueprint("web", __name__, url_prefix="")

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}
PAYMENT_METHODS = ["CASH", "TRANSFER", "DEBIT", "立替え"]


def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _save_receipt(file):
    """アップロードされたファイルを保存してファイル名を返す。"""
    if not file or file.filename == "":
        return None
    if not _allowed_file(file.filename):
        return None
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    ext = file.filename.rsplit(".", 1)[1].lower()
    filename = f"{uuid.uuid4()}.{ext}"
    file.save(RECEIPTS_DIR / filename)
    return filename


def _sort_clause(sort: str, order: str, allowed: dict) -> str:
    """ソート句を安全に構築する。"""
    col = allowed.get(sort, allowed.get("date", "e.date"))
    direction = "ASC" if order.upper() == "ASC" else "DESC"
    return f"{col} {direction}"


# ─────────────────────────────────────────────────────────────────────────────
# コンテキストプロセッサ
# ─────────────────────────────────────────────────────────────────────────────

@web.context_processor
def inject_globals():
    return {
        "fmt_idr": fmt_idr,
        "company_name": COMPANY_NAME,
        "current_year": datetime.now().year,
        "current_month": datetime.now().month,
    }


# ─────────────────────────────────────────────────────────────────────────────
# ダッシュボード
# ─────────────────────────────────────────────────────────────────────────────

@web.route("/")
def dashboard():
    now = datetime.now()
    year = int(request.args.get("year", now.year))
    month = now.month

    monthly_rev = sum_revenue(year, month)
    monthly_exp = sum_expenses(year, month)
    monthly_profit = monthly_rev - monthly_exp

    annual_rev = sum_revenue(year)
    annual_exp = sum_expenses(year)
    annual_profit = annual_rev - annual_exp

    summary = monthly_summary(year)

    return render_template(
        "dashboard.html",
        year=year,
        month=month,
        monthly_rev=monthly_rev,
        monthly_exp=monthly_exp,
        monthly_profit=monthly_profit,
        annual_rev=annual_rev,
        annual_exp=annual_exp,
        annual_profit=annual_profit,
        summary=summary,
        page="dashboard",
    )


# ─────────────────────────────────────────────────────────────────────────────
# 経費
# ─────────────────────────────────────────────────────────────────────────────

EXPENSE_SORT_COLS = {
    "date": "e.date",
    "name": "e.name",
    "amount": "e.amount",
    "category": "c.name",
    "payment": "e.payment_method",
    "payee": "e.payee",
}


@web.route("/expenses")
def expenses_list():
    now = datetime.now()
    year = int(request.args.get("year", now.year))
    month_raw = request.args.get("month", str(now.month))
    month = int(month_raw) if month_raw.isdigit() and month_raw != "0" else None

    sort = request.args.get("sort", "date")
    order = request.args.get("order", "desc")

    # ソートを適用した経費一覧を取得
    from config import DB_PATH
    import sqlite3

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    col = EXPENSE_SORT_COLS.get(sort, "e.date")
    direction = "ASC" if order.upper() == "ASC" else "DESC"

    if month:
        rows = conn.execute(
            f"SELECT e.*, c.name as category_name FROM expenses e "
            f"LEFT JOIN categories c ON e.category_id = c.id "
            f"WHERE e.year=? AND e.month=? ORDER BY {col} {direction}",
            (year, month),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT e.*, c.name as category_name FROM expenses e "
            f"LEFT JOIN categories c ON e.category_id = c.id "
            f"WHERE e.year=? ORDER BY {col} {direction}",
            (year,),
        ).fetchall()
    conn.close()

    expenses = [dict(r) for r in rows]
    total = sum(e["amount"] for e in expenses)

    return render_template(
        "expenses/list.html",
        expenses=expenses,
        total=total,
        year=year,
        month=month,
        sort=sort,
        order=order,
        page="expenses",
    )


@web.route("/expenses/new", methods=["GET", "POST"])
def expenses_new():
    categories = get_all_categories()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        amount = request.form.get("amount", "0").strip()
        date = request.form.get("date", "").strip()
        category_id = request.form.get("category_id") or None
        payment_method = request.form.get("payment_method") or None
        payee = request.form.get("payee", "").strip() or None
        memo = request.form.get("memo", "").strip() or None
        is_recurring = bool(request.form.get("is_recurring"))
        receipt_file = request.files.get("receipt")

        if not name or not amount or not date:
            flash("日付・名目・金額は必須です。", "error")
            return render_template(
                "expenses/form.html",
                categories=categories,
                payment_methods=PAYMENT_METHODS,
                expense=request.form,
                title="経費を追加",
                page="expenses",
            )

        try:
            receipt_path = _save_receipt(receipt_file)
            insert_expense(
                name=name,
                amount=float(amount),
                date=date,
                category_id=category_id,
                payment_method=payment_method,
                payee=payee,
                memo=memo,
                is_recurring=is_recurring,
                receipt_path=receipt_path,
            )
            flash("経費を追加しました。", "success")
            return redirect(url_for("web.expenses_list"))
        except Exception as e:
            flash(f"エラーが発生しました: {e}", "error")

    today = datetime.now().strftime("%Y-%m-%d")
    return render_template(
        "expenses/form.html",
        categories=categories,
        payment_methods=PAYMENT_METHODS,
        expense={"date": today},
        title="経費を追加",
        page="expenses",
    )


@web.route("/expenses/<expense_id>/edit", methods=["GET", "POST"])
def expenses_edit(expense_id):
    expense = get_expense_by_id(expense_id)
    if not expense:
        abort(404)
    categories = get_all_categories()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        amount = request.form.get("amount", "0").strip()
        date = request.form.get("date", "").strip()
        category_id = request.form.get("category_id") or None
        payment_method = request.form.get("payment_method") or None
        payee = request.form.get("payee", "").strip() or None
        memo = request.form.get("memo", "").strip() or None
        is_recurring = bool(request.form.get("is_recurring"))
        receipt_file = request.files.get("receipt")

        if not name or not amount or not date:
            flash("日付・名目・金額は必須です。", "error")
            return render_template(
                "expenses/form.html",
                categories=categories,
                payment_methods=PAYMENT_METHODS,
                expense=expense,
                title="経費を編集",
                page="expenses",
            )

        try:
            # 新しいレシートがアップロードされた場合のみ更新
            new_receipt = _save_receipt(receipt_file)
            receipt_path = new_receipt if new_receipt else expense.get("receipt_path")

            update_expense(
                expense_id=expense_id,
                name=name,
                amount=float(amount),
                date=date,
                category_id=category_id,
                payment_method=payment_method,
                payee=payee,
                memo=memo,
                is_recurring=is_recurring,
                receipt_path=receipt_path,
            )
            flash("経費を更新しました。", "success")
            return redirect(url_for("web.expenses_list"))
        except Exception as e:
            flash(f"エラーが発生しました: {e}", "error")

    return render_template(
        "expenses/form.html",
        categories=categories,
        payment_methods=PAYMENT_METHODS,
        expense=expense,
        title="経費を編集",
        page="expenses",
    )


@web.route("/expenses/<expense_id>/delete", methods=["POST"])
def expenses_delete(expense_id):
    expense = get_expense_by_id(expense_id)
    if not expense:
        abort(404)
    try:
        delete_expense(expense_id)
        flash("経費を削除しました。", "success")
    except Exception as e:
        flash(f"削除エラー: {e}", "error")
    return redirect(url_for("web.expenses_list"))


# ─────────────────────────────────────────────────────────────────────────────
# 収入
# ─────────────────────────────────────────────────────────────────────────────

REVENUE_SORT_COLS = {
    "date": "date",
    "name": "name",
    "amount": "amount",
    "student_name": "student_name",
    "memo": "memo",
}


@web.route("/revenue")
def revenue_list():
    now = datetime.now()
    year = int(request.args.get("year", now.year))
    month_raw = request.args.get("month", str(now.month))
    month = int(month_raw) if month_raw.isdigit() and month_raw != "0" else None

    sort = request.args.get("sort", "date")
    order = request.args.get("order", "desc")

    from config import DB_PATH
    import sqlite3

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    col = REVENUE_SORT_COLS.get(sort, "date")
    direction = "ASC" if order.upper() == "ASC" else "DESC"

    if month:
        rows = conn.execute(
            f"SELECT * FROM revenue WHERE year=? AND month=? ORDER BY {col} {direction}",
            (year, month),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT * FROM revenue WHERE year=? ORDER BY {col} {direction}",
            (year,),
        ).fetchall()
    conn.close()

    revenues = [dict(r) for r in rows]
    total = sum(r["amount"] for r in revenues)

    return render_template(
        "revenue/list.html",
        revenues=revenues,
        total=total,
        year=year,
        month=month,
        sort=sort,
        order=order,
        page="revenue",
    )


@web.route("/revenue/new", methods=["GET", "POST"])
def revenue_new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        amount = request.form.get("amount", "0").strip()
        date = request.form.get("date", "").strip()
        student_name = request.form.get("student_name", "").strip() or None
        memo = request.form.get("memo", "").strip() or None

        if not name or not amount or not date:
            flash("日付・名前・金額は必須です。", "error")
            return render_template(
                "revenue/form.html",
                revenue=request.form,
                title="収入を追加",
                page="revenue",
            )

        try:
            insert_revenue(
                name=name,
                amount=float(amount),
                date=date,
                student_name=student_name,
                memo=memo,
            )
            flash("収入を追加しました。", "success")
            return redirect(url_for("web.revenue_list"))
        except Exception as e:
            flash(f"エラーが発生しました: {e}", "error")

    today = datetime.now().strftime("%Y-%m-%d")
    return render_template(
        "revenue/form.html",
        revenue={"date": today},
        title="収入を追加",
        page="revenue",
    )


@web.route("/revenue/<revenue_id>/edit", methods=["GET", "POST"])
def revenue_edit(revenue_id):
    revenue = get_revenue_by_id(revenue_id)
    if not revenue:
        abort(404)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        amount = request.form.get("amount", "0").strip()
        date = request.form.get("date", "").strip()
        student_name = request.form.get("student_name", "").strip() or None
        memo = request.form.get("memo", "").strip() or None

        if not name or not amount or not date:
            flash("日付・名前・金額は必須です。", "error")
            return render_template(
                "revenue/form.html",
                revenue=revenue,
                title="収入を編集",
                page="revenue",
            )

        try:
            update_revenue(
                revenue_id=revenue_id,
                name=name,
                amount=float(amount),
                date=date,
                student_name=student_name,
                memo=memo,
            )
            flash("収入を更新しました。", "success")
            return redirect(url_for("web.revenue_list"))
        except Exception as e:
            flash(f"エラーが発生しました: {e}", "error")

    return render_template(
        "revenue/form.html",
        revenue=revenue,
        title="収入を編集",
        page="revenue",
    )


@web.route("/revenue/<revenue_id>/delete", methods=["POST"])
def revenue_delete(revenue_id):
    revenue = get_revenue_by_id(revenue_id)
    if not revenue:
        abort(404)
    try:
        delete_revenue(revenue_id)
        flash("収入を削除しました。", "success")
    except Exception as e:
        flash(f"削除エラー: {e}", "error")
    return redirect(url_for("web.revenue_list"))


# ─────────────────────────────────────────────────────────────────────────────
# 勘定科目（カテゴリ）
# ─────────────────────────────────────────────────────────────────────────────

@web.route("/categories")
def categories_list():
    categories = get_categories_with_count()
    return render_template(
        "categories/list.html",
        categories=categories,
        page="categories",
    )


@web.route("/categories/new", methods=["GET", "POST"])
def categories_new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("カテゴリ名は必須です。", "error")
            return render_template(
                "categories/form.html",
                category={},
                title="勘定科目を追加",
                page="categories",
            )
        try:
            upsert_category(name)
            flash("勘定科目を追加しました。", "success")
            return redirect(url_for("web.categories_list"))
        except Exception as e:
            flash(f"エラーが発生しました: {e}", "error")

    return render_template(
        "categories/form.html",
        category={},
        title="勘定科目を追加",
        page="categories",
    )


@web.route("/categories/<cat_id>/edit", methods=["GET", "POST"])
def categories_edit(cat_id):
    category = get_category_by_id(cat_id)
    if not category:
        abort(404)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("カテゴリ名は必須です。", "error")
            return render_template(
                "categories/form.html",
                category=category,
                title="勘定科目を編集",
                page="categories",
            )
        try:
            update_category(cat_id, name)
            flash("勘定科目を更新しました。", "success")
            return redirect(url_for("web.categories_list"))
        except Exception as e:
            flash(f"エラーが発生しました: {e}", "error")

    return render_template(
        "categories/form.html",
        category=category,
        title="勘定科目を編集",
        page="categories",
    )


@web.route("/categories/<cat_id>/delete", methods=["POST"])
def categories_delete(cat_id):
    category = get_category_by_id(cat_id)
    if not category:
        abort(404)
    try:
        delete_category(cat_id)
        flash("勘定科目を削除しました。", "success")
    except Exception as e:
        flash(f"削除エラー: {e}", "error")
    return redirect(url_for("web.categories_list"))


# ─────────────────────────────────────────────────────────────────────────────
# レシート配信
# ─────────────────────────────────────────────────────────────────────────────

@web.route("/receipts/<path:filename>")
def serve_receipt(filename):
    filepath = RECEIPTS_DIR / filename
    if not filepath.exists():
        abort(404)
    return send_from_directory(str(RECEIPTS_DIR), filename)
