"""
cPanel Passenger WSGI entry point for shuki.link/project

PassengerBaseURI=/project により Passenger は PATH_INFO から /project を剥がす。
内部では:
  - project Blueprint   →  / (ルート)
  - web Blueprint       →  /keiri (経理は内部で /keiri プレフィックス)
"""

import sys
import os
from pathlib import Path

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")

_here = Path(__file__).parent
sys.path.insert(0, str(_here))

# モジュールキャッシュをクリアして強制リロード
for m in list(sys.modules.keys()):
    if any(p in m for p in ["main", "core", "sync", "web_app", "project_app",
                            "translations", "config", "reports", "bot"]):
        del sys.modules[m]

from main import application as _flask_app  # noqa: E402


def application(environ, start_response):
    """PassengerBaseURI=/project を扱う:
    - PATH_INFO に /project を復元（Flask Blueprint と整合）
    - SCRIPT_NAME は空にして url_for() の二重プレフィックス回避
    ※ 実際には Blueprint 側に /project を含めずに、SCRIPT_NAME=/project を立てる方が
      自然なので、こちらの方式を採用：PATH_INFO はそのまま、SCRIPT_NAME に /project を立てる。
    """
    # cPanel/LiteSpeed が PATH_INFO に /project を含めて渡してくる場合と
    # 含めずに渡してくる場合の両方に対応する。
    path = environ.get("PATH_INFO", "") or ""
    if path.startswith("/project"):
        # /project を剥がす（SCRIPT_NAME に立てる）
        environ["PATH_INFO"] = path[len("/project"):] or "/"
    environ["SCRIPT_NAME"] = "/project"
    return _flask_app(environ, start_response)
