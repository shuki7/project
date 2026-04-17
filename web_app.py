"""
Flask Blueprint — 家計簿 Web CRUD インターフェース
"""

import csv
import io
import json
import os
import uuid
from datetime import datetime
from pathlib import Path

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, send_from_directory, abort,
    session, Response, make_response,
)
from werkzeug.utils import secure_filename

from config import (
    RECEIPTS_DIR, fmt_idr, COMPANY_NAME,
    LOGIN_EMAIL, LOGIN_PASSWORD, LOGIN_RESET_TOKEN,
    COURSE_KEYWORDS, REPORTS_DIR,
)
from bot.ocr import parse_receipt_from_bytes, classify_category, compress_image
from sync.gdrive import upload_receipt_bytes
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
    # 立替え・検索・直近
    get_tatekae_expenses, settle_expense,
    search_expenses, search_revenue,
    get_recent_expenses,
    # 新機能
    get_category_totals, get_prev_month_totals,
    get_revenue_ranking, get_recurring_summary,
    count_course_students, get_financial_statement,
    get_budget_progress, get_budgets, set_budget,
)

web = Blueprint("web", __name__, url_prefix="/keiri")


# ─────────────────────────────────────────────────────────────────────────────
# 認証
# ─────────────────────────────────────────────────────────────────────────────

@web.before_request
def check_auth():
    open_endpoints = {"web.login", "web.logout", "web.recover"}
    if request.endpoint in open_endpoints:
        return
    if not session.get("logged_in"):
        return redirect(url_for("web.login", next=request.path))


@web.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        email_ok = (not LOGIN_EMAIL) or (email == LOGIN_EMAIL)
        pass_ok  = (password == LOGIN_PASSWORD)
        if email_ok and pass_ok:
            session["logged_in"] = True
            session["user_email"] = email
            session.permanent = True
            return redirect(request.args.get("next") or url_for("web.dashboard"))
        flash("メールアドレスまたはパスワードが違います。", "error")
    return render_template("login.html", require_email=bool(LOGIN_EMAIL))


@web.route("/logout")
def logout():
    session.clear()
    flash("ログアウトしました。", "success")
    return redirect(url_for("web.login"))


@web.route("/recover")
def recover():
    """リカバリートークンURLでパスワードなしでログインする。"""
    token = request.args.get("token", "")
    if not token or not LOGIN_RESET_TOKEN or token != LOGIN_RESET_TOKEN:
        flash("リカバリートークンが無効です。", "error")
        return redirect(url_for("web.login"))
    session["logged_in"] = True
    session.permanent = True
    flash("リカバリートークンでログインしました。パスワードを確認してください。", "success")
    return redirect(url_for("web.dashboard"))

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
    tatekae_list = get_tatekae_expenses()
    tatekae_total = sum(e["amount"] for e in tatekae_list)
    recent_expenses = get_recent_expenses(30)
    month_expenses = get_expenses(year, month)

    # 前月比
    prev = get_prev_month_totals(year, month)

    # カテゴリ別（ドーナツチャート用）
    cat_totals = get_category_totals(year, month)
    chart_data = json.dumps({
        "labels": [f"{r['month']}月" for r in summary],
        "revenue": [r["revenue"] for r in summary],
        "expenses": [r["expenses"] for r in summary],
        "profit": [r["profit"] for r in summary],
    })
    donut_data = json.dumps({
        "labels": [c["category"] for c in cat_totals[:10]],
        "values": [c["total"] for c in cat_totals[:10]],
    })

    # コース別人数
    course_counts = {
        name: count_course_students(year, month, kw)
        for name, kw in COURSE_KEYWORDS.items()
    }

    # 定期支出
    recurring = get_recurring_summary(year, month)

    # 収入ランキング（今月上位5）
    ranking = get_revenue_ranking(year, month, limit=5)

    # 予算進捗
    budget_progress = get_budget_progress(year, month)

    return render_template(
        "dashboard.html",
        year=year, month=month,
        monthly_rev=monthly_rev, monthly_exp=monthly_exp, monthly_profit=monthly_profit,
        annual_rev=annual_rev, annual_exp=annual_exp, annual_profit=annual_profit,
        summary=summary,
        tatekae_list=tatekae_list, tatekae_total=tatekae_total,
        recent_expenses=recent_expenses, month_expenses=month_expenses,
        prev=prev,
        chart_data=chart_data, donut_data=donut_data,
        course_counts=course_counts,
        recurring=recurring,
        ranking=ranking,
        budget_progress=budget_progress,
        page="dashboard",
    )


@web.route("/expenses/<expense_id>/settle", methods=["POST"])
def expenses_settle(expense_id):
    """立替えを精算済み（TRANSFER）にする。"""
    try:
        settle_expense(expense_id)
        flash("精算済みに変更しました。", "success")
    except Exception as e:
        flash(f"エラー: {e}", "error")
    return redirect(url_for("web.dashboard"))


@web.route("/search")
def search():
    q = request.args.get("q", "").strip()
    expenses = []
    revenues = []
    if q:
        expenses = search_expenses(q)
        revenues = search_revenue(q)
    return render_template(
        "search.html",
        q=q,
        expenses=expenses,
        revenues=revenues,
        total_expenses=sum(e["amount"] for e in expenses),
        total_revenues=sum(r["amount"] for r in revenues),
        page="search",
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
# 決算書
# ─────────────────────────────────────────────────────────────────────────────

@web.route("/financial")
def financial_report():
    now = datetime.now()
    year = int(request.args.get("year", now.year))
    end_date = request.args.get("end_date", now.strftime("%Y-%m-%d"))
    data = get_financial_statement(year, end_date)
    return render_template("financial_report.html", data=data,
                           year=year, end_date=end_date, page="financial")


# ─────────────────────────────────────────────────────────────────────────────
# 予算管理
# ─────────────────────────────────────────────────────────────────────────────

@web.route("/budget", methods=["GET", "POST"])
def budget():
    now = datetime.now()
    year = int(request.args.get("year", now.year))
    month = int(request.args.get("month", now.month))
    if request.method == "POST":
        year = int(request.form.get("year", now.year))
        month = int(request.form.get("month", now.month))
        for key, val in request.form.items():
            if key.startswith("budget_"):
                cat_id = key[7:]
                try:
                    amount = float(val) if val.strip() else 0.0
                    set_budget(cat_id, year, month, amount)
                except ValueError:
                    pass
        flash("予算を保存しました。", "success")
        return redirect(url_for("web.budget", year=year, month=month))
    categories = get_all_categories()
    budgets = {b["category_id"]: b["amount"] for b in get_budgets(year, month)}
    progress = get_budget_progress(year, month)
    return render_template("budget.html", categories=categories, budgets=budgets,
                           progress=progress, year=year, month=month, page="budget")


# ─────────────────────────────────────────────────────────────────────────────
# CSVエクスポート
# ─────────────────────────────────────────────────────────────────────────────

@web.route("/export/expenses.csv")
def export_expenses_csv():
    now = datetime.now()
    year = int(request.args.get("year", now.year))
    month_raw = request.args.get("month", "")
    month = int(month_raw) if month_raw.isdigit() else None
    rows = get_expenses(year, month)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["日付", "名目", "金額(IDR)", "勘定科目", "支払方法", "支払先", "メモ", "定期"])
    for r in rows:
        w.writerow([r["date"], r["name"], r["amount"], r.get("category_name", ""),
                    r["payment_method"] or "", r["payee"] or "", r["memo"] or "",
                    "定期" if r["is_recurring"] else ""])
    resp = make_response(buf.getvalue())
    resp.headers["Content-Type"] = "text/csv; charset=utf-8-sig"
    resp.headers["Content-Disposition"] = f'attachment; filename="expenses_{year}.csv"'
    return resp


@web.route("/export/revenue.csv")
def export_revenue_csv():
    now = datetime.now()
    year = int(request.args.get("year", now.year))
    month_raw = request.args.get("month", "")
    month = int(month_raw) if month_raw.isdigit() else None
    rows = get_revenue(year, month)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["日付", "名前", "金額(IDR)", "生徒名", "メモ"])
    for r in rows:
        w.writerow([r["date"], r["name"], r["amount"],
                    r["student_name"] or "", r["memo"] or ""])
    resp = make_response(buf.getvalue())
    resp.headers["Content-Type"] = "text/csv; charset=utf-8-sig"
    resp.headers["Content-Disposition"] = f'attachment; filename="revenue_{year}.csv"'
    return resp


# ─────────────────────────────────────────────────────────────────────────────
# PDFレポート
# ─────────────────────────────────────────────────────────────────────────────

@web.route("/pdf/<int:year>")
@web.route("/pdf/<int:year>/<int:month>")
def pdf_report(year, month=None):
    try:
        from reports.pdf_export import monthly_report, annual_report
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        if month:
            path = monthly_report(year, month)
        else:
            path = annual_report(year)
        return send_from_directory(str(path.parent), path.name,
                                   as_attachment=True, mimetype="application/pdf")
    except Exception as e:
        flash(f"PDF生成エラー: {e}", "error")
        return redirect(url_for("web.financial_report", year=year))


# ─────────────────────────────────────────────────────────────────────────────
# レシート配信
# ─────────────────────────────────────────────────────────────────────────────

@web.route("/receipts/<path:filename>")
def serve_receipt(filename):
    filepath = RECEIPTS_DIR / filename
    if not filepath.exists():
        abort(404)
    return send_from_directory(str(RECEIPTS_DIR), filename)


# ─────────────────────────────────────────────────────────────────────────────
# レシート OCR 自動記帳（写真アップロード → Gemini 解析 → 確認 → 保存）
# ─────────────────────────────────────────────────────────────────────────────

@web.route("/receipt_ocr", methods=["GET", "POST"])
def receipt_ocr():
    categories = get_all_categories()

    # ── STEP 3: 確認フォーム送信 → DB 保存 ──────────────────────────────────
    if request.method == "POST" and request.form.get("action") == "confirm":
        record_type = request.form.get("record_type", "expense")
        drive_id    = request.form.get("drive_id", "")
        date_str    = request.form.get("date") or datetime.now().strftime("%Y-%m-%d")
        name        = request.form.get("name", "").strip() or "（名目なし）"
        amount      = float(request.form.get("amount") or 0)
        memo        = request.form.get("memo", "")
        receipt_ref = f"gdrive:{drive_id}" if drive_id else ""

        if record_type == "revenue":
            insert_revenue(
                name=name,
                amount=amount,
                date=date_str,
                student_name=request.form.get("student_name", ""),
                memo=memo,
                receipt_path=receipt_ref,
            )
            flash("売上を記帳しました！", "success")
        else:
            cat_id = upsert_category(request.form.get("category", "")) or None
            insert_expense(
                name=name,
                amount=amount,
                date=date_str,
                category_id=cat_id,
                payment_method=request.form.get("payment_method", ""),
                payee=request.form.get("payee", ""),
                memo=memo,
                receipt_path=receipt_ref,
            )
            flash("経費を記帳しました！", "success")
        return redirect(url_for("web.dashboard"))

    # ── STEP 2: 写真アップロード → OCR → 確認フォーム表示 ───────────────────
    if request.method == "POST" and "photo" in request.files:
        record_type = request.form.get("record_type", "expense")
        file = request.files["photo"]
        if not file or file.filename == "":
            flash("ファイルを選択してください。", "error")
            return render_template("receipt_ocr.html", step=1,
                                   record_type=record_type, categories=categories)

        raw_bytes  = file.read()
        compressed = compress_image(raw_bytes)
        orig_kb    = len(raw_bytes) // 1024
        comp_kb    = len(compressed) // 1024

        result = parse_receipt_from_bytes(compressed)
        if "error" in result:
            flash(f"OCR解析失敗: {result['error']}", "error")
            return render_template("receipt_ocr.html", step=1,
                                   record_type=record_type, categories=categories)

        cat_name = ""
        if record_type == "expense":
            cat_names = [c["name"] for c in categories]
            cat_name  = classify_category(
                result.get("name", ""), result.get("payee", ""),
                result.get("category_hint", ""), cat_names,
            )

        date_str = result.get("date") or datetime.now().strftime("%Y-%m-%d")
        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_web.jpg"
        drive_id = upload_receipt_bytes(compressed, filename, date_str)

        return render_template(
            "receipt_ocr.html",
            step=2,
            record_type=record_type,
            result=result,
            cat_name=cat_name,
            categories=categories,
            drive_id=drive_id,
            filename=filename,
            orig_kb=orig_kb,
            comp_kb=comp_kb,
        )

    # ── STEP 1: 種別選択（経費 or 売上） ─────────────────────────────────────
    record_type = request.args.get("type", "")
    return render_template("receipt_ocr.html", step=1,
                           record_type=record_type, categories=categories)
