import json
import uuid
import sqlite3
from pathlib import Path
from config import PROJECTS_FILE

def load_workspaces():
    if not PROJECTS_FILE.exists():
        return []
    with open(PROJECTS_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return []

def save_workspaces(projects):
    PROJECTS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(PROJECTS_FILE, "w", encoding="utf-8") as f:
        json.dump(projects, f, ensure_ascii=False, indent=4)

def create_partner_workspace(name, emoji, color, parent_db_project_id):
    workspaces = load_workspaces()
    pid = str(uuid.uuid4())[:8]
    db_name = f"kakeibo_{pid}.db"
    
    new_ws = {
        "id": pid,
        "name": name,
        "emoji": emoji,
        "db": db_name,
        "color": color,
        "parent_id": f"db_project:{parent_db_project_id}"
    }
    workspaces.append(new_ws)
    save_workspaces(workspaces)
    
    # DB初期化
    from core.database import get_connection, SCHEMA_SQL
    db_path = PROJECTS_FILE.parent / db_name
    conn = get_connection(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.close()
    
    return pid
def sync_master_projects():
    """DBの projects テーブルにある全プロジェクトを projects.json に同期する。"""
    from core.database import get_all_projects
    db_projects = get_all_projects()
    
    existing = load_workspaces()
    # IDをキーにしたマップを作成
    projects_map = {p["id"]: p for p in existing}
    
    for db_p in db_projects:
        pid = str(db_p["id"])
        projects_map[pid] = {
            "id":    pid,
            "name":  db_p["name"],
            "emoji": db_p.get("emoji") or "📁",
            "db":    "kakeibo.db", # マスターDBを使用
            "color": db_p.get("color") or "#16213e",
        }
    
    save_workspaces(list(projects_map.values()))
