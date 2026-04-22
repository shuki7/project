import sys
import os
import traceback

def application(environ, start_response):
    try:
        # このファイルがあるディレクトリをパスに追加
        _here = os.path.dirname(os.path.abspath(__file__))
        if _here not in sys.path:
            sys.path.insert(0, _here)
            
        # 文字コード設定
        os.environ.setdefault("PYTHONIOENCODING", "utf-8")
        os.environ.setdefault("PYTHONUTF8", "1")

        # mainモジュールの読み込み
        try:
            from main import application as _flask_app
        except BaseException:
            raise Exception("Failed to import main.py:\n" + traceback.format_exc())

        # PATH_INFO 調整
        path = environ.get("PATH_INFO", "") or ""
        if path.startswith("/project"):
            environ["PATH_INFO"] = path[len("/project"):] or "/"
        environ["SCRIPT_NAME"] = "/project"
        
        # Flask実行
        result = _flask_app(environ, start_response)
        return list(result)

    except BaseException:
        status = "500 Internal Server Error"
        response_headers = [("Content-type", "text/plain; charset=utf-8")]
        start_response(status, response_headers)
        
        # 詳細なエラー情報を出力
        error_info = [
            "SSP Project - Critical Error\n",
            "===========================\n",
            "Python Version: " + sys.version + "\n",
            "Current Path: " + os.getcwd() + "\n",
            "System Path: " + str(sys.path) + "\n",
            "Error Traceback:\n",
            traceback.format_exc()
        ]
        return ["".join(error_info).encode("utf-8")]
