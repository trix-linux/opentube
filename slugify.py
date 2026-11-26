import re
import secrets


def slugify(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:60] or "video") + "-" + secrets.token_hex(3)
