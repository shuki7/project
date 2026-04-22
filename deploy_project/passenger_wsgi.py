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

try:
    from main import application as _flask_app  # noqa: E402
except Exception:
    import traceback
    def application(environ, start_response):
        status = "500 Internal Server Error"
        response_headers = [("Content-type", "text/plain; charset=utf-8")]
        start_response(status, response_headers)
        return [traceback.format_exc().encode("utf-8")]
else:
    def application(environ, start_response):
        try:
            # PATH_INFO 調整
            path = environ.get("PATH_INFO", "") or ""
            if path.startswith("/project"):
                environ["PATH_INFO"] = path[len("/project"):] or "/"
            environ["SCRIPT_NAME"] = "/project"
            
            # Flask app を実行し、レスポンスを取得
            result = _flask_app(environ, start_response)
            # イテレータをリスト化して、レンダリング時のエラーもここで捕まえる
            return list(result)
            
        except Exception:
            import traceback
            status = "500 Internal Server Error"
            response_headers = [("Content-type", "text/plain; charset=utf-8")]
            start_response(status, response_headers)
            return [traceback.format_exc().encode("utf-8")]
