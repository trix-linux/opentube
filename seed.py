#!/usr/bin/env python3
"""Seed OpenTube with open-licensed sample videos.

Clips come from test-videos.co.uk (Blender Foundation films, CC BY 3.0).
The rest are procedurally generated with ffmpeg and are public domain.
"""
import argparse
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import db
from server import ffprobe_duration, make_thumbnail

ROOT = Path(__file__).resolve().parent
VIDEOS = ROOT / "media" / "videos"
THUMBS = ROOT / "media" / "thumbs"
BASE = "https://test-videos.co.uk/vids"

ITEMS = [
    {
        "title": "Big Buck Bunny — Meadow Morning",
        "desc": "The opening of Blender's classic open movie: a giant rabbit wakes up to a sunny "
                "forest, greeted by butterflies and very annoying rodents. Created by the Blender "
                "Foundation and released under Creative Commons Attribution 3.0.",
        "category": "Animation", "tags": ["animation", "blender", "comedy", "open movie"],
        "kind": "download",
        "url": f"{BASE}/bigbuckbunny/mp4/h264/720/Big_Buck_Bunny_720_10s_2MB.mp4",
        "file": "big-buck-bunny.mp4", "views": 18420, "likes": 942, "days": 26,
        "comments": [("pixel_pete", "The butterfly scene never gets old."),
                     ("meadowlark", "Watched this at least ten times. Still funny.")],
    },
    {
        "title": "Sintel — The Dragon Chase",
        "desc": "A lone warrior and her dragon companion, from the Blender Foundation's fantasy "
                "short Sintel (CC BY 3.0). One of the most ambitious open movies ever made.",
        "category": "Animation", "tags": ["animation", "fantasy", "blender", "short film"],
        "kind": "download",
        "url": f"{BASE}/sintel/mp4/h264/720/Sintel_720_10s_2MB.mp4",
        "file": "sintel.mp4", "views": 32750, "likes": 2110, "days": 19,
        "comments": [("dragonkin", "The scale of this project is unreal."),
                     ("northwind", "That soundtrack though.")],
    },
    {
        "title": "Jellyfish Drift — Deep Blue",
        "desc": "Slow, hypnotic jellyfish footage for focus, meditation or just leaving on in the "
                "background. A test clip released for open use.",
        "category": "Nature", "tags": ["nature", "ocean", "relaxation", "ambient"],
        "kind": "download",
        "url": f"{BASE}/jellyfish/mp4/h264/720/Jellyfish_720_10s_2MB.mp4",
        "file": "jellyfish.mp4", "views": 9310, "likes": 604, "days": 12,
        "comments": [("calmwater", "Perfect thing to put on while working.")],
    },
    {
        "title": "Mandelbrot Descent",
        "desc": "An endless zoom into the Mandelbrot set, rendered procedurally with ffmpeg. "
                "No two frames are the same.",
        "category": "Abstract", "tags": ["fractal", "math", "visuals", "loop"],
        "kind": "generate",
        "ffmpeg": ["-f", "lavfi", "-i", "mandelbrot=size=1280x720:rate=30"],
        "file": "mandelbrot-descent.mp4", "views": 4210, "likes": 318, "days": 8,
        "comments": [("fractal_fan", "Infinite detail. Beautiful.")],
    },
    {
        "title": "Sierpiński Bloom",
        "desc": "A procedural Sierpiński fractal slowly unfolding, generated in real time with "
                "ffmpeg's fractal source.",
        "category": "Abstract", "tags": ["fractal", "geometry", "generative", "loop"],
        "kind": "generate",
        "ffmpeg": ["-f", "lavfi", "-i", "sierpinski=size=1280x720:rate=30"],
        "file": "sierpinski-bloom.mp4", "views": 2870, "likes": 205, "days": 5,
        "comments": [("triangles", "Geometry class could have used this.")],
    },
    {
        "title": "Conway's Game of Life",
        "desc": "Cellular automata in motion. A single rule, endlessly surprising patterns. "
                "Rendered with ffmpeg's life source.",
        "category": "Tech", "tags": ["simulation", "generative", "code", "cells"],
        "kind": "generate",
        "ffmpeg": ["-f", "lavfi", "-i",
                   "life=size=1280x720:rate=30:mold=10:ratio=0.12:death_color=#101018:life_color=#ff8a1e"],
        "file": "game-of-life.mp4", "views": 6120, "likes": 437, "days": 3,
        "comments": [("turing_complete", "I could watch this for hours."),
                     ("glider", "Still the best zero-player game.")],
    },
    {
        "title": "Neon Gradient Flow",
        "desc": "Warm gradients drifting in slow motion. A calm, looping ambient background made "
                "entirely from procedural color.",
        "category": "Abstract", "tags": ["gradient", "ambient", "loop", "neon"],
        "kind": "generate",
        "ffmpeg": ["-f", "lavfi", "-i",
                   "gradients=size=1280x720:rate=30:speed=0.06:c0=0x14141b:c1=0xff8a1e:c2=0x5b3cff"],
        "file": "neon-gradient.mp4", "views": 1530, "likes": 149, "days": 1,
        "comments": [("slowmotion", "This is my new wallpaper.")],
    },
]


def download(url, dest):
    print(f"  downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "OpenTube-seed/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if total:
                pct = int(done * 100 / total)
                print(f"\r  {pct:3d}%  {done / 1e6:5.1f} MB", end="", flush=True)
    print()


def generate(spec, dest):
    print("  rendering with ffmpeg")
    cmd = ["ffmpeg", "-v", "error", "-y"] + spec + ["-t", "10", "-pix_fmt", "yuv420p",
                                                   "-c:v", "libx264", "-preset", "veryfast",
                                                   "-movflags", "+faststart", str(dest)]
    subprocess.run(cmd, check=True, timeout=300)


def wipe():
    for d in (VIDEOS, THUMBS):
        for f in d.iterdir():
            if f.is_file():
                f.unlink()
    with db.connect() as conn:
        conn.execute("DELETE FROM video_tags")
        conn.execute("DELETE FROM comments")
        conn.execute("DELETE FROM tags")
        conn.execute("DELETE FROM videos")
    print("Cleared existing library.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="wipe the library and reseed")
    args = ap.parse_args()

    db.init()
    with db.connect() as conn:
        existing = conn.execute("SELECT COUNT(*) AS n FROM videos").fetchone()["n"]
    if existing and not args.force:
        print(f"Library already has {existing} videos. Use --force to reseed.")
        return
    if args.force:
        wipe()

    VIDEOS.mkdir(parents=True, exist_ok=True)
    THUMBS.mkdir(parents=True, exist_ok=True)

    for i, item in enumerate(ITEMS, 1):
        dest = VIDEOS / item["file"]
        print(f"[{i}/{len(ITEMS)}] {item['title']}")
        try:
            if item["kind"] == "download":
                download(item["url"], dest)
            else:
                generate(item["ffmpeg"], dest)
        except Exception as exc:
            print(f"  skipped: {exc}", file=sys.stderr)
            continue

        duration = ffprobe_duration(dest)
        thumb_name = dest.stem + ".jpg"
        if not make_thumbnail(dest, THUMBS / thumb_name, duration):
            print("  thumbnail failed; using placeholder", file=sys.stderr)
            from server import placeholder_thumb
            thumb_name = dest.stem + ".svg"
            placeholder_thumb(THUMBS / thumb_name, item["title"])

        vid = db.add_video(item["title"], item["desc"], dest.name, thumb_name,
                           duration, item["category"], item["tags"])
        created = (datetime.now(timezone.utc) - timedelta(days=item["days"])).isoformat(timespec="seconds")
        with db.connect() as conn:
            conn.execute("UPDATE videos SET views = ?, likes = ?, created_at = ? WHERE id = ?",
                         (item["views"], item["likes"], created, vid))
            for j, (author, body) in enumerate(item.get("comments", [])):
                when = (datetime.now(timezone.utc) - timedelta(days=item["days"] - j, hours=3 * j)
                        ).isoformat(timespec="seconds")
                conn.execute(
                    "INSERT INTO comments (video_id, author, body, created_at) VALUES (?, ?, ?, ?)",
                    (vid, author, body, when))
        print(f"  ok — {duration:.1f}s")

    s = db.stats()
    print(f"\nDone. {s['videos']} videos, {s['views']} views, {s['comments']} comments.")
    print("Start the site with:  python3 server.py")


if __name__ == "__main__":
    main()
