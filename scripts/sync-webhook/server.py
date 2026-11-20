#!/usr/bin/env python3
"""3rde.online sync webhook — turns the admin panel's "مزامنة الآن" button
into a real, immediate full update.

Flow:
  panel -> POST /sync {token, tabs}   (tabs = Apps Script export payload)
  -> writes data/raw/*.json in a repo clone
  -> runs scripts/sync.py repeatedly until no new images remain
  -> git commit + push (SSH deploy key)
  -> POSTs the Coolify deploy webhook of the main site
  -> panel polls GET /sync-status?job=<id> for progress

Env vars (set in Coolify):
  SYNC_TOKEN              shared secret the admin panel sends
  REPO_URL                git URL of the site repo (SSH form for push)
  REPO_BRANCH             default: main
  DEPLOY_KEY              SSH private key (deploy key, write access)
  COOLIFY_DEPLOY_WEBHOOK  deploy-webhook URL of the main 3rode-online app
  COOLIFY_API_TOKEN       Coolify API token (Bearer auth for the webhook —
                          /api/v1/* returns 401 without it, even with API
                          access enabled; fix 2026-11-20)
  PORT                    default: 8000
  WORKDIR                 default: /data/repo
"""
import hashlib
import hmac
import json
import os
import re
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib import request as urlrequest
from urllib.error import URLError

PORT = int(os.environ.get("PORT", "8000"))
WORKDIR = os.environ.get("WORKDIR", "/data/repo")
REPO_URL = os.environ.get(
    "REPO_URL", "git@github.com:ahmedeldaby2033-hub/3rode-online.git")
REPO_BRANCH = os.environ.get("REPO_BRANCH", "main")
SYNC_TOKEN = os.environ.get("SYNC_TOKEN", "")
DEPLOY_KEY = os.environ.get("DEPLOY_KEY", "")
DEPLOY_KEY_FILE = os.environ.get("DEPLOY_KEY_FILE",
                                 "/run/secrets/deploy-key")
DEPLOY_WEBHOOK = os.environ.get("COOLIFY_DEPLOY_WEBHOOK", "")
COOLIFY_API_TOKEN = os.environ.get("COOLIFY_API_TOKEN", "")

TAB_FILES = {
    "الورقة1": "sheet1.json",
    "ملخص": "summary.json",
    "سجل الأسعار": "price_history.json",
    "المكرر فقط": "duplicates.json",
    "الكوبونات": "coupons.json",
    "الأدلة": "guides.json",
    "الأخبار": "news.json",
}
LAYOUTS = ("classic", "rows", "deals", "store", "compact", "luxury",
           "forest", "royal", "sunset", "minimal", "showcase",
           "fullrows", "quick")

JOBS = {}


def log(job, step):
    job["steps"].append(step)
    print(f"[job {job['id'][:8]}] {step}", flush=True)


def run(cmd, cwd=None, env=None, timeout=600):
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True,
                          text=True, timeout=timeout)


def git_env():
    env = dict(os.environ)
    key_path = "/tmp/sync-deploy-key"
    # Prefer a key file mounted from the host (exact bytes, no copy/paste);
    # fall back to the DEPLOY_KEY env var.
    key_data = None
    if os.path.isfile(DEPLOY_KEY_FILE):
        with open(DEPLOY_KEY_FILE, encoding="utf-8") as f:
            key_data = f.read()
    elif DEPLOY_KEY:
        key_data = DEPLOY_KEY
    if key_data:
        with open(key_path, "w", encoding="utf-8") as f:
            f.write(key_data if key_data.endswith("\n") else key_data + "\n")
        os.chmod(key_path, 0o600)
        env["GIT_SSH_COMMAND"] = (
            f"ssh -i {key_path} -o StrictHostKeyChecking=accept-new "
            "-o IdentitiesOnly=yes")
    return env


def ensure_repo(job):
    """Clone the repo on first run, pull latest afterwards."""
    env = git_env()
    if not os.path.isdir(os.path.join(WORKDIR, ".git")):
        os.makedirs(WORKDIR, exist_ok=True)
        log(job, "استنساخ المستودع لأول مرة…")
        r = run(["git", "clone", "--branch", REPO_BRANCH, REPO_URL, WORKDIR],
                env=env, timeout=300)
        if r.returncode != 0:
            raise RuntimeError("git clone failed: " + r.stderr[-500:])
    else:
        log(job, "سحب آخر نسخة من GitHub…")
        r = run(["git", "pull", "--ff-only", "origin", REPO_BRANCH],
                cwd=WORKDIR, env=env, timeout=300)
        if r.returncode != 0:
            raise RuntimeError("git pull failed: " + r.stderr[-500:])
    run(["git", "config", "user.name", "3rde-sync"], cwd=WORKDIR)
    run(["git", "config", "user.email", "3rdeonline@gmail.com"], cwd=WORKDIR)
    # Pushes must go over SSH when a deploy key is configured.
    if DEPLOY_KEY:
        run(["git", "remote", "set-url", "origin", REPO_URL], cwd=WORKDIR)


def write_export(job, tabs, settings):
    raw_dir = os.path.join(WORKDIR, "data", "raw")
    os.makedirs(raw_dir, exist_ok=True)
    written = []
    for tab, fname in TAB_FILES.items():
        values = (tabs or {}).get(tab)
        if values is None:
            continue
        with open(os.path.join(raw_dir, fname), "w", encoding="utf-8") as f:
            json.dump({"values": values}, f, ensure_ascii=False)
        written.append(fname)
    if "الورقة1" not in (tabs or {}):
        raise RuntimeError("بيانات الشيت ناقصة: تبويب «الورقة1» غير موجود")
    # Adopt the homepage layout chosen in the admin panel.
    hl = str(((settings or {}).get("home_layout", "") or "").strip().lower())
    if hl in LAYOUTS:
        sp = os.path.join(WORKDIR, "settings.json")
        cur = json.load(open(sp, encoding="utf-8"))
        if cur.get("home_layout", "classic") != hl:
            cur["home_layout"] = hl
            json.dump(cur, open(sp, "w", encoding="utf-8"),
                      ensure_ascii=False, indent=2)
            log(job, f"تخطيط الصفحة الرئيسية: {hl}")
    # Adopt the brand order chosen in the admin panel.
    _bo_raw = str(((settings or {}).get("brand_order_json", "") or "").strip())
    if _bo_raw:
        try:
            _bo = json.loads(_bo_raw)
            if isinstance(_bo, list) and all(isinstance(b, str) for b in _bo):
                sp = os.path.join(WORKDIR, "settings.json")
                cur = json.load(open(sp, encoding="utf-8"))
                if cur.get("brand_order") != _bo:
                    cur["brand_order"] = _bo
                    json.dump(cur, open(sp, "w", encoding="utf-8"),
                              ensure_ascii=False, indent=2)
                    log(job, f"ترتيب الماركات: {len(_bo)} ماركة")
        except Exception:
            pass
    log(job, f"كُتبت بيانات الشيت ({len(written)} تبويبات)")
    return written


def run_sync_loop(job):
    """Run sync.py until a run downloads no new images (max 8 runs)."""
    total_new = 0
    total_failed = 0
    models = offers = brands = 0
    for i in range(1, 9):
        log(job, f"تشغيل المزامنة ({i}/8)…")
        r = run(["python3", "scripts/sync.py"], cwd=WORKDIR, timeout=900)
        out = (r.stdout or "") + (r.stderr or "")
        m = re.search(r"\[download-images\] (\d+) new, (\d+) failed", out)
        new, failed = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
        total_new += new
        total_failed = failed
        m2 = re.search(r"models: (\d+)\s+offers: (\d+)\s+brands: (\d+)", out)
        if m2:
            models, offers, brands = (int(m2.group(1)), int(m2.group(2)),
                                      int(m2.group(3)))
        log(job, f"المزامنة {i}: {new} صورة جديدة، {failed} فاشلة")
        if r.returncode != 0:
            raise RuntimeError("sync.py failed: " + out[-800:])
        if new == 0:
            break
    return {"models": models, "offers": offers, "brands": brands,
            "images_downloaded": total_new, "images_failed": total_failed}


def push_changes(job):
    env = git_env()
    run(["git", "add", "site", "data"], cwd=WORKDIR, env=env)
    # Logs change every run — never commit them.
    run(["git", "reset", "-q", "--", "data/sync-log.json",
         "data/sync-cron.log"], cwd=WORKDIR, env=env)
    if run(["git", "diff", "--cached", "--quiet"], cwd=WORKDIR).returncode == 0:
        log(job, "لا تغييرات جديدة — لا حاجة للنشر")
        return False
    msg = "sync: " + time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()) \
        + " admin sync-now"
    r = run(["git", "commit", "-m", msg], cwd=WORKDIR, env=env)
    if r.returncode != 0:
        raise RuntimeError("git commit failed: " + r.stderr[-500:])
    log(job, "تم الحفظ محلياً — جارٍ الرفع إلى GitHub…")
    r = run(["git", "push", "origin", REPO_BRANCH], cwd=WORKDIR, env=env,
            timeout=300)
    if r.returncode != 0:
        raise RuntimeError("git push failed: " + r.stderr[-500:])
    log(job, "تم الرفع إلى GitHub")
    return True


def trigger_deploy(job):
    if not DEPLOY_WEBHOOK:
        log(job, "لا يوجد رابط نشر Coolify — تخطّي إعادة النشر")
        return False
    # Coolify /api/v1/* endpoints return 401 without auth even when API
    # access is enabled; a Bearer API token fixes it (2026-11-20).
    headers = {}
    if COOLIFY_API_TOKEN:
        headers["Authorization"] = "Bearer " + COOLIFY_API_TOKEN
    try:
        req = urlrequest.Request(DEPLOY_WEBHOOK, data=b"", method="POST",
                                 headers=headers)
        with urlrequest.urlopen(req, timeout=30) as resp:
            ok = 200 <= resp.status < 300
    except URLError as e:
        raise RuntimeError("deploy webhook failed: " + str(e))
    log(job, "تم طلب إعادة النشر من Coolify" if ok
        else "تعذر طلب إعادة النشر")
    return ok


def do_sync(job, payload):
    try:
        ensure_repo(job)
        write_export(job, payload.get("tabs"), payload.get("settings"))
        result = run_sync_loop(job)
        result["pushed"] = push_changes(job)
        result["deployed"] = (trigger_deploy(job)
                              if result["pushed"] else False)
        job["status"] = "done"
        job["result"] = result
        log(job, "اكتمل التحديث ✓")
    except Exception as e:  # noqa: BLE001 - report to the panel
        job["status"] = "error"
        job["error"] = str(e)
        log(job, "خطأ: " + str(e))


class Handler(BaseHTTPRequestHandler):
    def _json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        # The admin panel runs on another origin (3rde.online/adamwnor),
        # so the webhook must allow cross-origin calls from it.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return {}

    def do_GET(self):
        if self.path == "/health":
            return self._json(200, {"ok": True})
        if self.path.startswith("/sync-status"):
            job_id = self.path.split("job=", 1)[-1].split("&")[0]
            job = JOBS.get(job_id)
            if not job:
                return self._json(404, {"ok": False, "error": "job not found"})
            return self._json(200, {"ok": True, "status": job["status"],
                                    "steps": job["steps"],
                                    "result": job.get("result"),
                                    "error": job.get("error")})
        return self._json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if self.path != "/sync":
            return self._json(404, {"ok": False, "error": "not found"})
        payload = self._read_json()
        token = str(payload.get("token") or "")
        if not SYNC_TOKEN or not hmac.compare_digest(
                token, SYNC_TOKEN):
            return self._json(401, {"ok": False, "error": "unauthorized"})
        if not isinstance(payload.get("tabs"), dict):
            return self._json(400, {"ok": False,
                                    "error": "missing tabs payload"})
        job = {"id": uuid.uuid4().hex, "status": "running", "steps": [],
               "result": None, "error": None}
        JOBS[job["id"]] = job
        threading.Thread(target=do_sync, args=(job, payload),
                         daemon=True).start()
        return self._json(200, {"ok": True, "job": job["id"]})

    def log_message(self, *args):  # keep stdout for job logs only
        pass


if __name__ == "__main__":
    if not SYNC_TOKEN:
        print("WARNING: SYNC_TOKEN is not set — /sync will reject everything")
    print(f"sync webhook listening on :{PORT} (repo {REPO_URL})", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
