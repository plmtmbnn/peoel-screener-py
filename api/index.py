import sys
import os
from pathlib import Path

# Tambahkan direktori root project ke sys.path agar package 'app' dapat ditemukan oleh runtime Vercel
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.main import app  # ASGI app handler yang dieksekusi Vercel
