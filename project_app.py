"""
プロジェクト管理 Blueprint — /keiri/project/*

Phase 1:
  - プロジェクト一覧 / 追加 / 編集 / 削除
  - プロジェクト詳細（後続 Phase で タスク・情報・スタッフ・共有 を追加）
"""

from datetime import date

from flask import (
    Blueprint, render_template, request, redirect,
    url_for, flash, session, current_app,
)
from core.projects import load_workspaces, create_partner_workspace

from core.database import (
    get_all_projects, get_project_by_id,
    insert_project, update_project, delete_project,
    # Phase 2: tasks
    TASK_STATUSES, TASK_PRIORITIES,
    get_tasks_by_project, get_task_by_id,
    insert_project_task, update_project_task,
    update_task_status, count_tasks_by_status,
    delete_task,
    # Phase 3: project info + attachments
    INFO_CATEGORIES, INFO_FIELD_LABELS,
    get_project_info_items, get_project_info_item,
    insert_project_info_item, update_project_info_item,
    delete_project_info_item,
    get_project_attachments, insert_project_attachment,
    get_project_attachment, delete_project_attachment,
    # Phase 4: staff
    STAFF_EMPLOYMENT_TYPES, STAFF_STATUSES, STAFF_FIELD_LABELS,
    get_staff_by_project, get_staff_by_id,
    insert_staff, update_staff, delete_staff,
    count_staff_by_status,
)
from translations import get_T

project_bp = Blueprint("project", __name__)
# LiteSpeed がトレーリングスラッシュを除去するためリダイレクトループ回避
# → 各ルートに strict_slashes=False を付与する


# 既存 web Blueprint と同じ認証・言語注入
@project_bp.context_processor
def inject_lang():
    lang = session.get("lang", "ja")
    return {"lang": lang, "T": get_T(lang)}


@project_bp.before_request
def check_auth():
    if not session.get("logged_in"):
        # SCRIPT_NAME (=/project) を含む絶対パスを next に渡す。
        # これを付けないと web.login の redirect(next) が "/" を
        # ホストルートとして扱い、shuki.link/index.html に飛んでしまう。
        target = (request.script_root or "") + request.path
        return redirect(url_for("web.login", next=target))


# ─────────────────────────────────────────────────────────────────────────────
# 一覧
# ─────────────────────────────────────────────────────────────────────────────
@project_bp.route("/", methods=["GET"], strict_slashes=False)
def list_projects():
    show_archived = request.args.get("archived") == "1"
    projects = get_all_projects(include_archived=show_archived)
    return render_template(
        "project/list.html",
        projects=projects,
        show_archived=show_archived,
        page="list",
    )


# ─────────────────────────────────────────────────────────────────────────────
# 新規作成
# ─────────────────────────────────────────────────────────────────────────────
@project_bp.route("/new", methods=["GET", "POST"], strict_slashes=False)
def new_project():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("プロジェクト名は必須です。", "error")
            return redirect(url_for("project.new_project"))
        pid = insert_project(
            name=name,
            emoji=(request.form.get("emoji") or "").strip(),
            color=(request.form.get("color") or "#16213e").strip(),
            description=(request.form.get("description") or "").strip(),
            sort_order=int(request.form.get("sort_order") or 0),
            start_date=(request.form.get("start_date") or "").strip(),
            client_name=(request.form.get("client_name") or "").strip(),
            manager_name=(request.form.get("manager_name") or "").strip(),
        )
        # ランチャー用に同期
        from core.projects import sync_master_projects
        sync_master_projects()
        
        flash(f"プロジェクト「{name}」を作成しました。", "success")
        return redirect(url_for("project.detail", project_id=pid))
    return render_template("project/form.html", project=None, page="new")


# ─────────────────────────────────────────────────────────────────────────────
# 詳細
# ─────────────────────────────────────────────────────────────────────────────
@project_bp.route("/<int:project_id>", methods=["GET"], strict_slashes=False)
def detail(project_id):
    project = get_project_by_id(project_id)
    if not project:
        flash("プロジェクトが見つかりません。", "error")
        return redirect(url_for("project.list_projects"))
    return render_template("project/detail.html", project=project)


# ─────────────────────────────────────────────────────────────────────────────
# 編集
# ─────────────────────────────────────────────────────────────────────────────
@project_bp.route("/<int:project_id>/edit", methods=["GET", "POST"], strict_slashes=False)
def edit_project(project_id):
    project = get_project_by_id(project_id)
    if not project:
        flash("プロジェクトが見つかりません。", "error")
        return redirect(url_for("project.list_projects"))

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("プロジェクト名は必須です。", "error")
            return redirect(url_for("project.edit_project", project_id=project_id))
        update_project(
            project_id=project_id,
            name=name,
            emoji=(request.form.get("emoji") or "").strip(),
            color=(request.form.get("color") or "#16213e").strip(),
            description=(request.form.get("description") or "").strip(),
            status=(request.form.get("status") or "active").strip(),
            sort_order=int(request.form.get("sort_order") or 0),
            start_date=(request.form.get("start_date") or "").strip(),
            client_name=(request.form.get("client_name") or "").strip(),
            manager_name=(request.form.get("manager_name") or "").strip(),
        )
        flash("プロジェクトを更新しました。", "success")
        return redirect(url_for("project.detail", project_id=project_id))

    return render_template("project/form.html", project=project)


# ─────────────────────────────────────────────────────────────────────────────
# アーカイブ / アーカイブ解除
# ─────────────────────────────────────────────────────────────────────────────
@project_bp.route("/<int:project_id>/archive", methods=["POST"], strict_slashes=False)
def archive(project_id):
    project = get_project_by_id(project_id)
    if not project:
        flash("プロジェクトが見つかりません。", "error")
        return redirect(url_for("project.list_projects"))
    new_status = "active" if project.get("status") == "archived" else "archived"
    update_project(
        project_id=project_id,
        name=project["name"],
        emoji=project.get("emoji") or "",
        color=project.get("color") or "#16213e",
        description=project.get("description") or "",
        status=new_status,
        sort_order=project.get("sort_order") or 0,
        start_date=project.get("start_date") or "",
        client_name=project.get("client_name") or "",
        manager_name=project.get("manager_name") or "",
    )
    if new_status == "archived":
        flash(f"プロジェクト「{project['name']}」をアーカイブしました。", "success")
        return redirect(url_for("project.list_projects"))
    else:
        flash(f"プロジェクト「{project['name']}」のアーカイブを解除しました。", "success")
        return redirect(url_for("project.detail", project_id=project_id))


# ─────────────────────────────────────────────────────────────────────────────
# 削除
# ─────────────────────────────────────────────────────────────────────────────
@project_bp.route("/<int:project_id>/delete", methods=["POST"], strict_slashes=False)
def delete(project_id):
    project = get_project_by_id(project_id)
    if not project:
        flash("プロジェクトが見つかりません。", "error")
        return redirect(url_for("project.list_projects"))
    delete_project(project_id)
    flash(f"プロジェクト「{project['name']}」を削除しました。", "success")
    return redirect(url_for("project.list_projects"))


# ─────────────────────────────────────────────────────────────────────────────
# タスク管理 (Phase 2) — カンバン形式 5 ステータス
# ─────────────────────────────────────────────────────────────────────────────
@project_bp.route("/<int:project_id>/tasks", methods=["GET"], strict_slashes=False)
def tasks_list(project_id):
    project = get_project_by_id(project_id)
    if not project:
        flash("プロジェクトが見つかりません。", "error")
        return redirect(url_for("project.list_projects"))
    show_archived = request.args.get("archived") == "1"
    tasks = get_tasks_by_project(project_id, include_archived=show_archived)
    # ステータスごとにグルーピング
    columns = {key: [] for key, _, _ in TASK_STATUSES}
    for t in tasks:
        st = t.get("status") or "pending"
        if st not in columns:
            st = "pending"
        columns[st].append(t)
    counts = count_tasks_by_status(project_id)
    return render_template(
        "project/tasks.html",
        project=project,
        columns=columns,
        statuses=TASK_STATUSES,
        priorities=TASK_PRIORITIES,
        counts=counts,
        show_archived=show_archived,
        today=date.today().isoformat(),
    )


@project_bp.route("/<int:project_id>/tasks/new", methods=["GET", "POST"], strict_slashes=False)
def tasks_new(project_id):
    project = get_project_by_id(project_id)
    if not project:
        flash("プロジェクトが見つかりません。", "error")
        return redirect(url_for("project.list_projects"))
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        if not title:
            flash("タイトルは必須です。", "error")
            return redirect(url_for("project.tasks_new", project_id=project_id))
        insert_project_task(
            project_id=project_id,
            title=title,
            description=(request.form.get("description") or "").strip(),
            status=(request.form.get("status") or "pending").strip(),
            priority=(request.form.get("priority") or "middle").strip(),
            due_date=(request.form.get("due_date") or "").strip() or None,
            assignee=(request.form.get("assignee") or "").strip(),
            sort_order=int(request.form.get("sort_order") or 0),
        )
        flash(f"タスク「{title}」を追加しました。", "success")
        return redirect(url_for("project.tasks_list", project_id=project_id))
    return render_template(
        "project/task_form.html",
        project=project,
        task=None,
        statuses=TASK_STATUSES,
        priorities=TASK_PRIORITIES,
    )


@project_bp.route("/<int:project_id>/tasks/<task_id>/edit", methods=["GET", "POST"], strict_slashes=False)
def tasks_edit(project_id, task_id):
    project = get_project_by_id(project_id)
    task = get_task_by_id(task_id)
    if not project or not task:
        flash("タスクが見つかりません。", "error")
        return redirect(url_for("project.tasks_list", project_id=project_id))
    if request.method == "POST":
        title = (request.form.get("title") or "").strip()
        if not title:
            flash("タイトルは必須です。", "error")
            return redirect(url_for("project.tasks_edit",
                                    project_id=project_id, task_id=task_id))
        update_project_task(
            task_id=task_id,
            title=title,
            description=(request.form.get("description") or "").strip(),
            status=(request.form.get("status") or "pending").strip(),
            priority=(request.form.get("priority") or "middle").strip(),
            due_date=(request.form.get("due_date") or "").strip() or None,
            assignee=(request.form.get("assignee") or "").strip(),
            sort_order=int(request.form.get("sort_order") or 0),
            is_archived=1 if request.form.get("is_archived") else 0,
        )
        flash("タスクを更新しました。", "success")
        return redirect(url_for("project.tasks_list", project_id=project_id))
    return render_template(
        "project/task_form.html",
        project=project,
        task=task,
        statuses=TASK_STATUSES,
        priorities=TASK_PRIORITIES,
    )


@project_bp.route("/<int:project_id>/tasks/<task_id>/status", methods=["POST"], strict_slashes=False)
def tasks_set_status(project_id, task_id):
    """カンバン上での即時ステータス変更（select onchange で submit）。"""
    new_status = (request.form.get("status") or "pending").strip()
    valid = {s for s, _, _ in TASK_STATUSES}
    if new_status not in valid:
        new_status = "pending"
    update_task_status(task_id, new_status)
    return redirect(url_for("project.tasks_list", project_id=project_id))


@project_bp.route("/<int:project_id>/tasks/<task_id>/delete", methods=["POST"], strict_slashes=False)
def tasks_delete(project_id, task_id):
    delete_task(task_id)
    flash("タスクを削除しました。", "success")
    return redirect(url_for("project.tasks_list", project_id=project_id))


# ─────────────────────────────────────────────────────────────────────────────
# プロジェクト情報 (Phase 3) — 住所/Wi-Fi/銀行/公共料金/緊急連絡先/契約書/その他
# ─────────────────────────────────────────────────────────────────────────────

def _category_meta(cat_key):
    for k, label, fields in INFO_CATEGORIES:
        if k == cat_key:
            return {"key": k, "label": label, "fields": fields}
    return None


@project_bp.route("/<int:project_id>/info", methods=["GET"], strict_slashes=False)
def info(project_id):
    project = get_project_by_id(project_id)
    if not project:
        flash("プロジェクトが見つかりません。", "error")
        return redirect(url_for("project.list_projects"))

    items_all = get_project_info_items(project_id)
    grouped = {k: [] for k, _, _ in INFO_CATEGORIES}
    for it in items_all:
        cat = it.get("category") or "other"
        if cat not in grouped:
            grouped[cat] = []
        grouped[cat].append(it)

    # 添付ファイル一覧（カテゴリ別に紐付け & 全体）
    attachments = get_project_attachments(project_id)
    atts_by_item = {}
    for a in attachments:
        key = a.get("info_item_id") or "_unattached"
        atts_by_item.setdefault(key, []).append(a)

    return render_template(
        "project/info.html",
        project=project,
        categories=INFO_CATEGORIES,
        field_labels=INFO_FIELD_LABELS,
        grouped=grouped,
        attachments=attachments,
        atts_by_item=atts_by_item,
    )


@project_bp.route("/<int:project_id>/info/items/new", methods=["GET", "POST"], strict_slashes=False)
def info_item_new(project_id):
    project = get_project_by_id(project_id)
    if not project:
        flash("プロジェクトが見つかりません。", "error")
        return redirect(url_for("project.list_projects"))
    category = (request.args.get("category") or request.form.get("category") or "other").strip()
    meta = _category_meta(category) or _category_meta("other")

    if request.method == "POST":
        label = (request.form.get("label") or "").strip()
        fields = {}
        for key in meta["fields"]:
            fields[key] = (request.form.get(f"field_{key}") or "").strip()
        if not label and not any(fields.values()):
            flash("ラベルまたは少なくとも 1 項目の入力が必要です。", "error")
            return redirect(url_for("project.info_item_new",
                                    project_id=project_id, category=category))
        insert_project_info_item(
            project_id=project_id,
            category=category,
            label=label,
            fields=fields,
            sort_order=int(request.form.get("sort_order") or 0),
        )
        flash(f"{meta['label']}「{label or '(無題)'}」を追加しました。", "success")
        return redirect(url_for("project.info", project_id=project_id))

    return render_template(
        "project/info_form.html",
        project=project,
        item=None,
        meta=meta,
        field_labels=INFO_FIELD_LABELS,
        categories=INFO_CATEGORIES,
    )


@project_bp.route("/<int:project_id>/info/items/<item_id>/edit", methods=["GET", "POST"], strict_slashes=False)
def info_item_edit(project_id, item_id):
    project = get_project_by_id(project_id)
    item = get_project_info_item(item_id)
    if not project or not item:
        flash("項目が見つかりません。", "error")
        return redirect(url_for("project.info", project_id=project_id))
    meta = _category_meta(item["category"]) or _category_meta("other")

    if request.method == "POST":
        label = (request.form.get("label") or "").strip()
        fields = {}
        for key in meta["fields"]:
            fields[key] = (request.form.get(f"field_{key}") or "").strip()
        update_project_info_item(
            item_id=item_id,
            label=label,
            fields=fields,
            sort_order=int(request.form.get("sort_order") or 0),
        )
        flash("更新しました。", "success")
        return redirect(url_for("project.info", project_id=project_id))

    # 既存添付
    item_atts = get_project_attachments(project_id, info_item_id=item_id)
    return render_template(
        "project/info_form.html",
        project=project,
        item=item,
        meta=meta,
        field_labels=INFO_FIELD_LABELS,
        categories=INFO_CATEGORIES,
        item_attachments=item_atts,
    )


@project_bp.route("/<int:project_id>/info/items/<item_id>/delete", methods=["POST"], strict_slashes=False)
def info_item_delete(project_id, item_id):
    delete_project_info_item(item_id)
    flash("項目を削除しました。", "success")
    return redirect(url_for("project.info", project_id=project_id))


# ─── 添付ファイル (Google Drive) ────────────────────────────────────────────
def _maybe_convert_to_webp(file_bytes: bytes, filename: str, mime_type: str):
    """画像なら WebP に変換して軽量化。画像以外はそのまま返す。
    Returns: (bytes, filename, mime_type)
    """
    if not mime_type or not mime_type.startswith("image/"):
        return file_bytes, filename, mime_type
    if mime_type == "image/webp":
        return file_bytes, filename, mime_type
    try:
        from PIL import Image
        import io as _io
        img = Image.open(_io.BytesIO(file_bytes))
        # EXIF 回転を反映
        try:
            from PIL import ImageOps
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGB")
        # 最大長辺 2000px に縮小
        max_side = 2000
        if max(img.size) > max_side:
            ratio = max_side / max(img.size)
            new_size = (int(img.size[0] * ratio), int(img.size[1] * ratio))
            img = img.resize(new_size, Image.LANCZOS)
        out = _io.BytesIO()
        img.save(out, format="WEBP", quality=80, method=6)
        new_bytes = out.getvalue()
        # 拡張子を .webp に
        from pathlib import Path as _P
        new_name = _P(filename).stem + ".webp"
        return new_bytes, new_name, "image/webp"
    except Exception:
        # Pillow 未インストール / 変換失敗 → 元のまま
        return file_bytes, filename, mime_type


@project_bp.route("/<int:project_id>/info/attachments/upload", methods=["POST"], strict_slashes=False)
def info_attachment_upload(project_id):
    project = get_project_by_id(project_id)
    if not project:
        flash("プロジェクトが見つかりません。", "error")
        return redirect(url_for("project.list_projects"))

    f = request.files.get("file")
    if not f or not f.filename:
        flash("ファイルが選択されていません。", "error")
        return redirect(url_for("project.info", project_id=project_id))

    notes        = (request.form.get("notes") or "").strip()
    category     = (request.form.get("category") or "document").strip()
    info_item_id = (request.form.get("info_item_id") or "").strip() or None
    redirect_to  = (request.form.get("redirect_to") or "info").strip()

    file_bytes = f.read()
    mime_type  = f.mimetype or "application/octet-stream"
    file_bytes, up_filename, mime_type = _maybe_convert_to_webp(
        file_bytes, f.filename, mime_type
    )
    size_bytes = len(file_bytes)

    # Drive へアップロード
    try:
        from sync.gdrive import upload_project_file_bytes
        result = upload_project_file_bytes(
            project_name=project["name"],
            file_bytes=file_bytes,
            filename=up_filename,
            mime_type=mime_type,
            subfolder="info",
        )
    except Exception as e:
        result = {"file_id": "", "url": "", "name": f.filename, "error": str(e)}

    if not result.get("file_id"):
        err = result.get("error", "Drive 未設定または接続失敗")
        flash(f"Drive アップロード失敗: {err}", "error")
        return redirect(url_for("project.info", project_id=project_id))

    insert_project_attachment(
        project_id=project_id,
        filename=up_filename,
        drive_file_id=result["file_id"],
        drive_url=result["url"],
        mime_type=mime_type,
        size_bytes=size_bytes,
        notes=notes,
        info_item_id=info_item_id,
        category=category,
    )
    flash(f"「{up_filename}」を Drive にアップロードしました。", "success")
    if redirect_to == "edit" and info_item_id:
        return redirect(url_for("project.info_item_edit",
                                project_id=project_id, item_id=info_item_id))
    return redirect(url_for("project.info", project_id=project_id))


@project_bp.route("/<int:project_id>/info/attachments/<att_id>/delete", methods=["POST"], strict_slashes=False)
def info_attachment_delete(project_id, att_id):
    att = get_project_attachment(att_id)
    if att and att.get("drive_file_id"):
        try:
            from sync.gdrive import delete_drive_file
            delete_drive_file(att["drive_file_id"])
        except Exception:
            pass  # Drive 側削除失敗してもDB側は消す
    delete_project_attachment(att_id)
    flash("添付ファイルを削除しました。", "success")
    redirect_item_id = request.form.get("info_item_id")
    if redirect_item_id:
        return redirect(url_for("project.info_item_edit",
                                project_id=project_id, item_id=redirect_item_id))
    redirect_staff_id = request.form.get("staff_id")
    if redirect_staff_id:
        return redirect(url_for("project.staff_edit",
                                project_id=project_id, staff_id=redirect_staff_id))
    return redirect(url_for("project.info", project_id=project_id))


# ─────────────────────────────────────────────────────────────────────────────
# スタッフ管理 (Phase 4)
# ─────────────────────────────────────────────────────────────────────────────

def _staff_form_to_kwargs(form):
    """request.form からスタッフフィールド dict を取り出す。"""
    keys = (
        "name_kana", "position", "employment_type", "status",
        "whatsapp", "email", "phone", "address",
        "birthday", "hire_date", "termination_date",
        "working_hours", "salary", "bank_info",
        "emergency_contact", "memo",
    )
    out = {}
    for k in keys:
        v = (form.get(k) or "").strip()
        # 日付系で空文字は None にしておく
        if k in ("birthday", "hire_date", "termination_date") and not v:
            v = None
        out[k] = v
    out["sort_order"] = int(form.get("sort_order") or 0)
    if not out.get("status"):
        out["status"] = "active"
    if not out.get("employment_type"):
        out["employment_type"] = "seishain"
    return out


@project_bp.route("/<int:project_id>/staff", methods=["GET"], strict_slashes=False)
def staff_list(project_id):
    project = get_project_by_id(project_id)
    if not project:
        flash("プロジェクトが見つかりません。", "error")
        return redirect(url_for("project.list_projects"))
    staff = get_staff_by_project(project_id)
    counts = count_staff_by_status(project_id)
    # 雇用形態 key→label の dict
    emp_labels = {k: v for k, v in STAFF_EMPLOYMENT_TYPES}
    return render_template(
        "project/staff.html",
        project=project,
        staff=staff,
        statuses=STAFF_STATUSES,
        emp_labels=emp_labels,
        counts=counts,
        today=date.today().isoformat(),
    )


@project_bp.route("/<int:project_id>/staff/new", methods=["GET", "POST"], strict_slashes=False)
def staff_new(project_id):
    project = get_project_by_id(project_id)
    if not project:
        flash("プロジェクトが見つかりません。", "error")
        return redirect(url_for("project.list_projects"))
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("氏名は必須です。", "error")
            return redirect(url_for("project.staff_new", project_id=project_id))
        kwargs = _staff_form_to_kwargs(request.form)
        sid = insert_staff(project_id=project_id, name=name, **kwargs)
        flash(f"スタッフ「{name}」を追加しました。", "success")
        return redirect(url_for("project.staff_edit",
                                project_id=project_id, staff_id=sid))
    return render_template(
        "project/staff_form.html",
        project=project,
        staff=None,
        employment_types=STAFF_EMPLOYMENT_TYPES,
        statuses=STAFF_STATUSES,
        field_labels=STAFF_FIELD_LABELS,
        staff_attachments=[],
    )


@project_bp.route("/<int:project_id>/staff/<staff_id>/edit", methods=["GET", "POST"], strict_slashes=False)
def staff_edit(project_id, staff_id):
    project = get_project_by_id(project_id)
    member = get_staff_by_id(staff_id)
    if not project or not member:
        flash("スタッフが見つかりません。", "error")
        return redirect(url_for("project.staff_list", project_id=project_id))
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        if not name:
            flash("氏名は必須です。", "error")
            return redirect(url_for("project.staff_edit",
                                    project_id=project_id, staff_id=staff_id))
        kwargs = _staff_form_to_kwargs(request.form)
        update_staff(staff_id=staff_id, name=name, **kwargs)
        flash("スタッフ情報を更新しました。", "success")
        return redirect(url_for("project.staff_list", project_id=project_id))

    # 関連添付（写真・契約書など）
    all_atts = get_project_attachments(project_id)
    staff_atts = [a for a in all_atts if a.get("staff_id") == staff_id]
    return render_template(
        "project/staff_form.html",
        project=project,
        staff=member,
        employment_types=STAFF_EMPLOYMENT_TYPES,
        statuses=STAFF_STATUSES,
        field_labels=STAFF_FIELD_LABELS,
        staff_attachments=staff_atts,
    )


@project_bp.route("/<int:project_id>/staff/<staff_id>/delete", methods=["POST"], strict_slashes=False)
def staff_delete(project_id, staff_id):
    delete_staff(staff_id)
    flash("スタッフを削除しました。", "success")
    return redirect(url_for("project.staff_list", project_id=project_id))


@project_bp.route("/<int:project_id>/staff/<staff_id>/status", methods=["POST"], strict_slashes=False)
def staff_set_status(project_id, staff_id):
    """一覧画面でステータスをワンクリック変更。"""
    new_status = (request.form.get("status") or "active").strip()
    valid = {s for s, _, _ in STAFF_STATUSES}
    if new_status not in valid:
        new_status = "active"
    update_staff(staff_id=staff_id, status=new_status)
    return redirect(url_for("project.staff_list", project_id=project_id))


# ─────────────────────────────────────────────────────────────────────────────
# URL 一覧 (Aggregated)
# ─────────────────────────────────────────────────────────────────────────────

@project_bp.route("/urls", methods=["GET"], strict_slashes=False)
def url_list():
    """全プロジェクトの URL カテゴリ項目を集約して表示する。"""
    projects = get_all_projects(include_archived=False)
    all_urls = []
    for p in projects:
        items = get_project_info_items(p["id"], category="url")
        if items:
            all_urls.append({
                "project": p,
                "items": items
            })
    return render_template("project/url_list.html", all_urls=all_urls, page="urls")


# ─── スタッフに添付（Drive） ─────────────────────────────────────────────
@project_bp.route("/<int:project_id>/staff/<staff_id>/attachments/upload",
                  methods=["POST"], strict_slashes=False)
def staff_attachment_upload(project_id, staff_id):
    project = get_project_by_id(project_id)
    member = get_staff_by_id(staff_id)
    if not project or not member:
        flash("スタッフが見つかりません。", "error")
        return redirect(url_for("project.staff_list", project_id=project_id))

    f = request.files.get("file")
    if not f or not f.filename:
        flash("ファイルが選択されていません。", "error")
        return redirect(url_for("project.staff_edit",
                                project_id=project_id, staff_id=staff_id))

    notes      = (request.form.get("notes") or "").strip()
    category   = (request.form.get("category") or "document").strip()
    file_bytes = f.read()
    mime_type  = f.mimetype or "application/octet-stream"
    file_bytes, up_filename, mime_type = _maybe_convert_to_webp(
        file_bytes, f.filename, mime_type
    )
    size_bytes = len(file_bytes)

    try:
        from sync.gdrive import upload_project_file_bytes
        result = upload_project_file_bytes(
            project_name=project["name"],
            file_bytes=file_bytes,
            filename=up_filename,
            mime_type=mime_type,
            subfolder="staff",
        )
    except Exception as e:
        result = {"file_id": "", "url": "", "name": f.filename, "error": str(e)}

    if not result.get("file_id"):
        err = result.get("error", "Drive 未設定または接続失敗")
        flash(f"Drive アップロード失敗: {err}", "error")
        return redirect(url_for("project.staff_edit",
                                project_id=project_id, staff_id=staff_id))

    att_id = insert_project_attachment(
        project_id=project_id,
        filename=up_filename,
        drive_file_id=result["file_id"],
        drive_url=result["url"],
        mime_type=mime_type,
        size_bytes=size_bytes,
        notes=notes,
        category=category,
    )
    # staff_id を別途更新（insert_project_attachment は info_item_id しか受けない既存仕様のため）
    from core.database import transaction as _tx
    with _tx() as conn:
        conn.execute(
            "UPDATE project_attachments SET staff_id=? WHERE id=?",
            (staff_id, att_id),
        )

    # 写真カテゴリの場合は photo_url にも反映
    if category == "photo" and result.get("url"):
        update_staff(staff_id=staff_id, photo_url=result["url"])

    flash(f"「{up_filename}」を Drive にアップロードしました。", "success")
    return redirect(url_for("project.staff_edit",
                            project_id=project_id, staff_id=staff_id))

# ─────────────────────────────────────────────────────────────────────────────
# 取引相手別管理 (枝分かれ)
# ─────────────────────────────────────────────────────────────────────────────

@project_bp.route("/<int:project_id>/partners", methods=["GET"])
def partners(project_id):
    project = get_project_by_id(project_id)
    if not project:
        flash("プロジェクトが見つかりません。", "error")
        return redirect(url_for("project.list_projects"))
    
    # このプロジェクトに紐付く子ワークスペースを抽出
    all_ws = load_workspaces()
    linked_partners = [ws for ws in all_ws if ws.get("parent_id") == f"db_project:{project_id}"]
    
    return render_template("project/partners.html", 
                           project=project, 
                           partners=linked_partners)


@project_bp.route("/<int:project_id>/partners/add", methods=["POST"])
def partners_add(project_id):
    project = get_project_by_id(project_id)
    if not project:
        flash("プロジェクトが見つかりません。", "error")
        return redirect(url_for("project.list_projects"))
    
    name = request.form.get("name", "").strip()
    emoji = request.form.get("emoji", "").strip() or "🏢"
    color = request.form.get("color", "#3b82f6")
    
    if not name:
        flash("名前は必須です。", "error")
        return redirect(url_for("project.partners", project_id=project_id))
    
    create_partner_workspace(name, emoji, color, project_id)
    flash(f"取引相手「{name}」の経理空間を作成しました。", "success")
    return redirect(url_for("project.partners", project_id=project_id))
