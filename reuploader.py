"""Backend Animation Re-Uploader (Open Cloud API) - dipasang sebagai Blueprint ke app.py."""
import json, re, time
from concurrent.futures import ThreadPoolExecutor
import requests
from flask import Blueprint, Response, jsonify, request

bp = Blueprint("reuploader", __name__)
ASSETS = "https://apis.roblox.com/assets/v1"
DELIVERY = "https://apis.roblox.com/asset-delivery-api/v1/assetId"


@bp.post("/api/account")
def account():
    d = request.json or {}
    cid, ctype = str(d.get("creator_id", "")).strip(), d.get("creator_type", "user")
    if not cid.isdigit():
        return jsonify(error="ID harus berupa angka"), 400
    try:
        if ctype == "group":
            g = requests.get(f"https://groups.roblox.com/v1/groups/{cid}", timeout=15)
            if g.status_code != 200:
                return jsonify(error="Grup tidak ditemukan"), 400
            th = requests.get("https://thumbnails.roblox.com/v1/groups/icons",
                              params={"groupIds": cid, "size": "150x150", "format": "Png"}, timeout=15).json()
            return jsonify(name=g.json()["name"], handle=f"Group {cid}", avatar=th["data"][0].get("imageUrl", ""))
        u = requests.get(f"https://users.roblox.com/v1/users/{cid}", timeout=15)
        if u.status_code != 200:
            return jsonify(error="User tidak ditemukan"), 400
        j = u.json()
        th = requests.get("https://thumbnails.roblox.com/v1/users/avatar-headshot",
                          params={"userIds": cid, "size": "150x150", "format": "Png"}, timeout=15).json()
        return jsonify(name=j["displayName"], handle=f"@{j['name']}", avatar=th["data"][0].get("imageUrl", ""))
    except Exception as e:
        return jsonify(error=f"Gagal cek akun: {e}"), 500


def rq(method, url, **kw):
    """requests dengan retry otomatis untuk rate limit (429) dan error server."""
    kw.setdefault("timeout", 30)
    r = None
    for i in range(5):
        r = requests.request(method, url, **kw)
        if r.status_code == 429 or (r.status_code >= 500 and i < 2):
            try:
                wait = float(r.headers.get("Retry-After", 2 * (i + 1)))
            except ValueError:
                wait = 2 * (i + 1)
            time.sleep(min(wait, 20))
            continue
        return r
    return r


# Format daftar: {"NAMA", 123} | ["NAMA"] = "rbxassetid://123" | "NAMA": 123
PAIR_PATTERNS = [
    re.compile(r"""["']([^"'\n]+)["']\s*,\s*["']?(?:rbxassetid://)?(\d{5,})"""),
    re.compile(r"""\[\s*["']([^"'\n]+)["']\s*\]\s*=\s*["']?(?:rbxassetid://)?(\d{5,})"""),
    re.compile(r"""["']([^"'\n]+)["']\s*[:=]\s*["']?(?:rbxassetid://)?(\d{5,})"""),
]


def parse_pairs(text):
    found = []
    for pat in PAIR_PATTERNS:
        for m in list(pat.finditer(text)):
            found.append((m.start(), m.group(1).strip(), m.group(2)))
            text = text[:m.start()] + " " * (m.end() - m.start()) + text[m.end():]
    found.sort()
    return [(n, i) for _, n, i in found], text


@bp.post("/api/resolve")
def resolve():
    d = request.json or {}
    text = d.get("text") if d.get("text") is not None else "\n".join(d.get("lines", []))
    pairs, rest = parse_pairs(text)
    out = [{"id": i, "name": n} for n, i in pairs]
    for line in rest.splitlines():
        line = line.strip()
        if not line or not re.sub(r"[\s{}\[\](),;\"']", "", line):
            continue
        if re.match(r"(local\b|return\b|--|end\b)", line):
            continue
        m = re.search(r"bundles/(\d+)", line)
        if m:
            try:
                b = rq("GET", f"https://catalog.roblox.com/v1/bundles/{m.group(1)}/details").json()
                items = [i for i in b.get("items", []) if i.get("type") == "Asset"]
                if not items:
                    out.append({"id": "", "name": line, "error": "Bundle tidak berisi asset"})
                for it in items:
                    out.append({"id": str(it["id"]), "name": it.get("name", "")})
            except Exception:
                out.append({"id": "", "name": line, "error": "Gagal baca bundle"})
            continue
        m = (re.search(r"(?:catalog|library|asset|asset-details)/(\d+)", line)
             or re.search(r"rbxassetid://(\d+)", line) or re.fullmatch(r"[\s,{}]*(\d{5,})[\s,{}]*", line))
        out.append({"id": m.group(1), "name": ""} if m else {"id": "", "name": line, "error": "Format tidak dikenali"})
    fill_details(out)
    return jsonify(items=out)


def fetch_details(asset_id):
    try:
        r = rq("GET", f"https://economy.roblox.com/v2/assets/{asset_id}/details", timeout=15)
        if r.status_code != 200:
            return {}
        j = r.json()
        return {"name": j.get("Name", ""), "owner": (j.get("Creator") or {}).get("Name", "")}
    except Exception:
        return {}


def fill_details(items):
    todo = [i for i in items if i.get("id")]
    with ThreadPoolExecutor(max_workers=8) as ex:
        for it, d in zip(todo, ex.map(lambda i: fetch_details(i["id"]), todo)):
            if d.get("name") and not it.get("name"):
                it["name"] = d["name"]
            it["owner"] = d.get("owner", "")


def asset_name(asset_id):
    return fetch_details(asset_id).get("name") or f"Anim_{asset_id}"


def err_text(r):
    try:
        j = r.json()
        return j.get("message") or j.get("errors", [{}])[0].get("message") or r.text[:150]
    except Exception:
        return r.text[:150]


def find_location(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k.lower() == "location" and isinstance(v, str) and v.startswith("http"):
                return v
        for v in obj.values():
            r = find_location(v)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = find_location(v)
            if r:
                return r
    return None


def download(api_key, asset_id):
    """Ambil konten animasi lewat Asset Delivery API."""
    r = rq("GET", f"{DELIVERY}/{asset_id}", headers={"x-api-key": api_key, "Accept": "application/json"})
    if r.status_code in (401, 403):
        raise RuntimeError(f"API key ditolak Asset Delivery ({r.status_code}): {err_text(r)}. "
                           "Pastikan key punya scope legacy-asset:manage dan izin ke asset ini.")
    if r.status_code != 200:
        raise RuntimeError(f"Gagal ambil animasi {asset_id} ({r.status_code}): {err_text(r)}")
    if "json" not in r.headers.get("content-type", "").lower() and r.content:
        return r.content
    try:
        j = r.json()
    except ValueError:
        raise RuntimeError(f"Respons Asset Delivery bukan JSON: {r.text[:200]}")
    loc = find_location(j)
    if not loc:
        msg = ""
        if isinstance(j, dict) and j.get("errors"):
            msg = "; ".join(str(e.get("message", e)) for e in j["errors"] if isinstance(e, dict)) or str(j["errors"])
        msg = msg or json.dumps(j, ensure_ascii=False)[:300]
        raise RuntimeError(
            f"Asset Delivery tidak memberi lokasi file untuk ID {asset_id}. Respons Roblox: {msg}. "
            "Biasanya karena animasi bukan milikmu / tidak ada izin akses, atau API key belum punya scope "
            "legacy-asset. Solusi: export animasinya dari Studio sebagai .rbxm lalu drag ke dropzone.")
    f = rq("GET", loc)
    if f.status_code != 200:
        raise RuntimeError(f"Gagal download data animasi ({f.status_code})")
    return f.content


def sniff(data):
    """'rbxm' (biner), 'rbxmx' (XML) atau None."""
    head = data[:64].lstrip(b"\xef\xbb\xbf \r\n\t")
    if head.startswith(b"<roblox!"):
        return "rbxm"
    if head.startswith(b"<roblox") or head.startswith(b"<?xml"):
        return "rbxmx"
    return None


def hexhead(data):
    return " ".join(f"{b:02x}" for b in data[:12]) + " | " + "".join(chr(b) if 32 <= b < 127 else "." for b in data[:12])


def create_asset(api_key, ctype, cid, name, data):
    fmt = sniff(data)
    if not fmt:
        raise RuntimeError("Isi file bukan format rbxm/rbxmx (awal data: " + hexhead(data) + "). Upload dibatalkan "
                           "supaya tidak membuat animasi rusak ('AnimationClip loaded is not valid').")
    creator = {"groupId": cid} if ctype == "group" else {"userId": cid}
    meta = {"assetType": "Animation", "displayName": name[:50], "description": "Re-uploaded",
            "creationContext": {"creator": creator}}
    r = rq("POST", f"{ASSETS}/assets", headers={"x-api-key": api_key}, timeout=90,
           files={"request": (None, json.dumps(meta), "application/json"),
                  "fileContent": ("animation." + fmt, data, "model/x-rbxm")})
    if r.status_code != 200:
        raise RuntimeError(f"Create Asset gagal ({r.status_code}): {err_text(r)}")
    op = r.json()
    op_path = op.get("path", "")
    for _ in range(40):
        if op.get("done"):
            break
        time.sleep(1.5)
        p = rq("GET", f"https://apis.roblox.com/{'assets/v1/' if not op_path.startswith('assets/') else ''}{op_path}",
               headers={"x-api-key": api_key})
        if p.status_code != 200:
            raise RuntimeError(f"Cek status upload gagal ({p.status_code}): {err_text(p)}")
        op = p.json()
    if not op.get("done"):
        raise RuntimeError("Timeout menunggu Roblox memproses upload")
    if op.get("error"):
        raise RuntimeError(op["error"].get("message", "Upload ditolak Roblox"))
    state = ((op.get("response") or {}).get("moderationResult") or {}).get("moderationState", "")
    if "REJECT" in state.upper():
        raise RuntimeError("Animasi ditolak moderasi Roblox (" + state + ")")
    aid = (op.get("response") or {}).get("assetId")
    if not aid:
        raise RuntimeError("Upload selesai tapi assetId tidak ditemukan")
    return str(aid)


@bp.post("/api/download")
def download_file():
    api_key, aid = request.form.get("api_key", "").strip(), request.form.get("id", "").strip()
    try:
        if not api_key:
            raise RuntimeError("API key belum diisi")
        if not aid.isdigit():
            raise RuntimeError("ID animasi tidak valid")
        data = download(api_key, aid)
        resp = Response(data, mimetype="application/octet-stream")
        resp.headers["X-Asset-Format"] = sniff(data) or "raw"
        resp.headers["X-Asset-Head"] = hexhead(data).replace("|", "/")
        resp.headers["Access-Control-Expose-Headers"] = "X-Asset-Format, X-Asset-Head"
        return resp
    except Exception as e:
        return jsonify(error=str(e)), 400


@bp.post("/api/upload")
def upload():
    f = request.form
    api_key, ctype, cid = f.get("api_key", "").strip(), f.get("creator_type", "user"), f.get("creator_id", "").strip()
    src = f.get("id", "")
    try:
        if not api_key or not cid:
            raise RuntimeError("API key / ID pembuat belum diisi")
        if "file" in request.files:
            up = request.files["file"]
            src, data = up.filename, up.read()
            name = f.get("name") or re.sub(r"\.rbxmx?$", "", up.filename, flags=re.I)
        else:
            data = download(api_key, src)
            name = f.get("name") or asset_name(src)
        return jsonify(ok=True, source=src, name=name, new_id=create_asset(api_key, ctype, cid, name, data))
    except Exception as e:
        return jsonify(ok=False, source=src, error=str(e))
