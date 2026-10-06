import os, re, json, uuid, time, threading, subprocess, queue, hmac
from urllib.parse import urlsplit
import requests, imageio_ffmpeg
from flask import Flask, request, jsonify, send_from_directory, session, redirect, url_for, render_template_string, has_request_context
from yt_dlp import YoutubeDL

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_ROOT = os.environ.get("DATA_DIR", os.path.join(BASE, "runtime"))
APP_ENV = os.environ.get("APP_ENV", "development")
ACCESS_PASSWORD = os.environ.get("PUBLIC_ACCESS_PASSWORD", "")
SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "")
if APP_ENV == "production" and not ACCESS_PASSWORD:
    raise RuntimeError("PUBLIC_ACCESS_PASSWORD must be configured in production")
if APP_ENV == "production" and not SECRET_KEY:
    raise RuntimeError("FLASK_SECRET_KEY must be configured in production")
FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
app = Flask(__name__, static_folder="static", static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024
app.config.update(
    SECRET_KEY=SECRET_KEY or uuid.uuid4().hex,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Strict",
    SESSION_COOKIE_SECURE=APP_ENV == "production",
)
jobs, q = {}, queue.Queue()
CODEC = {"mp3": ["-c:a", "libmp3lame", "-b:a", "256k"], "wav": ["-c:a", "pcm_s16le"],
         "m4a": ["-c:a", "aac", "-b:a", "192k"], "aac": ["-c:a", "aac", "-b:a", "192k", "-f", "adts"],
         "ogg": ["-c:a", "libvorbis", "-q:a", "5"]}
MIME = {"mp3": "audio/mpeg", "wav": "audio/wav", "m4a": "audio/mp4", "aac": "audio/aac", "ogg": "audio/ogg"}
ALLOWED_HOSTS = {
    "youtube.com", "www.youtube.com", "music.youtube.com", "youtu.be",
    "tiktok.com", "www.tiktok.com", "m.tiktok.com", "soundcloud.com", "www.soundcloud.com",
}

def current_workspace():
    if not has_request_context():
        return "system"
    workspace = session.get("workspace_id")
    if not workspace:
        workspace = uuid.uuid4().hex
        session["workspace_id"] = workspace
    return workspace

def workspace_paths(workspace=None):
    workspace = workspace or current_workspace()
    if workspace != "system" and not re.fullmatch(r"[0-9a-f]{32}", workspace):
        raise ValueError("Invalid workspace")
    root = os.path.join(DATA_ROOT, workspace)
    out, temp = os.path.join(root, "output"), os.path.join(root, "temp")
    os.makedirs(out, exist_ok=True)
    os.makedirs(temp, exist_ok=True)
    return out, temp, os.path.join(root, "history.json"), os.path.join(root, "playlists.json")

def valid_audio_url(value):
    try:
        parsed = urlsplit(value)
        return (parsed.scheme == "https" and parsed.hostname is not None
                and parsed.hostname.lower().rstrip(".") in ALLOWED_HOSTS
                and parsed.port in (None, 443)
                and parsed.username is None and parsed.password is None)
    except ValueError:
        return False

def read_json(path, default):
    try:
        with open(path, encoding="utf-8") as data:
            return json.load(data)
    except FileNotFoundError:
        return default

def write_json(path, value):
    with open(path, "w", encoding="utf-8") as data:
        json.dump(value, data, ensure_ascii=False, indent=1)

@app.before_request
def require_access():
    if request.endpoint in ("login", "healthz"):
        return None
    if not ACCESS_PASSWORD and APP_ENV != "production":
        current_workspace()
        return None
    if session.get("authenticated"):
        current_workspace()
        return None
    if request.path.startswith("/api/"):
        return jsonify(error="Silakan masuk terlebih dahulu."), 401
    return redirect(url_for("login", next=request.full_path))

@app.after_request
def security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    return response

@app.get("/healthz")
def healthz():
    return jsonify(status="ok")

@app.route("/login", methods=["GET", "POST"])
def login():
    error = ""
    if request.method == "POST":
        submitted = request.form.get("password", "")
        if ACCESS_PASSWORD and hmac.compare_digest(submitted, ACCESS_PASSWORD):
            session.clear()
            session["authenticated"] = True
            session["workspace_id"] = uuid.uuid4().hex
            target = request.form.get("next", "/")
            parsed = urlsplit(target)
            if not target.startswith("/") or target.startswith("//") or parsed.netloc or parsed.scheme or "\\" in target:
                target = "/"
            return redirect(target)
        error = "Kata sandi tidak valid atau belum dikonfigurasi."
    return render_template_string("""<!doctype html>
<html lang="id"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Masuk · Gaje Studio</title>
<style>body{font:16px system-ui;background:#0a0a0c;color:#f2f2f2;display:grid;place-items:center;min-height:95vh}
main{width:min(360px,90vw);padding:28px;border:1px solid #2a2a2e;border-radius:14px;background:#141416}
h1{font-size:24px}label{display:block;margin:18px 0 6px}input,button{box-sizing:border-box;width:100%;padding:12px;border-radius:8px}
input{background:#1d1d20;border:1px solid #2a2a2e;color:inherit}button{margin-top:14px;border:0;background:#ff2d4a;color:white;font-weight:700;cursor:pointer}
.error{color:#ff8795}</style><main><h1>Gaje Studio</h1><p>Masukkan kata sandi untuk melanjutkan.</p>
{% if error %}<p class="error">{{ error }}</p>{% endif %}
<form method="post"><input type="hidden" name="next" value="{{ next }}">
<label for="password">Kata sandi akses</label><input id="password" name="password" type="password" autocomplete="current-password" required autofocus>
<button type="submit">Masuk</button></form></main></html>""",
        error=error, next=request.args.get("next", "/"))

@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

def load_hist(workspace=None):
    return read_json(workspace_paths(workspace)[2], [])

def load_pl(workspace=None):
    return read_json(workspace_paths(workspace)[3], [])

def add_pl(name):
    name = re.sub(r"\s+", " ", (name or "")).strip()[:50]
    if not name: return ""
    workspace = current_workspace()
    pl = load_pl(workspace)
    for n in pl:
        if n.lower() == name.lower(): return n
    pl.append(name); write_json(workspace_paths(workspace)[3], pl)
    return name

def write_hist(h, workspace=None):
    write_json(workspace_paths(workspace)[2], h[:100])

def save_hist(item, workspace=None):
    h = load_hist(workspace); h.insert(0, item); write_hist(h, workspace)

def norm_state(s):
    s = (s or "").lower()
    if "approv" in s: return "Approved"
    if "reject" in s: return "Rejected"
    if "review" in s or "pend" in s: return "Reviewing"
    return "Unknown"

def duration(path):
    r = subprocess.run([FFMPEG, "-i", path], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.?\d*)", r.stderr)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0

def roblox_upload(path, name, fmt, key, cid, ctype, job):
    creator = {"groupId": cid} if ctype == "group" else {"userId": cid}
    meta = {"assetType": "Audio", "displayName": name[:50], "description": "Uploaded via Roblox Hub",
            "creationContext": {"creator": creator}}
    h = {"x-api-key": key}
    with open(path, "rb") as f:
        r = requests.post("https://apis.roblox.com/assets/v1/assets", headers=h,
            data={"request": json.dumps(meta)}, files={"fileContent": (os.path.basename(path), f, MIME[fmt])}, timeout=120)
    if r.status_code != 200: raise RuntimeError(f"Roblox: {r.status_code} {r.text[:200]}")
    op = r.json().get("path") or r.json().get("operationId")
    op = op if str(op).startswith("operations/") else f"operations/{op}"
    for _ in range(40):
        time.sleep(2)
        d = requests.get(f"https://apis.roblox.com/assets/v1/{op}", headers=h, timeout=30).json()
        if d.get("done"):
            if "error" in d: raise RuntimeError(d["error"].get("message", "Upload ditolak"))
            return d["response"]["assetId"]
    raise RuntimeError("Timeout menunggu moderasi Roblox")

def process(job):
    try:
        out_dir, temp_dir, _, _ = workspace_paths(job["workspace_id"])
        p = job["params"]
        if p.get("reuse"):   # upload ulang file dari History, tanpa convert
            it = p["reuse"]; outp = os.path.join(out_dir, it["file"]); job.update(status="Upload ulang ke Roblox…", progress=40)
            name = re.sub(r"[^\w\- ]", "", it["title"]).strip()[:60] or "audio"
            aid = roblox_upload(outp, name, it["fmt"].lower(), p["key"], p["cid"], p["ctype"], job)
            res = dict(it) | {"assetId": aid, "time": int(time.time()), "creator": f'{p["ctype"]}:{p["cid"]}'}
            res.pop("moderation", None)
            job.update(status="Selesai", progress=100, result=res, done=True); save_hist(res, job["workspace_id"]); return
        job.update(status="Mengambil audio…", progress=5)
        if p.get("url"):
            def hook(d):
                if d["status"] == "downloading" and d.get("total_bytes") or d.get("total_bytes_estimate"):
                    t = d.get("total_bytes") or d.get("total_bytes_estimate")
                    job["progress"] = 5 + int(45 * d["downloaded_bytes"] / t)
            with YoutubeDL({"format": "bestaudio/best", "outtmpl": os.path.join(temp_dir, job["id"] + ".%(ext)s"),
                            "noplaylist": True, "quiet": True, "progress_hooks": [hook]}) as y:
                info = y.extract_info(p["url"], download=True); src = y.prepare_filename(info)
            title = p.get("title") or info.get("title", "audio")
        else:
            src, title = p["src"], p.get("title") or p["orig_title"]
        job.update(status="Convert audio…", progress=55)
        fmt = p["fmt"]; safe = re.sub(r"[^\w\- ]", "", title).strip()[:60] or "audio"
        outname = f"{safe}_{job['id'][:6]}.{fmt}"; outp = os.path.join(out_dir, outname)
        cmd = [FFMPEG, "-y", "-i", src, "-vn", "-t", str(p["maxdur"]), "-af", f"volume={p['amp']}dB", *CODEC[fmt], outp]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode: raise RuntimeError("FFmpeg gagal: " + r.stderr[-200:])
        res = {"file": outname, "title": title, "fmt": fmt.upper(), "duration": round(duration(outp)),
               "size": round(os.path.getsize(outp) / 1048576, 2), "time": int(time.time())}
        if p.get("playlist"): res["playlist"] = p["playlist"]
        if p.get("upload"):
            job.update(status="Upload ke Roblox…", progress=80)
            res["assetId"] = roblox_upload(outp, safe, fmt, p["key"], p["cid"], p["ctype"], job)
            res["creator"] = f'{p["ctype"]}:{p["cid"]}'
        job.update(status="Selesai", progress=100, result=res, done=True); save_hist(res, job["workspace_id"])
    except Exception as e:
        job.update(status="Gagal", error=str(e), done=True)
    finally:
        job.pop("params", None)
        for f in os.listdir(temp_dir):
            if f.startswith(job["id"]):
                try: os.remove(os.path.join(temp_dir, f))
                except OSError: pass

def worker():
    while True: process(q.get()); q.task_done()
threading.Thread(target=worker, daemon=True).start()

@app.route("/")
def index(): return send_from_directory(os.path.join(BASE, "static"), "index.html")

MAXPL = 30

def enqueue(p, label):
    jid = uuid.uuid4().hex
    workspace = current_workspace()
    jobs[jid] = {"id": jid, "label": label, "status": "Antre", "progress": 0, "params": p,
                 "workspace_id": workspace, "done": False}
    q.put(jobs[jid]); return jid

@app.get("/api/expand_playlist")
def expand_playlist():
    url = request.args.get("url", "").strip()
    if not valid_audio_url(url): return jsonify(error="URL tidak didukung"), 400
    try:
        with YoutubeDL({"extract_flat": True, "quiet": True, "playlistend": MAXPL}) as y:
            info = y.extract_info(url, download=False)
        entries = info.get("entries") if info.get("_type") == "playlist" or info.get("entries") else None
        if not entries: return jsonify(is_playlist=False)
        items = []
        for e in entries:
            if not e: continue
            vid = e.get("url") or e.get("id")
            link = vid if str(vid).startswith("http") else f"https://www.youtube.com/watch?v={vid}"
            items.append({"url": link, "title": e.get("title") or "audio"})
        return jsonify(is_playlist=True, total=info.get("playlist_count") or len(items), items=items[:MAXPL])
    except Exception as e:
        return jsonify(error=str(e)[:150]), 500

@app.post("/api/convert")
def convert():
    f = request.form; jid = uuid.uuid4().hex
    if f.get("rights_confirmed") != "1":
        return jsonify(error="Konfirmasi bahwa kamu memiliki hak atas audio ini atau izin untuk menggunakannya."), 400
    p = {"amp": min(max(float(f.get("amp", -2)), -20), 0),
         "maxdur": min(max(int(f.get("maxdur", 300)), 30), 600), "fmt": f.get("fmt", "mp3") if f.get("fmt") in CODEC else "mp3",
         "upload": f.get("upload") == "1", "key": f.get("key", "").strip(), "cid": f.get("cid", "").strip(), "ctype": f.get("ctype", "user")}
    if p["upload"] and not (p["key"] and p["cid"].isdigit()): return jsonify(error="API Key & Creator ID (angka) Roblox wajib diisi"), 400
    p["playlist"] = add_pl(f.get("playlist", ""))
    custom_title = f.get("title", "").strip()[:120]
    url = f.get("url", "").strip()

    if f.get("playlist_mode") == "1" and url:
        if not valid_audio_url(url): return jsonify(error="URL tidak didukung"), 400
        try:
            with YoutubeDL({"extract_flat": True, "quiet": True, "playlistend": MAXPL}) as y:
                info = y.extract_info(url, download=False)
            entries = [e for e in (info.get("entries") or []) if e]
        except Exception as e:
            return jsonify(error="Gagal membaca playlist: " + str(e)[:120]), 400
        if not entries: return jsonify(error="Playlist kosong atau tidak ditemukan"), 400
        if not p["playlist"]: p["playlist"] = add_pl(info.get("title") or "")  # folder otomatis dari judul playlist
        ids = []
        for e in entries[:MAXPL]:
            vid = e.get("url") or e.get("id")
            link = vid if str(vid).startswith("http") else f"https://www.youtube.com/watch?v={vid}"
            pp = dict(p); pp["url"] = link
            ids.append(enqueue(pp, e.get("title") or "audio"))
        return jsonify(ids=ids, total=len(ids))

    if custom_title: p["title"] = custom_title
    if url:
        if not valid_audio_url(url): return jsonify(error="URL tidak didukung"), 400
        p["url"] = url; label = url
    elif "file" in request.files:
        up = request.files["file"]; ext = os.path.splitext(up.filename)[1].lower()
        if ext not in (".mp3", ".wav", ".m4a", ".aac"): return jsonify(error="Format file tidak didukung"), 400
        temp_dir = workspace_paths()[1]
        p["src"] = os.path.join(temp_dir, jid + ext); up.save(p["src"]); p["orig_title"] = os.path.splitext(up.filename)[0]; label = up.filename
    else: return jsonify(error="Pilih file atau isi link"), 400
    return jsonify(id=enqueue(p, label))

@app.get("/api/job/<jid>")
def job(jid):
    j = jobs.get(jid)
    if not j or j["workspace_id"] != current_workspace(): return jsonify(error="not found"), 404
    return jsonify({k: v for k, v in j.items() if k not in ("params", "workspace_id")} | {"queue": q.qsize()})

@app.post("/api/status")
def status():
    key = request.form.get("key", "").strip()
    ids = [i for i in request.form.get("ids", "").split(",") if i.strip().isdigit()][:100]
    if not key: return jsonify(error="API Key wajib diisi"), 400
    out, mods = {}, {}
    for i in ids:
        try:
            r = requests.get(f"https://apis.roblox.com/assets/v1/assets/{i}", headers={"x-api-key": key},
                             params={"readMask": "moderationResult"}, timeout=20)
            if r.status_code == 200:
                st = norm_state((r.json().get("moderationResult") or {}).get("moderationState"))
                out[i] = {"state": st}; mods[i] = st
            elif r.status_code in (401, 403): out[i] = {"state": "Error", "msg": "API Key tidak punya izin asset:read"}
            elif r.status_code == 404: out[i] = {"state": "Error", "msg": "Asset tidak ditemukan"}
            else: out[i] = {"state": "Error", "msg": f"HTTP {r.status_code}"}
        except Exception as e:
            out[i] = {"state": "Error", "msg": str(e)[:80]}
    if mods:
        workspace = current_workspace()
        h = load_hist(workspace)
        for it in h:
            if str(it.get("assetId")) in mods: it["moderation"] = mods[str(it["assetId"])]
        write_hist(h, workspace)
    return jsonify(out)

@app.post("/api/reupload")
def reupload():
    f = request.form; name = os.path.basename(f.get("file", ""))
    if f.get("rights_confirmed") != "1":
        return jsonify(error="Konfirmasi bahwa kamu memiliki hak atas audio ini atau izin untuk menggunakannya."), 400
    workspace = current_workspace()
    out_dir = workspace_paths(workspace)[0]
    item = next((x for x in load_hist(workspace) if x.get("file") == name), None)
    key, cid, ctype = f.get("key", "").strip(), f.get("cid", "").strip(), f.get("ctype", "user")
    if not item or not os.path.exists(os.path.join(out_dir, name)): return jsonify(error="File tidak ditemukan di folder output"), 404
    if not key or not cid.isdigit(): return jsonify(error="API Key & ID tujuan (angka) wajib diisi"), 400
    jid = uuid.uuid4().hex
    jobs[jid] = {"id": jid, "label": "Upload ulang: " + item["title"], "status": "Antre", "progress": 0, "done": False,
                 "workspace_id": workspace,
                 "params": {"reuse": item, "key": key, "cid": cid, "ctype": "group" if ctype == "group" else "user"}}
    q.put(jobs[jid]); return jsonify(id=jid)

@app.post("/api/rename")
def rename():
    f = request.form; file, t, title = f.get("file", ""), f.get("time", ""), f.get("title", "").strip()
    if not title: return jsonify(error="Nama tidak boleh kosong"), 400
    title = title[:80]
    workspace = current_workspace()
    h = load_hist(workspace); found = False
    for it in h:
        if it.get("file") == file and str(it.get("time")) == str(t):
            it["title"] = title; found = True; break
    if not found: return jsonify(error="Lagu tidak ditemukan di history"), 404
    write_hist(h, workspace); return jsonify(title=title)

@app.get("/api/rbxinfo")
def rbxinfo():
    cid, ctype = request.args.get("cid", "").strip(), request.args.get("ctype", "user")
    if not cid.isdigit(): return jsonify(error="ID tidak valid"), 400
    try:
        if ctype == "group":
            g = requests.get(f"https://groups.roblox.com/v1/groups/{cid}", timeout=10)
            if g.status_code != 200: return jsonify(error="Grup tidak ditemukan"), 404
            name = g.json().get("name", "")
            t = requests.get("https://thumbnails.roblox.com/v1/groups/icons",
                params={"groupIds": cid, "size": "150x150", "format": "Png"}, timeout=10).json()
        else:
            u = requests.get(f"https://users.roblox.com/v1/users/{cid}", timeout=10)
            if u.status_code != 200: return jsonify(error="User tidak ditemukan"), 404
            name = u.json().get("displayName") or u.json().get("name", "")
            t = requests.get("https://thumbnails.roblox.com/v1/users/avatar-headshot",
                params={"userIds": cid, "size": "150x150", "format": "Png"}, timeout=10).json()
        av = (t.get("data") or [{}])[0].get("imageUrl", "")
        return jsonify(name=name, avatar=av)
    except Exception as e:
        return jsonify(error=str(e)[:100]), 500

@app.get("/api/playlists")
def playlists():
    pl = load_pl()
    for it in load_hist():
        n = it.get("playlist")
        if n and n not in pl: pl.append(n)
    return jsonify(pl)

@app.post("/api/playlists")
def playlist_new():
    n = add_pl(request.form.get("name", ""))
    if not n: return jsonify(error="Nama playlist kosong"), 400
    return jsonify(name=n, list=load_pl())

@app.post("/api/playlists/delete")
def playlist_del():
    n = request.form.get("name", "")
    workspace = current_workspace()
    write_json(workspace_paths(workspace)[3], [x for x in load_pl(workspace) if x != n])
    h = load_hist(workspace)
    for it in h:
        if it.get("playlist") == n: it.pop("playlist")
    write_hist(h, workspace); return jsonify(load_pl(workspace))

@app.post("/api/history/delete")
def history_delete():
    """Hapus riwayat: scope=one (file+time) | playlist (name) | all. files=1 -> hapus juga file audionya."""
    f = request.form; scope = f.get("scope", "one"); workspace = current_workspace()
    out_dir, _, _, playlist_path = workspace_paths(workspace)
    h = load_hist(workspace)
    if scope == "all":
        gone, keep = h, []
    elif scope == "playlist":
        n = f.get("name", "")
        gone = [x for x in h if (x.get("playlist") or "") == n]; keep = [x for x in h if (x.get("playlist") or "") != n]
        if n: write_json(playlist_path, [x for x in load_pl(workspace) if x != n])
    else:
        file, t = f.get("file", ""), str(f.get("time", ""))
        match = lambda x: x.get("file") == file and str(x.get("time")) == t
        gone = [x for x in h if match(x)]; keep = [x for x in h if not match(x)]
    if f.get("files") == "1":
        left = {x.get("file") for x in keep}
        for x in gone:
            if x.get("file") and x["file"] not in left:
                try: os.remove(os.path.join(out_dir, os.path.basename(x["file"])))
                except OSError: pass
    write_hist(keep, workspace); return jsonify(removed=len(gone))

@app.get("/api/history")
def history(): return jsonify(load_hist())

@app.get("/files/<path:n>")
def files(n): return send_from_directory(workspace_paths()[0], n, as_attachment=request.args.get("dl") == "1")

from reuploader import bp
app.register_blueprint(bp)

if __name__ == "__main__":
    host = "0.0.0.0" if APP_ENV == "production" else "127.0.0.1"
    app.run(host, int(os.environ.get("PORT", "5000")), threaded=True)
