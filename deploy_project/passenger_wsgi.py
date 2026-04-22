import sys
import os
import traceback

# 初期化時のエラーをキャッチ
init_error = None
try:
    _here = os.path.dirname(os.path.abspath(__file__))
    if _here not in sys.path:
        sys.path.insert(0, _here)
        
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    os.environ.setdefault("PYTHONUTF8", "1")

    from main import application as _flask_app
except BaseException:
    init_error = traceback.format_exc()

def application(environ, start_response):
    if init_error:
        # 初期化エラーがあればここで返す (まだ start_response は呼ばれていない)
        start_response("200 OK", [("Content-type", "text/plain; charset=utf-8")])
        msg = f"SSP Project - Initialization Error\nPython: {sys.version}\n\n{init_error}"
        return [msg.encode("utf-8")]

    try:
        path = environ.get("PATH_INFO", "") or ""
        if path.startswith("/project"):
            environ["PATH_INFO"] = path[len("/project"):] or "/"
        environ["SCRIPT_NAME"] = "/project"
        
        # Flask に処理を委譲。Flask 内でのエラーは Flask 自身が処理するはず
        return _flask_app(environ, start_response)
        
    except BaseException:
        # リクエスト処理中の例外（Flask が処理しきれなかった非常事態）
        # すでに start_response が呼ばれている可能性があるので、安全な方法をとる
        err = traceback.format_exc()
        try:
            start_response("200 OK", [("Content-type", "text/plain; charset=utf-8")])
        except BaseException:
            pass # すでに呼ばれていた場合は無視
        
        msg = f"SSP Project - Runtime Error\nPython: {sys.version}\n\n{err}"
        return [msg.encode("utf-8")]
