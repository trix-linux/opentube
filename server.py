#!/usr/bin/env python3
import argparse
import json
import mimetypes
import re
import shutil
import subprocess
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import db
import views

ROOT = Path(__file__).resolve().parent
MEDIA = ROOT / "media"
VIDEOS = MEDIA / "videos"
THUMBS = MEDIA / "thumbs"
STATIC = ROOT / "static"

MAX_UPLOAD = 1024 * 1024 * 1024
ALLOWED_VIDEO_EXT = {".mp4", ".webm", ".ogv", ".mov", ".mkv"}
MIME = {
    ".mp4": "video/mp4", ".webm": "video/webm", ".ogv": "video/ogg",
    ".mov": "video/quicktime", ".mkv": "video/x-matroska",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".svg": "image/svg+xml", ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8", ".ico": "image/x-icon",
}

ROUTES = []


def route(method, pattern):
    rx = re.compile(pattern)

    def deco(fn):
        ROUTES.append((method, rx, fn))
        return fn
    return deco


def safe_join(base, name):
    name = unquote(name)
    if not name or name.startswith((".", "/")) or "/" in name or "\\" in name:
        return None
    path = (base / name).resolve()
    try:
        path.relative_to(base.resolve())
    except ValueError:
        return None
    return path


def ffprobe_duration(path):
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        return float(out.stdout.strip() or 0)
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0.0


def make_thumbnail(video_path, thumb_path, duration):
    at = max(0.0, min(3.0, duration * 0.25 if duration else 0.0))
    try:
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-ss", f"{at:.2f}", "-i", str(video_path),
             "-frames:v", "1", "-vf", "scale=640:-2", "-q:v", "3", str(thumb_path)],
            capture_output=True, timeout=60, check=True,
        )
        return thumb_path.exists() and thumb_path.stat().st_size > 0
    except (OSError, subprocess.SubprocessError):
        return False


def placeholder_thumb(thumb_path, title):
    safe = "".join(c for c in title if c.isalnum() or c in " -_").strip()[:40] or "Video"
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="640" height="360" viewBox="0 0 640 360">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="#1b1b26"/><stop offset="1" stop-color="#2b1a12"/></linearGradient></defs>
<rect width="640" height="360" fill="url(#g)"/>
<circle cx="320" cy="170" r="46" fill="#ff8a1e" opacity="0.9"/>
<path d="M305 146l38 24-38 24z" fill="#0e0e12"/>
<text x="320" y="290" font-family="sans-serif" font-size="20" fill="#c9c9d6" text-anchor="middle">{safe}</text>
</svg>"""
    thumb_path.write_text(svg, encoding="utf-8")


class Handler(BaseHTTPRequestHandler):
    server_version = "OpenTube/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} [{self.command} {urlparse(self.path).path}] {fmt % args}")

    def do_GET(self):
        self.dispatch("GET")

    def do_HEAD(self):
        self.dispatch("GET")

    def do_POST(self):
        self.dispatch("POST")

    def dispatch(self, method):
        parsed = urlparse(self.path)
        path = parsed.path
        self.query = {k: v[0] for k, v in parse_qs(parsed.query, keep_blank_values=True).items()}
        try:
            for m, rx, fn in ROUTES:
                if m != method:
                    continue
                match = rx.fullmatch(path)
                if match:
                    return fn(self, *match.groups())
            self.send_html(404, views.page_404())
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            traceback.print_exc()
            try:
                self.send_html(500, views.page_error(500, "Something went wrong on our side."))
            except Exception:
                pass

    # ---------- response helpers ----------
    def send_bytes(self, code, data, content_type="text/html; charset=utf-8", extra=None):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def send_html(self, code, text):
        self.send_bytes(code, text.encode("utf-8"))

    def send_json(self, code, obj):
        self.send_bytes(code, json.dumps(obj).encode(), "application/json")

    def redirect(self, location):
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def read_body(self, limit):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return b""
        if length > limit:
            raise ValueError("body too large")
        return self.rfile.read(length)

    # ---------- file streaming with Range ----------
    def serve_file(self, path, cache="public, max-age=600"):
        try:
            size = path.stat().st_size
        except OSError:
            return self.send_html(404, views.page_404())
        ctype = MIME.get(path.suffix.lower()) or mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        start, end = 0, size - 1
        status = 200
        rng = self.headers.get("Range")
        if rng:
            m = re.fullmatch(r"bytes=(\d*)-(\d*)", rng.strip())
            if m and size > 0:
                a, b = m.groups()
                if a == "" and b:
                    start = max(0, size - int(b))
                elif a:
                    start = int(a)
                    end = int(b) if b else size - 1
                if start >= size or start > end:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                end = min(end, size - 1)
                status = 206
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", cache)
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if self.command == "HEAD":
            return
        with open(path, "rb") as f:
            f.seek(start)
            remaining = length
            while remaining > 0:
                chunk = f.read(min(65536, remaining))
                if not chunk:
                    break
                self.wfile.write(chunk)
                remaining -= len(chunk)

    # ---------- multipart ----------
    def parse_multipart(self):
        ctype = self.headers.get("Content-Type", "")
        m = re.search(r'boundary="?([^";]+)"?', ctype)
        if "multipart/form-data" not in ctype or not m:
            raise ValueError("expected multipart/form-data")
        boundary = m.group(1).encode()
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise ValueError("empty upload")
        if length > MAX_UPLOAD:
            raise ValueError("upload exceeds 1 GB limit")

        rfile = self.rfile
        delim = b"\r\n--" + boundary
        buf = b"\r\n"
        remaining = length
        written = 0

        def fill():
            nonlocal buf, remaining
            if remaining <= 0:
                raise ValueError("unexpected end of upload")
            chunk = rfile.read(min(1 << 16, remaining))
            if not chunk:
                raise ValueError("unexpected end of upload")
            remaining -= len(chunk)
            buf += chunk

        fields, files = {}, {}
        while delim not in buf:
            fill()
        buf = buf[buf.index(delim) + len(delim):]

        while True:
            while len(buf) < 2:
                fill()
            if buf.startswith(b"--"):
                break
            if buf.startswith(b"\r\n"):
                buf = buf[2:]
            while b"\r\n\r\n" not in buf:
                fill()
            head, buf = buf.split(b"\r\n\r\n", 1)
            headers = {}
            for line in head.split(b"\r\n"):
                if b":" in line:
                    k, v = line.split(b":", 1)
                    headers[k.strip().lower().decode("latin-1")] = v.strip().decode("latin-1")
            disp = headers.get("content-disposition", "")
            name = (re.search(r'name="([^"]*)"', disp) or [None, ""])[1]
            filename = (re.search(r'filename="([^"]*)"', disp) or [None, None])[1]

            fh = None
            chunks = []
            if filename:
                ext = Path(filename).suffix.lower()
                dest = VIDEOS / (uuid.uuid4().hex + ext)
                fh = open(dest, "wb")
            try:
                while True:
                    idx = buf.find(delim)
                    if idx != -1:
                        data = buf[:idx]
                        buf = buf[idx + len(delim):]
                        if fh:
                            fh.write(data)
                            written += len(data)
                        else:
                            chunks.append(data)
                        break
                    keep = len(delim) - 1
                    if len(buf) > keep:
                        data = buf[:-keep]
                        buf = buf[-keep:]
                        if fh:
                            fh.write(data)
                            written += len(data)
                        else:
                            chunks.append(data)
                        if written > MAX_UPLOAD:
                            raise ValueError("upload exceeds 1 GB limit")
                    fill()
            finally:
                if fh:
                    fh.close()
            if fh:
                if filename == "" or not dest.exists() or dest.stat().st_size == 0:
                    if dest.exists():
                        dest.unlink()
                else:
                    files[name] = (filename, dest)
            else:
                raw = b"".join(chunks)
                if len(raw) > 2 * 1024 * 1024:
                    raise ValueError("form field too large")
                fields[name] = raw.decode("utf-8", "replace")
        return fields, files


# ---------- routes ----------
@route("GET", r"/")
def home(h):
    q = h.query.get("q", "").strip()
    category = h.query.get("category", "")
    if category not in db.CATEGORIES:
        category = ""
    tag = h.query.get("tag", "").strip().lower()
    sort = "popular" if h.query.get("sort") == "popular" else "new"
    try:
        page = max(1, int(h.query.get("page", "1")))
    except ValueError:
        page = 1
    videos, total = db.list_videos(q=q, category=category, tag=tag, sort=sort, page=page)
    h.send_html(200, views.page_home(videos, total, q, category, tag, sort, page))


@route("GET", r"/watch/(\d+)")
def watch(h, vid):
    v = db.get_video(int(vid))
    if not v:
        return h.send_html(404, views.page_404())
    rel = db.related(v)
    cmts = db.comments(v["id"])
    h.send_html(200, views.page_watch(v, rel, cmts))


@route("GET", r"/upload")
def upload_form(h):
    h.send_html(200, views.page_upload())


@route("GET", r"/media/(.+)")
def media(h, name):
    path = safe_join(VIDEOS, name)
    if not path or not path.is_file():
        return h.send_html(404, views.page_404())
    h.serve_file(path, cache="public, max-age=86400")


@route("GET", r"/thumbs/(.+)")
def thumbs(h, name):
    path = safe_join(THUMBS, name)
    if not path or not path.is_file():
        return h.send_html(404, views.page_404())
    h.serve_file(path, cache="public, max-age=86400")


@route("GET", r"/static/(.+)")
def static(h, name):
    path = safe_join(STATIC, name)
    if not path or not path.is_file():
        return h.send_html(404, views.page_404())
    h.serve_file(path, cache="public, max-age=300")


@route("POST", r"/api/view/(\d+)")
def api_view(h, vid):
    if not db.get_video(int(vid)):
        return h.send_json(404, {"error": "not found"})
    db.add_view(int(vid))
    h.send_json(200, {"ok": True})


@route("POST", r"/api/like/(\d+)")
def api_like(h, vid):
    if not db.get_video(int(vid)):
        return h.send_json(404, {"error": "not found"})
    try:
        payload = json.loads(h.read_body(4096) or b"{}")
    except (ValueError, json.JSONDecodeError):
        payload = {}
    delta = 1 if int(payload.get("delta", 1)) >= 0 else -1
    count = db.toggle_like(int(vid), delta)
    h.send_json(200, {"likes": count})


@route("POST", r"/comment/(\d+)")
def comment(h, vid):
    if not db.get_video(int(vid)):
        return h.send_html(404, views.page_404())
    body = h.read_body(64 * 1024).decode("utf-8", "replace")
    form = {k: v[0] for k, v in parse_qs(body, keep_blank_values=True).items()}
    author = (form.get("author") or "").strip()[:40] or "Anonymous"
    text = (form.get("body") or "").strip()[:2000]
    if text:
        db.add_comment(int(vid), author, text)
    h.redirect(f"/watch/{vid}")


@route("POST", r"/upload")
def upload(h):
    try:
        fields, files = h.parse_multipart()
    except ValueError as exc:
        return h.send_html(413 if "1 GB" in str(exc) else 400,
                           views.page_upload(str(exc)))
    title = (fields.get("title") or "").strip()[:120]
    description = (fields.get("description") or "").strip()[:4000]
    category = fields.get("category") or "Other"
    if category not in db.CATEGORIES:
        category = "Other"
    tags = [t.strip()[:24] for t in re.split(r"[,\s]+", fields.get("tags", "")) if t.strip()][:10]

    item = files.get("file")
    if not item:
        return h.send_html(400, views.page_upload("Please choose a video file."))
    orig, path = item
    if not title:
        path.unlink(missing_ok=True)
        return h.send_html(400, views.page_upload("A title is required."))
    ext = Path(orig).suffix.lower()
    if ext not in ALLOWED_VIDEO_EXT:
        path.unlink(missing_ok=True)
        return h.send_html(400, views.page_upload("Unsupported format. Use MP4, WebM, OGV, MOV or MKV."))

    duration = ffprobe_duration(path)
    thumb_name = path.stem + ".jpg"
    thumb_path = THUMBS / thumb_name
    if not make_thumbnail(path, thumb_path, duration):
        thumb_name = path.stem + ".svg"
        placeholder_thumb(THUMBS / thumb_name, title)
    vid = db.add_video(title, description, path.name, thumb_name, duration, category, tags)
    h.redirect(f"/watch/{vid}")


def main():
    ap = argparse.ArgumentParser(description="OpenTube demo video platform")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    for d in (VIDEOS, THUMBS, STATIC):
        d.mkdir(parents=True, exist_ok=True)
    db.init()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    server.daemon_threads = True
    print(f"OpenTube running at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nBye.")


if __name__ == "__main__":
    main()
