"""
shuki.link/project — Flask アプリケーション本体。

ブループリント構成:
  - project_bp (project_app.py)  →  /          (プロジェクト管理が本体)
  - web (web_app.py)              →  /keiri     (経理は内部で /keiri 名前空間)

データベースは /home/ordp5944/keiri_data/kakeibo.db を共有。
"""

import os
import logging
from pathlib import Path

from flask import Flask, redirect, url_for, session

# ── ロギング ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ── DB 初期化 ────────────────────────────────────────────────
from config import DB_PATH
from core.database import init_db

try:
    init_db(DB_PATH)
    logger.info(f"DB initialized at {DB_PATH}")
except Exception as e:
    logger.error(f"DB init failed: {e}")

# ── Flask アプリ ────────────────────────────────────────────
flask_app = Flask(__name__)
flask_app.secret_key = os.getenv("SECRET_KEY", "project-secret-2026")

# Blueprint 読込み（インポート時にエラーが出ても起動は続行）
try:
    from web_app import web
    # 経理は /keiri プレフィックスで再マウント（既存 web_app の内部ルートは "/" 起点）
    flask_app.register_blueprint(web, url_prefix="/keiri")
    logger.info("registered web blueprint at /keiri")
except Exception as e:
    logger.error(f"failed to register web blueprint: {e}")


# ── /keiri 用の自動プロジェクト選択（ワークスペース選択をバイパス） ──
# 経理アプリのレガシー launcher（projects.json ベース）を不要にする。
# 共有の kakeibo.db を常に使うために projects.json をシードし、
# session に project_id を自動セットする。
import json as _json
from flask import request, session
from config import PROJECTS_FILE, DB_PATH, COMPANY_NAME


def _load_projects_list():
    """projects.json を読み込んで list を返す（壊れていれば空 list）。"""
    try:
        if PROJECTS_FILE.exists():
            with open(PROJECTS_FILE, "r", encoding="utf-8") as f:
                data = _json.load(f)
            if isinstance(data, list):
                return data
    except Exception as e:
        logger.warning(f"_load_projects_list: {e}")
    return []


DEFAULT_WORKSPACE_NAME  = "🇮🇩BALI 🇯🇵JAPAN 🌎️DREAM"
DEFAULT_WORKSPACE_EMOJI = ""   # 名前自体に絵文字を含むので別途絵文字なし

def _ensure_kakeibo_workspace():
    """DBの projects テーブルにある全プロジェクトを projects.json に同期し、
    すべて「マスタープロジェクト」としてランチャーに表示されるようにする。"""
    try:
        from core.projects import sync_master_projects
        sync_master_projects()
        logger.info(f"synced projects to {PROJECTS_FILE}")
    except Exception as e:
        logger.warning(f"_ensure_kakeibo_workspace: {e}")


# 起動時に 1 度実行
_ensure_kakeibo_workspace()


@flask_app.before_request
def _auto_select_kakeibo_workspace():
    """ログイン済みで /keiri/* にアクセスした場合、ワークスペースを自動選択。
    既存 /keiri のデータを共有しているので、projects.json にある先頭の
    プロジェクトを自動的に選ぶ（launcher 画面をスキップ）。
    """
    if not request.path.startswith("/keiri/"):
        return
    if not session.get("logged_in"):
        return

    projects = _load_projects_list()
    if not projects:
        return  # データが無いなら触らない（launcher が出るが、それは正しい挙動）

    pid = session.get("project_id")
    valid = pid and any(p.get("id") == pid for p in projects)
    if not valid:
        # 先頭のプロジェクトを自動選択（古い無効 ID も上書き）
        session["project_id"] = projects[0].get("id")
        session.modified = True

    # /keiri/ ちょうどへのアクセスは web.dashboard が無条件で
    # launcher にリダイレクトしてしまうので、/keiri/dashboard に
    # 直接飛ばす（launcher 表示をバイパス）。
    if request.path in ("/keiri", "/keiri/"):
        from flask import redirect as _redirect, url_for as _url_for
        return _redirect(_url_for("web.job_dashboard"))

try:
    from project_app import project_bp
    # プロジェクト管理は本体としてルートに配置（既存の url_prefix='/keiri/project' を上書き）
    flask_app.register_blueprint(project_bp, url_prefix="")
    logger.info("registered project blueprint at /")
except Exception as e:
    logger.error(f"failed to register project blueprint: {e}")


# ── ヘルスチェック ─────────────────────────────────────────
@flask_app.route("/health")
def health():
    return "ok", 200

@flask_app.route("/_debug_projects")
def _debug_projects():
    """一時的: projects.json を複数の候補場所から探す。"""
    import json as _j
    from pathlib import Path as _P
    from flask import jsonify
    candidates = [
        PROJECTS_FILE,
        _P("/home/ordp5944/public_html/shuki.link/keiri/projects.json"),
        _P("/home/ordp5944/public_html/shuki.link/keiri/data/projects.json"),
        _P("/home/ordp5944/keiri_data/projects.json"),
    ]
    found = {}
    for c in candidates:
        try:
            if c.exists():
                with open(c, "r", encoding="utf-8") as f:
                    found[str(c)] = _j.load(f)
            else:
                found[str(c)] = "(not found)"
        except Exception as e:
            found[str(c)] = f"error: {e}"
    # also list keiri app root and data subdir
    listings = {}
    for d in [
        _P("/home/ordp5944/public_html/shuki.link/keiri"),
        _P("/home/ordp5944/public_html/shuki.link/keiri/data"),
    ]:
        try:
            listings[str(d)] = sorted([p.name for p in d.iterdir()])
        except Exception as e:
            listings[str(d)] = f"error: {e}"
    # also read OLD keiri's .env and config.py
    extra = {}
    for f in [
        _P("/home/ordp5944/public_html/shuki.link/keiri/.env"),
        _P("/home/ordp5944/public_html/shuki.link/keiri/config.py"),
    ]:
        try:
            extra[str(f)] = f.read_text(encoding="utf-8")[:2000]
        except Exception as e:
            extra[str(f)] = f"error: {e}"
    # inspect each DB to see which has data
    import sqlite3 as _sql
    db_info = {}
    keiri_data_dir = _P("/home/ordp5944/public_html/shuki.link/keiri/data")
    for db_file in keiri_data_dir.glob("*.db"):
        info = {"size": db_file.stat().st_size}
        try:
            conn = _sql.connect(str(db_file))
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [r[0] for r in cur.fetchall()]
            info["tables"] = tables
            for t in ("expenses", "revenue", "tasks", "contacts"):
                if t in tables:
                    cur.execute(f"SELECT COUNT(*) FROM {t}")
                    info[f"{t}_count"] = cur.fetchone()[0]
            conn.close()
        except Exception as e:
            info["error"] = str(e)
        db_info[db_file.name] = info
    return jsonify({
        "PROJECTS_FILE_configured": str(PROJECTS_FILE),
        "DB_PATH":                  str(DB_PATH),
        "candidates":               found,
        "listings":                 listings,
        "old_keiri_files":          extra,
        "db_info":                  db_info,
        "session_project_id":       session.get("project_id"),
    })

# 注: ルート "/" は project_bp.list_projects がハンドル。
#     未ログイン時は project_bp.before_request で web.login にリダイレクト。


# Passenger が要求する WSGI callable
application = flask_app


# ── ローカル開発用 ─────────────────────────────────────────
if __name__ == "__main__":
    flask_app.run(host="0.0.0.0", port=8001, debug=True)
