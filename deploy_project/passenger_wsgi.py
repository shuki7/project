import sys
import os

_here = os.path.dirname(os.path.abspath(__file__))
if _here not in sys.path:
    sys.path.insert(0, _here)

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.environ.setdefault("PYTHONUTF8", "1")

from main import application as _flask_app

def application(environ, start_response):
    # LiteSpeedの500エラー画面上書きを防ぐためのラッパー
    def custom_start_response(status, headers, exc_info=None):
        if status.startswith("5"):
            status = "200 OK"  # エラー内容を画面に出すためにあえて200を返す
        return start_response(status, headers, exc_info)

    try:
        path = environ.get("PATH_INFO", "") or ""
        if path.startswith("/project"):
            environ["PATH_INFO"] = path[len("/project"):] or "/"
        environ["SCRIPT_NAME"] = "/project"
        
        return _flask_app(environ, custom_start_response)
    except Exception as e:
        import traceback
        custom_start_response("200 OK", [("Content-type", "text/plain; charset=utf-8")])
        return [f"WSGI Unhandled Error:\n{traceback.format_exc()}".encode("utf-8")]

