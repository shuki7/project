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
                return _json.load(f)
    except Exception as e:
        logger.error(f"failed to load projects: {e}")
    return []


def _ensure_kakeibo_workspace():
    """/keiri 用のマスターワークスペース（id="1" 固定）がなければ作る。"""
    try:
        from core.projects import sync_master_projects
        sync_master_projects()
        
        from core.database import get_all_projects
        all_projects = get_all_projects()
        if not all_projects:
            logger.warning("No projects found in DB.")
    except Exception as e:
        logger.error(f"failed to ensure kakeibo workspace: {e}")

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

@flask_app.route("/")
def index():
    if not session.get("logged_in"):
        return redirect("/project/keiri/login")
    return redirect("/project/keiri/launcher")


try:
    from project_app import project_bp
    flask_app.register_blueprint(project_bp, url_prefix="")
    logger.info("registered project blueprint at /")
except Exception as e:
    logger.error(f"failed to register project blueprint: {e}")



@flask_app.errorhandler(Exception)
def handle_exception(e):
    # すべての未キャッチエラーを拾って、テキスト形式でブラウザに直接出力する
    import traceback
    err_msg = traceback.format_exc()
    logger.error(f"Unhandled Exception: {err_msg}")
    
    # 意図的に 200 OK を返すことで LiteSpeed の 500 隠蔽をバイパスする
    from flask import Response
    return Response(
        f"FLASK UNHANDLED ERROR:\n{err_msg}",
        mimetype="text/plain",
        status=200
    )

# ── ヘルスチェック ─────────────────────────────────────────
@flask_app.route("/health")
def health():
    return "ok", 200




# 注: ルート "/" は project_bp.list_projects がハンドル。
#     未ログイン時は project_bp.before_request で web.login にリダイレクト。


# Passenger が要求する WSGI callable
application = flask_app


# ── ローカル開発用 ─────────────────────────────────────────
if __name__ == "__main__":
    flask_app.run(host="0.0.0.0", port=8001, debug=True)
