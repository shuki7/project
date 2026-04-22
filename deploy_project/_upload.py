"""FTPS uploader for /project deployment."""
from ftplib import FTP_TLS
from pathlib import Path
import ssl
import sys

HOST = "ftp.order-shipwreckbali.com"
USER = "project@shuki.link"
PASS = "Enrichno1@"

LOCAL_ROOT = Path(__file__).parent.parent  # /Users/shuki/Downloads/GitHub開発/SSP経理

# (local relative path → remote path under chroot "/")
FILES = [
    # entry points (from deploy_project/)
    ("deploy_project/passenger_wsgi.py", "passenger_wsgi.py"),
    ("deploy_project/main.py",            "main.py"),
    ("deploy_project/requirements.txt",   "requirements.txt"),
    ("deploy_project/.env",                ".env"),
    ("deploy_project/service-account.json", "service-account.json"),
    # core flask app modules
    ("project_app.py",   "project_app.py"),
    ("web_app.py",       "web_app.py"),
    ("config.py",        "config.py"),
    ("translations.py",  "translations.py"),
    # core/
    ("core/__init__.py", "core/__init__.py"),
    ("core/database.py", "core/database.py"),
    ("core/projects.py", "core/projects.py"),
    # sync/
    ("sync/__init__.py", "sync/__init__.py"),
    ("sync/gdrive.py",   "sync/gdrive.py"),
    # bot/ (web_app imports bot.ocr)
    ("bot/__init__.py",  "bot/__init__.py"),
    ("bot/ocr.py",       "bot/ocr.py"),
    # reports/
    ("reports/__init__.py",   "reports/__init__.py"),
    ("reports/pdf_export.py", "reports/pdf_export.py"),
    ("reports/generator.py",  "reports/generator.py"),
]

# Templates: walk the entire templates/ directory
def collect_templates():
    out = []
    tdir = LOCAL_ROOT / "templates"
    for p in tdir.rglob("*.html"):
        rel = p.relative_to(LOCAL_ROOT)
        out.append((str(rel), str(rel).replace("\\", "/")))
    return out


def ensure_dir(ftp: FTP_TLS, remote_dir: str):
    """Create nested directories on FTP if missing."""
    parts = [p for p in remote_dir.split("/") if p]
    cur = ""
    for part in parts:
        cur = (cur + "/" + part) if cur else part
        try:
            ftp.cwd("/" + cur)
        except Exception:
            try:
                ftp.mkd("/" + cur)
                print(f"  mkdir /{cur}")
            except Exception as e:
                print(f"  mkdir /{cur} failed: {e}")
    ftp.cwd("/")


def upload_file(ftp: FTP_TLS, local: Path, remote: str):
    if not local.exists():
        print(f"  SKIP missing: {local}")
        return False
    # ensure parent dir
    parent = "/".join(remote.split("/")[:-1])
    if parent:
        ensure_dir(ftp, parent)
    with open(local, "rb") as f:
        try:
            ftp.storbinary(f"STOR /{remote}", f)
            print(f"  ✓ {remote}  ({local.stat().st_size} B)")
            return True
        except Exception as e:
            print(f"  ✗ {remote}  -> {e}")
            return False


def main():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    ftp = FTP_TLS(context=ctx)
    ftp.connect(HOST, 21, timeout=30)
    ftp.login(USER, PASS)
    ftp.prot_p()
    print(f"[connected] pwd={ftp.pwd()}")

    files = list(FILES) + collect_templates()
    print(f"[planning] {len(files)} file(s) to upload\n")

    ok = 0
    fail = 0
    for local_rel, remote in files:
        local = LOCAL_ROOT / local_rel
        if upload_file(ftp, local, remote):
            ok += 1
        else:
            fail += 1

    print(f"\n[done] uploaded={ok}  failed={fail}")
    ftp.quit()
    sys.exit(0 if fail == 0 else 1)


if __name__ == "__main__":
    main()
