import sys
import os
from flask import Flask

application = Flask(__name__)
@application.route("/")
def index():
    return "Flask is working!"

# ── 開発用 ─────────────────────────────────────────
if __name__ == "__main__":
    application.run(host="0.0.0.0", port=8001, debug=True)
