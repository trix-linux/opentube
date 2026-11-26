import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "opentube.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS videos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    filename TEXT NOT NULL,
    thumb TEXT NOT NULL,
    duration REAL NOT NULL DEFAULT 0,
    category TEXT NOT NULL DEFAULT 'Other',
    views INTEGER NOT NULL DEFAULT 0,
    likes INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tags (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL
);
CREATE TABLE IF NOT EXISTS video_tags (
    video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    tag_id INTEGER NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (video_id, tag_id)
);
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id INTEGER NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
    author TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_videos_created ON videos(created_at);
CREATE INDEX IF NOT EXISTS idx_comments_video ON comments(video_id);
CREATE INDEX IF NOT EXISTS idx_video_tags_tag ON video_tags(tag_id);
"""

CATEGORIES = ["Animation", "Nature", "Abstract", "Sci-Fi", "Music", "Tech", "Comedy", "Documentary", "Other"]


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(SCHEMA)


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def add_video(title, description, filename, thumb, duration, category, tags):
    from slugify import slugify  # local module
    slug = slugify(title)
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO videos (slug, title, description, filename, thumb, duration, category, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (slug, title, description, filename, thumb, float(duration), category, now()),
        )
        vid = cur.lastrowid
        for name in tags:
            name = name.strip().lower()
            if not name:
                continue
            conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
            tid = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()["id"]
            conn.execute("INSERT OR IGNORE INTO video_tags (video_id, tag_id) VALUES (?, ?)", (vid, tid))
        return vid


def get_video(vid):
    with connect() as conn:
        row = conn.execute("SELECT * FROM videos WHERE id = ?", (vid,)).fetchone()
        if row is None:
            return None
        video = dict(row)
        video["tags"] = [r["name"] for r in conn.execute(
            "SELECT t.name FROM tags t JOIN video_tags vt ON vt.tag_id = t.id "
            "WHERE vt.video_id = ? ORDER BY t.name", (vid,))]
        return video


def list_videos(q="", category="", tag="", sort="new", page=1, per_page=12):
    where, params = [], []
    if q:
        where.append("(v.title LIKE ? OR v.description LIKE ? OR v.id IN ("
                     "SELECT vt.video_id FROM video_tags vt JOIN tags t ON t.id = vt.tag_id WHERE t.name LIKE ?))")
        like = f"%{q}%"
        params += [like, like, like]
    if category:
        where.append("v.category = ?")
        params.append(category)
    if tag:
        where.append("v.id IN (SELECT vt.video_id FROM video_tags vt JOIN tags t ON t.id = vt.tag_id WHERE t.name = ?)")
        params.append(tag)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    order = "v.views DESC, v.id DESC" if sort == "popular" else "v.id DESC"
    offset = max(0, (page - 1) * per_page)
    with connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS n FROM videos v {clause}", params).fetchone()["n"]
        rows = conn.execute(
            f"SELECT v.* FROM videos v {clause} ORDER BY {order} LIMIT ? OFFSET ?",
            params + [per_page, offset],
        ).fetchall()
    videos = []
    for r in rows:
        v = dict(r)
        with connect() as conn:
            v["tags"] = [t["name"] for t in conn.execute(
                "SELECT t.name FROM tags t JOIN video_tags vt ON vt.tag_id = t.id "
                "WHERE vt.video_id = ? ORDER BY t.name", (v["id"],))]
        videos.append(v)
    return videos, total


def related(video, limit=8):
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM videos WHERE id != ? AND category = ? ORDER BY views DESC, id DESC LIMIT ?",
            (video["id"], video["category"], limit),
        ).fetchall()
        if len(rows) < limit:
            ids = [r["id"] for r in rows] + [video["id"]]
            marks = ",".join("?" for _ in ids)
            more = conn.execute(
                f"SELECT * FROM videos WHERE id NOT IN ({marks}) ORDER BY views DESC, id DESC LIMIT ?",
                ids + [limit - len(rows)],
            ).fetchall()
            rows = list(rows) + list(more)
    out = []
    for r in rows:
        v = dict(r)
        with connect() as conn:
            v["tags"] = [t["name"] for t in conn.execute(
                "SELECT t.name FROM tags t JOIN video_tags vt ON vt.tag_id = t.id "
                "WHERE vt.video_id = ? ORDER BY t.name", (v["id"],))]
        out.append(v)
    return out


def add_view(vid):
    with connect() as conn:
        conn.execute("UPDATE videos SET views = views + 1 WHERE id = ?", (vid,))


def toggle_like(vid, delta):
    with connect() as conn:
        conn.execute(
            "UPDATE videos SET likes = MAX(0, likes + ?) WHERE id = ?", (delta, vid))
        row = conn.execute("SELECT likes FROM videos WHERE id = ?", (vid,)).fetchone()
        return row["likes"] if row else 0


def add_comment(vid, author, body):
    with connect() as conn:
        conn.execute(
            "INSERT INTO comments (video_id, author, body, created_at) VALUES (?, ?, ?, ?)",
            (vid, author, body, now()))


def comments(vid, limit=100):
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM comments WHERE video_id = ? ORDER BY id DESC LIMIT ?", (vid, limit))]


def top_tags(limit=18):
    with connect() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT t.name, COUNT(vt.video_id) AS n FROM tags t "
            "JOIN video_tags vt ON vt.tag_id = t.id GROUP BY t.id "
            "ORDER BY n DESC, t.name LIMIT ?", (limit,))]


def stats():
    with connect() as conn:
        v = conn.execute("SELECT COUNT(*) AS n, COALESCE(SUM(views),0) AS views FROM videos").fetchone()
        c = conn.execute("SELECT COUNT(*) AS n FROM comments").fetchone()
    return {"videos": v["n"], "views": v["views"], "comments": c["n"]}
