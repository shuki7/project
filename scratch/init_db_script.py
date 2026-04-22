import sys
import os
from pathlib import Path

# プロジェクトルート（scratchの親）をパスに追加
root_dir = Path(__file__).parent.parent
sys.path.append(str(root_dir))

from core.database import init_db
from config import DB_PATH

print(f"Initializing database at: {DB_PATH}")
init_db(DB_PATH)
print("Initialization complete.")
