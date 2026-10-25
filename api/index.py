import sys
import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.main import app as fastapi_app


async def app(scope, receive, send):
    """
    ASGI middleware wrapper untuk Vercel Serverless environment:
    - Menangani URL rewrite dari Vercel edge di mana request path dialihkan ke entrypoint.
    - Memulihkan path asli dari header 'x-matched-path' atau 'x-forwarded-uri' yang diinjeksi Vercel.
    """
    if scope.get("type") == "http":
        headers = dict(scope.get("headers", []))
        raw_target = headers.get(b"x-matched-path") or headers.get(b"x-forwarded-uri")
        if raw_target:
            real_path = raw_target.decode("latin-1", errors="ignore").split("?")[0]
            if real_path and real_path != scope.get("path"):
                scope["path"] = real_path
                scope["raw_path"] = real_path.encode("ascii", errors="ignore")
        elif scope.get("path") in ("/api/index.py", "/api/index", "/api"):
            scope["path"] = "/"
            scope["raw_path"] = b"/"

    await fastapi_app(scope, receive, send)
