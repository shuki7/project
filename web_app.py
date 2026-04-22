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
    session, Response, make_response
)
from werkzeug.utils import secure_filename

from config import (
    RECEIPTS_DIR, fmt_idr, COMPANY_NAME,
    LOGIN_EMAIL, LOGIN_PASSWORD, LOGIN_RESET_TOKEN,
    COURSE_KEYWORDS, REPORTS_DIR, PROJECTS_FILE, DB_PATH,
)
from flask import g
from bot.ocr import parse_receipt_from_bytes, classify_category, compress_image
from sync.gdrive import upload_receipt_bytes
from translations import get_T
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
    get_budget_progress, get_budgets, set_budget, init_db,
    # プロジェクト管理
    get_tasks, insert_task, update_task, delete_task,
    get_contacts, insert_contact, update_contact, delete_contact,
    get_project_info, save_project_info,
    get_jobs, get_job_by_id, insert_job, update_job, delete_job, get_job_summary,
)

web = Blueprint("web", __name__)


# ── プロジェクト管理 ─────────────────────────────────────────────────────────────

from core.projects import load_workspaces, save_workspaces

def _load_projects():
    return load_workspaces()

def _save_projects(projects):
    save_workspaces(projects)

def _get_active_project():
    pid = session.get("project_id")
    if not pid:
        return None
    projects = load_workspaces()
    for p in projects:
        if p["id"] == pid:
            return p
    return None


# ── 言語・翻訳をすべてのテンプレートに注入 ──────────────────────────────────
@web.context_processor
def inject_lang():
    lang = session.get("lang", "ja")
    return {"lang": lang, "T": get_T(lang)}


@web.app_template_filter("from_json")
def from_json_filter(s):
    if not s:
        return []
    try:
        res = json.loads(s)
        return res if isinstance(res, list) else [res]
    except Exception:
        return [s] if s else []


# ─────────────────────────────────────────────────────────────────────────────
# 認証
# ─────────────────────────────────────────────────────────────────────────────

@web.before_request
def check_auth():
    open_endpoints = {"web.login", "web.logout", "web.recover", "web.set_lang", "web.shared_access"}
    if request.endpoint in open_endpoints:
        return
    
    # 閲覧専用ユーザーの場合、許可されたページかチェック
    is_readonly = session.get("read_only", False)
    if is_readonly:
        allowed = session.get("allowed_pages", ["dashboard"])
        # エンドポイント名（例: web.dashboard）からプレフィックスを除いたものを取得
        current_page = request.endpoint.replace("web.", "") if request.endpoint else ""
        
        # 特定の共通エンドポイントは許可（静的分類などは各ページに含まれるため）
        if current_page not in allowed and current_page != "dashboard":
            flash("このページへのアクセス権限がありません。", "error")
            return redirect(url_for("web.dashboard"))

        # 書き込み操作の制限
        if request.method == "POST":
            # 精算や追加などは許可しない
            forbidden_actions = {
                "expenses_new", "expenses_edit", "expenses_delete", "expenses_settle",
                "revenue_new", "revenue_edit", "revenue_delete",
                "categories_new", "categories_edit", "categories_delete",
                "set_budget", "projects_add", "projects_share_add", "projects_share_delete",
                # 新機能もガード
                "tasks", "tasks_new", "tasks_edit", "tasks_delete",
                "contacts", "contacts_new", "contacts_edit", "contacts_delete",
                "project_info", "jobs", "jobs_new", "jobs_edit", "jobs_delete", "job_detail"
            }
            if current_page in forbidden_actions:
                abort(403)

    if not session.get("logged_in") and not is_readonly:
        return redirect(url_for("web.login", next=request.path))
    
    # プロジェクト選択のチェック
    project = _get_active_project()
    if not project and request.endpoint not in ("web.launcher", "web.select_project", "web.add_project", "web.login", "web.logout"):
        return redirect(url_for("web.launcher"))
    
    if project:
        # DBパスを flask.g にセット
        db_path = PROJECTS_FILE.parent / project.get("db", "kakeibo.db")
        g.db_path = db_path
        g.project = project
        g.read_only = is_readonly
        g.allowed_pages = session.get("allowed_pages", [])


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


@web.route("/lang/<lang>")
def set_lang(lang):
    if lang in ("ja", "id"):
        session["lang"] = lang
    return redirect(request.referrer or url_for("web.dashboard"))


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
    return redirect(url_for("web.launcher"))


@web.route("/launcher")
def launcher():
    parent_id = request.args.get("parent_id")
    all_projects = _load_projects()
    
    # 全プロジェクトの中から、誰かの親になっている ID を抽出
    parent_ids = {p["parent_id"] for p in all_projects if p.get("parent_id")}
    
    if parent_id:
        # 子プロジェクト（特定のグループ内）を表示
        display_projects = [p for p in all_projects if p.get("parent_id") == parent_id]
        parent = next((p for p in all_projects if p["id"] == parent_id), None)
    else:
        # 親プロジェクト（または独立したプロジェクト）のみを表示
        display_projects = [p for p in all_projects if not p.get("parent_id")]
        parent = None
        
    return render_template("launcher.html", 
                           projects=display_projects, 
                           parent=parent,
                           parent_ids=parent_ids)


@web.route("/choose/<project_id>")
def select_project(project_id):
    projects = _load_projects()
    project = next((p for p in projects if p["id"] == project_id), None)
    
    if project:
        session["project_id"] = project_id
        session.modified = True
        return redirect(url_for("web.workspace_home"))
    
    flash("プロジェクトが見つかりません。", "error")
    return redirect(url_for("web.launcher"))


@web.route("/projects/add", methods=["POST"])
def add_project():
    name = request.form.get("name", "").strip()
    emoji = request.form.get("emoji", "").strip() or "📁"
    color = request.form.get("color", "#3b82f6")
    parent_id = request.form.get("parent_id")
    is_group = request.form.get("is_group") == "1"
    
    if not name:
        flash("名前は必須です。", "error")
        return redirect(url_for("web.launcher", parent_id=parent_id))
    
    projects = _load_projects()
    pid = str(uuid.uuid4())[:8]
    db_name = f"kakeibo_{pid}.db"
    
    new_p = {
        "id": pid,
        "name": name,
        "emoji": emoji,
        "db": db_name,
        "color": color,
        "is_group": is_group
    }
    if parent_id:
        new_p["parent_id"] = parent_id
        
    projects.append(new_p)
    _save_projects(projects)
    
    # 新しいDBの初期化
    db_path = PROJECTS_FILE.parent / db_name
    from core.database import init_db, get_connection, SCHEMA_SQL
    
    # Explicitly init the new DB
    conn = get_connection(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.close()

    flash(f"プロジェクト「{name}」を作成しました。", "success")
    return redirect(url_for("web.launcher", parent_id=parent_id))


@web.route("/share/<token>")
def shared_access(token):
    """トークンによる閲覧専用アクセスを許可する。"""
    projects = _load_projects()
    for p in projects:
        shares = p.get("shares", [])
        for s in shares:
            if s["id"] == token:
                # 閲覧専用セッションを開始
                session.clear()
                session["project_id"] = p["id"]
                session["read_only"] = True
                session["allowed_pages"] = s.get("allowed_pages", ["dashboard"])
                flash(f"{p['name']} の閲覧モードでログインしました。", "success")
                return redirect(url_for("web.dashboard"))
    
    flash("無効な共有リンクです。", "error")
    return redirect(url_for("web.login"))


@web.route("/projects/shares/add", methods=["POST"])
def projects_share_add():
    """プロジェクトに新しい共有リンクを追加する。"""
    project_id = request.form.get("project_id")
    partner_name = request.form.get("partner_name", "パートナー様").strip()
    allowed_pages = request.form.getlist("allowed_pages")
    
    if not allowed_pages:
        allowed_pages = ["dashboard"] # 最小権限

    projects = _load_projects()
    target = next((p for p in projects if p["id"] == project_id), None)
    if not target:
        flash("プロジェクトが見つかりません。", "error")
        return redirect(url_for("web.launcher"))

    if "shares" not in target:
        target["shares"] = []
    
    new_share = {
        "id": str(uuid.uuid4()),
        "name": partner_name,
        "allowed_pages": allowed_pages,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M")
    }
    target["shares"].append(new_share)
    _save_projects(projects)
    
    flash(f"「{partner_name}」用の共有リンクを作成しました。", "success")
    return redirect(url_for("web.launcher"))


@web.route("/projects/shares/delete", methods=["POST"])
def projects_share_delete():
    """共有リンクを削除する。"""
    project_id = request.form.get("project_id")
    share_id = request.form.get("share_id")

    projects = _load_projects()
    target = next((p for p in projects if p["id"] == project_id), None)
    if target and "shares" in target:
        target["shares"] = [s for s in target["shares"] if s["id"] != share_id]
        _save_projects(projects)
        flash("共有リンクを削除しました。", "success")
    
    return redirect(url_for("web.launcher"))

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "pdf"}
IMAGE_EXTENSIONS   = {"png", "jpg", "jpeg", "gif", "webp"}
PAYMENT_METHODS = ["CASH", "TRANSFER", "DEBIT", "立替え"]


def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _save_receipt(file, date_str: str = None, kind: str = "expenses") -> str:
    """
    アップロードされたファイルを圧縮して WebP 形式で Google Drive に保存する。
    成功時は 'gdrive:<fileId>' を返す。
    """
    if not file or file.filename == "":
        return None
    if not _allowed_file(file.filename):
        return None

    raw_bytes = file.read()
    ext_original = file.filename.rsplit(".", 1)[1].lower() if "." in file.filename else "jpg"
    
    # 画像は WebP 圧縮、PDF などはそのまま
    if ext_original in IMAGE_EXTENSIONS:
        compressed = compress_image(raw_bytes)
        ext_target = "webp"
    else:
        compressed = raw_bytes
        ext_target = ext_original

    if date_str is None:
        date_str = datetime.now().strftime("%Y-%m-%d")

    filename = f"{date_str.replace('-', '')}_{uuid.uuid4().hex[:8]}.{ext_target}"

    # 現在のプロジェクト名を取得（g.project から）
    proj = getattr(g, "project", None)
    project_name = proj.get("name") if proj else None

    # Google Drive にアップロード
    drive_id = upload_receipt_bytes(
        compressed, filename, date_str,
        project_name=project_name, kind=kind,
    )
    if drive_id:
        return f"gdrive:{drive_id}"

    # フォールバック: ローカル保存
    RECEIPTS_DIR.mkdir(parents=True, exist_ok=True)
    local_path = RECEIPTS_DIR / filename
    local_path.write_bytes(compressed)
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
    project = getattr(g, "project", None)
    read_only = getattr(g, "read_only", False)
    allowed_pages = getattr(g, "allowed_pages", [])
    return {
        "fmt_idr": fmt_idr,
        "company_name": project["name"] if project else COMPANY_NAME,
        "project_emoji": project["emoji"] if project else "",
        "current_year": datetime.now().year,
        "current_month": datetime.now().month,
        "active_project": project,
        "read_only": read_only,
        "allowed_pages": allowed_pages,
    }


# ─────────────────────────────────────────────────────────────────────────────
# ダッシュボード
# ─────────────────────────────────────────────────────────────────────────────

@web.route("/")
def dashboard():
    # 統合運用のため、トップページはまずプロジェクト選択画面（ランチャー）へ
    return redirect(url_for("web.launcher"))

@web.route("/dashboard")
def job_dashboard():
    now = datetime.now()
    year  = int(request.args.get("year",  now.year))
    month = int(request.args.get("month", now.month))
    # 範囲チェック
    if month < 1:  month = 1
    if month > 12: month = 12

    # 前月・翌月のリンク用
    if month == 1:
        prev_year, prev_month = year - 1, 12
    else:
        prev_year, prev_month = year, month - 1
    if month == 12:
        next_year, next_month = year + 1, 1
    else:
        next_year, next_month = year, month + 1
    is_current_month = (year == now.year and month == now.month)

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
        prev_year=prev_year, prev_month=prev_month,
        next_year=next_year, next_month=next_month,
        is_current_month=is_current_month,
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
            files = request.files.getlist("receipt")
            receipt_paths = []
            # 最大5枚制限
            for f in files[:5]:
                path = _save_receipt(f, date)
                if path:
                    receipt_paths.append(path)
            
            # JSON 形式で保存
            receipt_path_json = json.dumps(receipt_paths) if receipt_paths else None

            insert_expense(
                name=name,
                amount=float(amount),
                date=date,
                category_id=category_id,
                payment_method=payment_method,
                payee=payee,
                memo=memo,
                is_recurring=is_recurring,
                receipt_path=receipt_path_json,
                contact_id=request.form.get("contact_id") or None,
                job_id=request.form.get("job_id") or None,
            )
            flash(f"経費を追加しました（添付: {len(receipt_paths)}枚）", "success")
            return redirect(url_for("web.expenses_list"))
        except Exception as e:
            flash(f"エラーが発生しました: {e}", "error")

    today = datetime.now().strftime("%Y-%m-%d")
    contacts = get_contacts('vendor')
    jobs = get_jobs('active')
    return render_template(
        "expenses/form.html",
        categories=categories,
        payment_methods=PAYMENT_METHODS,
        expense={"date": today},
        contacts=contacts,
        jobs=jobs,
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
            contacts = get_contacts('vendor')
            jobs = get_jobs('active')
            return render_template(
                "expenses/form.html",
                categories=categories,
                payment_methods=PAYMENT_METHODS,
                expense=expense,
                contacts=contacts,
                jobs=jobs,
                title="経費を編集",
                page="expenses",
            )

        try:
            files = request.files.getlist("receipt")
            new_paths = []
            for f in files[:5]:
                path = _save_receipt(f, date)
                if path:
                    new_paths.append(path)
            
            # 新しいアップロードがあれば更新、なければ既存を維持
            receipt_path = json.dumps(new_paths) if new_paths else expense.get("receipt_path")

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
                contact_id=request.form.get("contact_id") or None,
                job_id=request.form.get("job_id") or None,
            )
            flash("経費を更新しました。", "success")
            return redirect(url_for("web.expenses_list"))
        except Exception as e:
            flash(f"エラーが発生しました: {e}", "error")

    contacts = get_contacts('vendor')
    jobs = get_jobs('active')
    return render_template(
        "expenses/form.html",
        categories=categories,
        payment_methods=PAYMENT_METHODS,
        expense=expense,
        contacts=contacts,
        jobs=jobs,
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
        receipt_file = request.files.get("receipt")

        if not name or not amount or not date:
            flash("日付・名前・金額は必須です。", "error")
            return render_template(
                "revenue/form.html",
                revenue=request.form,
                title="収入を追加",
                page="revenue",
            )

        try:
            files = request.files.getlist("receipt")
            receipt_paths = []
            for f in files[:5]:
                path = _save_receipt(f, date, kind="revenue")
                if path:
                    receipt_paths.append(path)
            
            receipt_path_json = json.dumps(receipt_paths) if receipt_paths else None

            insert_revenue(
                name=name,
                amount=float(amount),
                date=date,
                student_name=student_name,
                memo=memo,
                receipt_path=receipt_path_json,
                contact_id=request.form.get("contact_id") or None,
                job_id=request.form.get("job_id") or None,
                category_id=request.form.get("category_id") or None,
            )
            flash(f"収入を追加しました（添付: {len(receipt_paths)}枚）", "success")
            return redirect(url_for("web.revenue_list"))
        except Exception as e:
            flash(f"エラーが発生しました: {e}", "error")

    today = datetime.now().strftime("%Y-%m-%d")
    contacts = get_contacts('customer')
    jobs = get_jobs('active')
    categories = get_all_categories()
    return render_template(
        "revenue/form.html",
        revenue={"date": today},
        contacts=contacts,
        jobs=jobs,
        categories=categories,
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
        receipt_file = request.files.get("receipt")

        if not name or not amount or not date:
            flash("日付・名前・金額は必須です。", "error")
            return render_template(
                "revenue/form.html",
                revenue=revenue,
                title="収入を編集",
                page="revenue",
            )

        try:
            files = request.files.getlist("receipt")
            new_paths = []
            for f in files[:5]:
                path = _save_receipt(f, date, kind="revenue")
                if path:
                    new_paths.append(path)
            
            # 新しいアップロードがあれば更新、なければ既存を維持
            receipt_path = json.dumps(new_paths) if new_paths else revenue.get("receipt_path")

            update_revenue(
                revenue_id=revenue_id,
                name=name,
                amount=float(amount),
                date=date,
                student_name=student_name,
                memo=memo,
                receipt_path=receipt_path,
                contact_id=request.form.get("contact_id") or None,
                job_id=request.form.get("job_id") or None,
                category_id=request.form.get("category_id") or None,
            )
            flash("収入を更新しました。", "success")
            return redirect(url_for("web.revenue_list"))
        except Exception as e:
            flash(f"エラーが発生しました: {e}", "error")

    contacts = get_contacts('customer')
    jobs = get_jobs('active')
    categories = get_all_categories()
    return render_template(
        "revenue/form.html",
        revenue=revenue,
        contacts=contacts,
        jobs=jobs,
        categories=categories,
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
        from reports.pdf_export import export_monthly_pdf, export_annual_pdf
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        if month:
            path = export_monthly_pdf(year, month)
        else:
            path = export_annual_pdf(year)
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
                job_id=request.form.get("job_id") or None,
                contact_id=request.form.get("contact_id") or None,
                category_id=upsert_category(request.form.get("category", "")) if request.form.get("category") else None,
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
                job_id=request.form.get("job_id") or None,
                contact_id=request.form.get("contact_id") or None,
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

        contacts_v = get_contacts('vendor')
        contacts_c = get_contacts('customer')
        jobs = get_jobs('active')

        return render_template(
            "receipt_ocr.html",
            step=2,
            record_type=record_type,
            result=result,
            cat_name=cat_name,
            categories=categories,
            contacts_v=contacts_v,
            contacts_c=contacts_c,
            jobs=jobs,
            drive_id=drive_id,
            filename=filename,
            orig_kb=orig_kb,
            comp_kb=comp_kb,
        )

    # ── STEP 1: 種別選択（経費 or 売上） ─────────────────────────────────────
    record_type = request.args.get("type", "")
    return render_template("receipt_ocr.html", step=1,
                           record_type=record_type, categories=categories)


# ─────────────────────────────────────────────────────────────────────────────
# プロジェクト管理機能 (Management Features)
# ─────────────────────────────────────────────────────────────────────────────

@web.route("/tasks", methods=["GET", "POST"])
def tasks():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            insert_task(
                title=request.form.get("title"),
                description=request.form.get("description"),
                priority=request.form.get("priority", "middle"),
                due_date=request.form.get("due_date")
            )
            flash("タスクを追加しました", "success")
        elif action == "update":
            update_task(
                task_id=request.form.get("id"),
                title=request.form.get("title"),
                description=request.form.get("description"),
                status=request.form.get("status"),
                priority=request.form.get("priority"),
                due_date=request.form.get("due_date"),
                is_archived=int(request.form.get("is_archived", 0))
            )
        return redirect(url_for("web.tasks"))

    include_archived = request.args.get("archived") == "1"
    tasks_list = get_tasks(include_archived)
    return render_template("tasks/list.html", tasks=tasks_list, archived=include_archived, page="tasks")

@web.route("/tasks/delete/<id>", methods=["POST"])
def tasks_delete(id):
    delete_task(id)
    flash("タスクを削除しました", "success")
    return redirect(url_for("web.tasks"))


@web.route("/contacts", methods=["GET", "POST"])
def contacts():
    if request.method == "POST":
        id = request.form.get("id")
        data = {
            "contact_type": request.form.get("type"),
            "name": request.form.get("name"),
            "contact_person": request.form.get("contact_person"),
            "phone": request.form.get("phone"),
            "email": request.form.get("email"),
            "address": request.form.get("address"),
            "bank_info": request.form.get("bank_info"),
            "memo": request.form.get("memo")
        }
        if id:
            update_contact(id, **data)
            flash("連絡先を更新しました", "success")
        else:
            insert_contact(**data)
            flash("連絡先を追加しました", "success")
        return redirect(url_for("web.contacts"))

    contacts_list = get_contacts()
    return render_template("contacts/list.html", contacts=contacts_list, page="contacts")

@web.route("/contacts/delete/<id>", methods=["POST"])
def contacts_delete(id):
    delete_contact(id)
    flash("連絡先を削除しました", "success")
    return redirect(url_for("web.contacts"))


@web.route("/info", methods=["GET", "POST"])
def project_info():
    if request.method == "POST":
        save_project_info(
            bank_info=request.form.get("bank_info"),
            facility_info=request.form.get("facility_info"),
            emergency_info=request.form.get("emergency_info")
        )
        flash("情報を保存しました", "success")
        return redirect(url_for("web.project_info"))

    info = get_project_info()
    return render_template("project_info/view.html", info=info, page="info")


@web.route("/jobs", methods=["GET", "POST"])
def jobs():
    if request.method == "POST":
        id = request.form.get("id")
        data = {
            "name": request.form.get("name"),
            "start_date": request.form.get("start_date"),
            "status": request.form.get("status", "active")
        }
        if id:
            update_job(id, **data)
            flash("案件を更新しました", "success")
        else:
            insert_job(**data)
            flash("案件を追加しました", "success")
        return redirect(url_for("web.jobs"))

    status_filter = request.args.get("status")
    jobs_list = get_jobs(status_filter)
    return render_template("jobs/list.html", jobs=jobs_list, status_filter=status_filter, page="jobs")

@web.route("/jobs/<id>")
def job_detail(id):
    job = get_job_by_id(id)
    if not job:
        abort(404)
    summary = get_job_summary(id)
    return render_template("jobs/detail.html", job=job, summary=summary, page="jobs")

@web.route("/jobs/delete/<id>", methods=["POST"])
def jobs_delete(id):
    delete_job(id)
    flash("案件を削除しました", "success")
    return redirect(url_for("web.jobs"))
@web.route("/home")
def workspace_home():
    """ワークスペースのホーム画面（メニューグリッド）を表示する。"""
    from core.database import get_project_attachments
    # 社長の顔写真を探す
    photos = get_project_attachments(1, category="photo")
    president_photo = next((p for p in photos if p.get("notes") == "社長の顔写真"), None)
    
    return render_template("workspace_home.html", page="home", president_photo=president_photo)


@web.route("/staff")
def staff():
    """現在のワークスペース内のスタッフ一覧を表示する。"""
    from core.database import get_staff_by_project
    staff_list = get_staff_by_project(0) 
    if not staff_list:
        staff_list = get_staff_by_project(1)
        
    return render_template("staff_workspace.html", staff=staff_list, page="staff")


@web.route("/links", methods=["GET", "POST"])
def links():
    """現在のワークスペース内のURLリンク一覧を管理する。"""
    from core.database import get_project_info_items, save_project_info_item, delete_project_info_item
    import json
    import uuid

    if request.method == "POST":
        action = request.form.get("action")
        if action == "delete":
            item_id = request.form.get("id")
            delete_project_info_item(item_id)
            flash("リンクを削除しました", "success")
        else:
            item_id = request.form.get("id") or str(uuid.uuid4())
            label = request.form.get("label")
            url = request.form.get("url")
            category = "url"
            fields_json = json.dumps({"url": url})
            # ワークスペース内は project_id=1 固定とする
            save_project_info_item(item_id, 1, category, label, fields_json)
            flash("リンクを保存しました", "success")
        return redirect(url_for("web.links"))

    # project_id=1 の項目を取得
    items = get_project_info_items(1, category="url")
    # JSONデコード
    links_list = []
    for it in items:
        d = dict(it)
        try:
            d["fields"] = json.loads(it["fields_json"])
        except:
            d["fields"] = {}
        links_list.append(d)

    return render_template("links_workspace.html", links=links_list, page="urls")


@web.route("/gallery", methods=["GET", "POST"])
def gallery():
    """プロジェクトのギャラリー（写真）を管理する。"""
    from core.database import (
        get_project_attachments, get_project_attachment,
        insert_project_attachment, delete_project_attachment
    )
    from sync.gdrive import upload_project_file_bytes, delete_drive_file
    import uuid

    if request.method == "POST":
        action = request.form.get("action")
        if action == "delete":
            att_id = request.form.get("id")
            att = get_project_attachment(att_id)
            # 実際には Drive からも消すべきだが、まずは DB から
            delete_project_attachment(att_id)
            if att and att.get("drive_file_id"):
                delete_drive_file(att["drive_file_id"])
            flash("写真を削除しました", "success")
        else:
            file = request.files.get("photo")
            if file and file.filename:
                file_bytes = file.read()
                filename = file.filename
                mime_type = file.mimetype
                size = len(file_bytes)
                notes = request.form.get("notes", "") # 例: 'president'
                
                # Driveへアップロード
                res = upload_project_file_bytes(
                    project_name=session.get("company_name", "Unknown"),
                    file_bytes=file_bytes,
                    filename=filename,
                    mime_type=mime_type,
                    subfolder="gallery"
                )
                
                if res.get("file_id"):
                    insert_project_attachment(
                        project_id=1,
                        filename=filename,
                        drive_file_id=res["file_id"],
                        drive_url=res["url"],
                        mime_type=mime_type,
                        size_bytes=size,
                        notes=notes,
                        category="photo"
                    )
                    flash("写真をアップロードしました", "success")
                else:
                    flash("アップロードに失敗しました", "error")
        return redirect(url_for("web.gallery"))

    # 写真一覧を取得
    photos = get_project_attachments(1, category="photo")
    return render_template("gallery_workspace.html", photos=photos, page="gallery")
