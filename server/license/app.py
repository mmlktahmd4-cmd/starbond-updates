#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Starbond License Server — خدمة تراخيص صغيرة مستقلة (Python بدون مكتبات خارجية + SQLite)

  GET  /api/check?id=<DEVICE>&board=&ver=&name=     الراوتر بيسأل عن ترخيصه (بدون تسجيل دخول)
  GET  /admin                                       لوحة الإدارة (كلمة سر ADMIN_PASSWORD)
  GET  /api/admin/devices                           قائمة الأجهزة
  POST /api/admin/devices/<DEVICE>                  {"action": "activate|extend|suspend|resume|delete|edit", "days": 30, "customer": "...", "note": "..."}

متغيرات البيئة:
  ADMIN_PASSWORD   (إجباري) كلمة سر لوحة الإدارة
  DB_PATH          default /data/licenses.db
  TRIAL_DAYS       default 3   (جهاز جديد بيشتغل كم يوم لحد ما تفعّله)
  PORT             default 8010
"""
import base64, hmac, html, json, os, re, sqlite3, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

DB_PATH = os.environ.get("DB_PATH", "/data/licenses.db")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "")
TRIAL_DAYS = int(os.environ.get("TRIAL_DAYS", "3"))
PORT = int(os.environ.get("PORT", "8010"))
DAY = 86400
ID_RE = re.compile(r"^[0-9A-F]{12}$")
LOCK = threading.Lock()


def db():
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS devices (
            id TEXT PRIMARY KEY, status TEXT NOT NULL, expires INTEGER NOT NULL,
            customer TEXT DEFAULT '', note TEXT DEFAULT '', board TEXT DEFAULT '', version TEXT DEFAULT '',
            hostname TEXT DEFAULT '', last_ip TEXT DEFAULT '', first_seen INTEGER, last_seen INTEGER)""")
        c.execute("""CREATE TABLE IF NOT EXISTS log (
            ts INTEGER, device TEXT, action TEXT, detail TEXT)""")


def norm_id(s):
    s = re.sub(r"[^0-9A-Fa-f]", "", s or "").upper()
    return s if ID_RE.match(s) else None


def effective(row, now):
    """الحالة اللي بتنبعت للراوتر"""
    st = row["status"]
    if st == "suspended":
        return "suspended"
    if row["expires"] <= now:
        return "expired"
    return st  # active | trial


def log(c, dev, action, detail=""):
    c.execute("INSERT INTO log VALUES (?,?,?,?)", (int(time.time()), dev, action, detail[:300]))


MESSAGES = {
    "active": "مرخّص",
    "trial": "فترة تجربة",
    "expired": "انتهى الاشتراك — تواصل مع المزوّد للتجديد",
    "suspended": "الترخيص موقوف — تواصل مع المزوّد",
}


def handle_check(q, ip):
    dev = norm_id(q.get("id", [""])[0])
    if not dev:
        return 400, {"ok": False, "error": "bad id"}
    now = int(time.time())
    clip = lambda k, n: (q.get(k, [""])[0] or "")[:n]
    with LOCK, db() as c:
        row = c.execute("SELECT * FROM devices WHERE id=?", (dev,)).fetchone()
        if row is None:
            exp = now + TRIAL_DAYS * DAY
            c.execute("INSERT INTO devices (id,status,expires,board,version,hostname,last_ip,first_seen,last_seen) VALUES (?,?,?,?,?,?,?,?,?)",
                      (dev, "trial", exp, clip("board", 60), clip("ver", 20), clip("name", 60), ip, now, now))
            log(c, dev, "first_seen", "trial %d days" % TRIAL_DAYS)
            row = c.execute("SELECT * FROM devices WHERE id=?", (dev,)).fetchone()
        else:
            c.execute("UPDATE devices SET board=?,version=?,hostname=?,last_ip=?,last_seen=? WHERE id=?",
                      (clip("board", 60) or row["board"], clip("ver", 20) or row["version"],
                       clip("name", 60) or row["hostname"], ip, now, dev))
        st = effective(row, now)
        return 200, {"ok": True, "id": dev, "status": st, "expires": row["expires"], "now": now,
                     "customer": row["customer"] or "", "message": MESSAGES.get(st, st)}


def handle_admin_action(dev, body):
    dev = norm_id(dev)
    if not dev:
        return 400, {"ok": False, "error": "رقم جهاز غلط"}
    act = body.get("action", "")
    now = int(time.time())
    with LOCK, db() as c:
        row = c.execute("SELECT * FROM devices WHERE id=?", (dev,)).fetchone()
        if row is None:
            if act not in ("activate", "add"):
                return 404, {"ok": False, "error": "الجهاز مش موجود"}
            c.execute("INSERT INTO devices (id,status,expires,first_seen,last_seen) VALUES (?,?,?,?,?)", (dev, "active", now, now, 0))
            row = c.execute("SELECT * FROM devices WHERE id=?", (dev,)).fetchone()
        try:
            days = int(body.get("days") or 0)
        except (TypeError, ValueError):
            return 400, {"ok": False, "error": "عدد الأيام غلط"}
        if days < 0 or days > 3660:
            return 400, {"ok": False, "error": "عدد الأيام غلط"}
        if act in ("activate", "add", "extend"):
            days = days or 30
            base = max(row["expires"], now)   # التمديد بيبلّش من آخر تاريخ إذا لسا ساري
            exp = base + days * DAY
            c.execute("UPDATE devices SET status='active', expires=? WHERE id=?", (exp, dev))
            log(c, dev, act, "+%d days" % days)
        elif act == "set_expiry":
            try:
                exp = int(body.get("expires"))
            except (TypeError, ValueError):
                return 400, {"ok": False, "error": "تاريخ غلط"}
            c.execute("UPDATE devices SET status='active', expires=? WHERE id=?", (exp, dev))
            log(c, dev, act, str(exp))
        elif act == "suspend":
            c.execute("UPDATE devices SET status='suspended' WHERE id=?", (dev,))
            log(c, dev, act)
        elif act == "resume":
            c.execute("UPDATE devices SET status='active' WHERE id=?", (dev,))
            log(c, dev, act)
        elif act == "delete":
            c.execute("DELETE FROM devices WHERE id=?", (dev,))
            log(c, dev, act)
            return 200, {"ok": True}
        elif act != "edit":
            return 400, {"ok": False, "error": "عملية غير معروفة"}
        if "customer" in body:
            c.execute("UPDATE devices SET customer=? WHERE id=?", (str(body["customer"])[:80], dev))
        if "note" in body:
            c.execute("UPDATE devices SET note=? WHERE id=?", (str(body["note"])[:300], dev))
        row = c.execute("SELECT * FROM devices WHERE id=?", (dev,)).fetchone()
        return 200, {"ok": True, "device": row_json(row, now)}


def row_json(r, now):
    d = dict(r)
    d["effective"] = effective(r, now)
    d["days_left"] = max(0, (r["expires"] - now + DAY - 1) // DAY)
    return d


def list_devices():
    now = int(time.time())
    with db() as c:
        rows = c.execute("SELECT * FROM devices ORDER BY last_seen DESC").fetchall()
        return 200, {"ok": True, "now": now, "devices": [row_json(r, now) for r in rows]}


class H(BaseHTTPRequestHandler):
    server_version = "starbond-license"

    def log_message(self, fmt, *a):
        sys.stderr.write("%s %s\n" % (self.client_ip(), fmt % a))

    def client_ip(self):
        xf = self.headers.get("X-Forwarded-For", "")
        return (xf.split(",")[0].strip() or self.headers.get("X-Real-IP", "") or self.client_address[0])[:45]

    def send(self, code, obj=None, body=None, ctype="application/json; charset=utf-8", extra=None):
        data = body if body is not None else json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def authed(self):
        if not ADMIN_PASSWORD:
            return False
        h = self.headers.get("Authorization", "")
        if not h.startswith("Basic "):
            return False
        try:
            user, _, pw = base64.b64decode(h[6:]).decode("utf-8").partition(":")
        except Exception:
            return False
        return hmac.compare_digest(pw.encode(), ADMIN_PASSWORD.encode())

    def need_auth(self):
        self.send(401, {"ok": False, "error": "auth"}, extra={"WWW-Authenticate": 'Basic realm="Starbond Licenses", charset="UTF-8"'})

    def route(self):
        p = urlparse(self.path)
        path = re.sub(r"^/starbond-lic", "", p.path) or "/"   # يشتغل ورا nginx بالـ prefix أو بدونه
        return path, parse_qs(p.query)

    def do_GET(self):
        path, q = self.route()
        if path == "/api/check":
            code, obj = handle_check(q, self.client_ip())
            return self.send(code, obj)
        if path == "/health":
            return self.send(200, {"ok": True})
        if path in ("/admin", "/admin/", "/"):
            if not self.authed():
                return self.need_auth()
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "admin.html"), "rb") as f:
                return self.send(200, body=f.read(), ctype="text/html; charset=utf-8")
        if path == "/api/admin/devices":
            if not self.authed():
                return self.need_auth()
            return self.send(*list_devices())
        self.send(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        path, q = self.route()
        m = re.match(r"^/api/admin/devices/([0-9A-Fa-f:\-]{12,17})$", path)
        if not m:
            return self.send(404, {"ok": False, "error": "not found"})
        if not self.authed():
            return self.need_auth()
        n = int(self.headers.get("Content-Length") or 0)
        if n > 10000:
            return self.send(413, {"ok": False, "error": "too large"})
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return self.send(400, {"ok": False, "error": "bad json"})
        self.send(*handle_admin_action(m.group(1), body))


if __name__ == "__main__":
    if not ADMIN_PASSWORD:
        print("ADMIN_PASSWORD مش مضبوط — لوحة الإدارة مقفولة", file=sys.stderr)
    init_db()
    print("starbond-license on :%d db=%s trial=%dd" % (PORT, DB_PATH, TRIAL_DAYS), file=sys.stderr)
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()
