import html
from datetime import datetime, timezone
from urllib.parse import urlencode

import db

E = lambda s: html.escape(str(s), quote=True)


def fmt_duration(seconds):
    seconds = int(round(float(seconds or 0)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def fmt_count(n):
    n = int(n or 0)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1_000:
        return f"{n / 1_000:.1f}K".replace(".0K", "K")
    return str(n)


def ago(iso):
    try:
        then = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return "recently"
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    secs = (datetime.now(timezone.utc) - then).total_seconds()
    if secs < 60:
        return "just now"
    for unit, div in (("year", 31536000), ("month", 2592000), ("week", 604800),
                      ("day", 86400), ("hour", 3600), ("minute", 60)):
        if secs >= div:
            n = int(secs // div)
            return f"{n} {unit}{'s' if n != 1 else ''} ago"
    return "just now"


ICON_PLAY = '<svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><path d="M8 5v14l11-7z"/></svg>'
ICON_LIKE = ('<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" '
             'stroke-width="2" stroke-linejoin="round"><path d="M7 10v11H3V10h4zm0 0 4-7c1.7 0 3 1.3 3 3v3h5.5a2 2 0 0 1 2 2.3l-1.3 7A2 2 0 0 1 18.2 21H7"/></svg>')
ICON_SEARCH = ('<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" '
               'stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>')
ICON_UP = ('<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" '
           'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 16V4m0 0 4 4m-4-4L8 8"/><path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2"/></svg>')


def layout(title, body, q="", active=""):
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{E(title)} · OpenTube</title>
<link rel="stylesheet" href="/static/style.css">
<link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
</head>
<body>
<header class="topbar">
  <a class="brand" href="/"><span class="brand-mark">{ICON_PLAY}</span><span>Open<b>Tube</b></span></a>
  <form class="search" action="/" method="get" role="search">
    <input type="search" name="q" value="{E(q)}" placeholder="Search videos, tags…" aria-label="Search">
    <button type="submit" aria-label="Search">{ICON_SEARCH}</button>
  </form>
  <nav class="topnav">
    <a href="/" class="{'active' if active == 'home' else ''}">Home</a>
    <a href="/?sort=popular" class="{'active' if active == 'trending' else ''}">Trending</a>
    <a href="/upload" class="upload-link">{ICON_UP}<span>Upload</span></a>
  </nav>
</header>
<main>{body}</main>
<footer class="footer">
  <div class="footer-inner">
    <p><b>OpenTube</b> — a demo video-sharing platform. Sample clips are open-licensed films from the
    Blender Foundation (CC BY) and procedurally generated shorts. Upload only content you own or have
    permission to share.</p>
  </div>
</footer>
<script src="/static/app.js"></script>
</body>
</html>"""


def tag_chips(tags, limit=3):
    return "".join(f'<span class="chip">{E(t)}</span>' for t in tags[:limit])


def card(v):
    return f"""<a class="card" href="/watch/{v['id']}">
  <div class="thumb">
    <img src="/thumbs/{E(v['thumb'])}" alt="" loading="lazy">
    <span class="dur">{fmt_duration(v['duration'])}</span>
    <span class="play-overlay">{ICON_PLAY}</span>
  </div>
  <div class="card-body">
    <h3>{E(v['title'])}</h3>
    <div class="card-meta">{fmt_count(v['views'])} views · {ago(v['created_at'])}</div>
    <div class="card-tags">{tag_chips(v['tags'])}</div>
  </div>
</a>"""


def grid(videos):
    return '<div class="grid">' + "".join(card(v) for v in videos) + "</div>"


def page_home(videos, total, q="", category="", tag="", sort="new", page=1, per_page=12):
    s = db.stats()
    chips = [("", "All")] + [(c, c) for c in db.CATEGORIES]
    chip_html = "".join(
        f'<a class="chip{" on" if category == c else ""}" href="/?{urlencode({"category": c}) if c else ""}">'
        f'{E(label)}</a>' for c, label in chips)
    popular_tags = db.top_tags(12)
    tag_html = "".join(
        f'<a class="chip tag-chip{" on" if tag == t["name"] else ""}" href="/?tag={E(t["name"])}">'
        f'#{E(t["name"])} <span>{t["n"]}</span></a>' for t in popular_tags)

    heading = "Trending now" if sort == "popular" else "Fresh uploads"
    if q:
        heading = f'Results for “{q}”'
    if category:
        heading = category
    if tag:
        heading = f"#{tag}"

    pages = max(1, -(-total // per_page))
    def page_link(n):
        params = {"page": n}
        if q: params["q"] = q
        if category: params["category"] = category
        if tag: params["tag"] = tag
        if sort != "new": params["sort"] = sort
        return "/?" + urlencode(params)
    pager = ""
    if pages > 1:
        parts = []
        if page > 1:
            parts.append(f'<a class="page-btn" href="{E(page_link(page - 1))}">Prev</a>')
        for n in range(1, pages + 1):
            if n == 1 or n == pages or abs(n - page) <= 2:
                parts.append(f'<a class="page-btn{" on" if n == page else ""}" href="{E(page_link(n))}">{n}</a>')
            elif parts and parts[-1] != '<span class="page-gap">…</span>':
                parts.append('<span class="page-gap">…</span>')
        if page < pages:
            parts.append(f'<a class="page-btn" href="{E(page_link(page + 1))}">Next</a>')
        pager = '<div class="pager">' + "".join(parts) + "</div>"

    sort_tabs = (f'<div class="sort-tabs">'
                 f'<a class="{"on" if sort != "popular" else ""}" href="/?{urlencode({"q": q, "category": category, "tag": tag})}">Newest</a>'
                 f'<a class="{"on" if sort == "popular" else ""}" href="/?{urlencode({"q": q, "category": category, "tag": tag, "sort": "popular"})}">Most viewed</a>'
                 f'</div>')

    body = f"""
<section class="hero">
  <div>
    <p class="eyebrow">Open-licensed streaming</p>
    <h1>Watch, share and discover <span>free video</span>.</h1>
    <p class="hero-sub">A demo tube built with nothing but Python's standard library. Every clip here is legal to share.</p>
    <div class="hero-stats">
      <span><b>{s['videos']}</b> videos</span>
      <span><b>{fmt_count(s['views'])}</b> views</span>
      <span><b>{fmt_count(s['comments'])}</b> comments</span>
    </div>
  </div>
  <a class="hero-cta" href="/upload">Upload a video</a>
</section>

<div class="chips">{chip_html}</div>
<div class="tagline"><span>Popular tags</span>{tag_html}</div>

<div class="section-head"><h2>{E(heading)}</h2>{sort_tabs}</div>
{grid(videos) if videos else '<div class="empty">No videos found. Try a different search or <a href="/upload">upload one</a>.</div>'}
{pager}
"""
    return layout("Watch free video", body, q=q, active="trending" if sort == "popular" else "home")


def page_watch(v, rel, cmts):
    like_btn = (f'<button class="action like-btn" data-id="{v["id"]}">{ICON_LIKE}'
                f'<span class="like-count">{fmt_count(v["likes"])}</span></button>')
    tag_html = "".join(f'<a class="chip" href="/?tag={E(t)}">#{E(t)}</a>' for t in v["tags"])
    desc = E(v["description"]).replace("\n", "<br>") or "<em>No description.</em>"
    comment_html = "".join(
        f'<li class="comment"><div class="avatar">{E((c["author"] or "?")[:1].upper())}</div>'
        f'<div><div class="c-head"><b>{E(c["author"])}</b><span>{ago(c["created_at"])}</span></div>'
        f'<p>{E(c["body"]).replace(chr(10), "<br>")}</p></div></li>' for c in cmts)
    rel_html = "".join(
        f'<a class="mini" href="/watch/{r["id"]}"><img src="/thumbs/{E(r["thumb"])}" alt="" loading="lazy">'
        f'<div><h4>{E(r["title"])}</h4><div class="mini-meta">{fmt_count(r["views"])} views · {ago(r["created_at"])}</div></div></a>'
        for r in rel)

    body = f"""
<div class="watch">
  <div class="watch-main">
    <div class="player-wrap">
      <video id="player" controls playsinline preload="metadata" poster="/thumbs/{E(v['thumb'])}">
        <source src="/media/{E(v['filename'])}">
      </video>
    </div>
    <h1 class="watch-title">{E(v['title'])}</h1>
    <div class="watch-meta">
      <div class="meta-left">
        <span data-views="{v['views']}">{fmt_count(v['views'])} views</span><span>{ago(v['created_at'])}</span>
        <a class="badge" href="/?category={E(v['category'])}">{E(v['category'])}</a>
      </div>
      <div class="actions">
        {like_btn}
        <button class="action copy-btn" data-path="/watch/{v['id']}">Copy link</button>
      </div>
    </div>
    <div class="channel-row">
      <div class="avatar big">O</div>
      <div><b>OpenTube Library</b><div class="muted">{fmt_duration(v['duration'])} · open license</div></div>
    </div>
    <div class="description"><p>{desc}</p><div class="card-tags">{tag_html}</div></div>

    <section class="comments">
      <h2>{len(cmts)} comment{'s' if len(cmts) != 1 else ''}</h2>
      <form class="comment-form" action="/comment/{v['id']}" method="post">
        <input name="author" maxlength="40" placeholder="Your name" required>
        <textarea name="body" rows="3" maxlength="2000" placeholder="Add a comment…" required></textarea>
        <button class="btn" type="submit">Comment</button>
      </form>
      <ul class="comment-list">{comment_html or '<li class="muted">No comments yet. Start the conversation.</li>'}</ul>
    </section>
  </div>
  <aside class="watch-aside">
    <h2 class="aside-title">Up next</h2>
    <div class="mini-list">{rel_html or '<p class="muted">Nothing else here yet.</p>'}</div>
  </aside>
</div>
"""
    return layout(v["title"], body)


def page_upload(error=""):
    cats = "".join(f"<option>{E(c)}</option>" for c in db.CATEGORIES)
    err = f'<div class="alert">{E(error)}</div>' if error else ""
    body = f"""
<section class="upload-page">
  <div class="upload-card">
    <h1>Upload a video</h1>
    <p class="muted">By uploading you confirm you own the rights or have permission to share this video.</p>
    {err}
    <form action="/upload" method="post" enctype="multipart/form-data" class="upload-form">
      <label>Video file
        <input type="file" name="file" accept="video/mp4,video/webm,video/ogg,video/quicktime,video/x-matroska,.mp4,.webm,.ogv,.mov,.mkv" required>
        <span class="hint">MP4, WebM, OGV, MOV or MKV · up to 1 GB</span>
      </label>
      <label>Title
        <input name="title" maxlength="120" required placeholder="Give your video a title">
      </label>
      <div class="form-row">
        <label>Category
          <select name="category">{cats}</select>
        </label>
        <label>Tags
          <input name="tags" maxlength="200" placeholder="comma, separated, tags">
        </label>
      </div>
      <label>Description
        <textarea name="description" rows="4" maxlength="4000" placeholder="Tell viewers about your video"></textarea>
      </label>
      <button class="btn primary" type="submit">Publish</button>
    </form>
  </div>
</section>
"""
    return layout("Upload", body)


def page_404():
    body = """
<section class="notfound">
  <h1>404</h1>
  <p>That video wandered off. <a href="/">Back to the homepage</a>.</p>
</section>
"""
    return layout("Not found", body)


def page_error(code, message):
    body = f"""
<section class="notfound">
  <h1>{E(code)}</h1>
  <p>{E(message)} <a href="/">Back home</a>.</p>
</section>
"""
    return layout(str(code), body)
