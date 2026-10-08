import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("TD2S_DATA_DIR", BACKEND_DIR / "data"))
OUTPUT_DIR = Path(os.environ.get("TD2S_OUTPUT_DIR", BACKEND_DIR / "output"))
DB_PATH = Path(os.environ.get("TD2S_DB_PATH", DATA_DIR / "jobs.db"))
SOURCES_DIR = DATA_DIR / "sources"
CLONE_TIMEOUT_SECONDS = int(os.environ.get("TD2S_CLONE_TIMEOUT", "120"))
# Allow file:// and local-path sources (used by tests and offline demos).
ALLOW_LOCAL_REPOS = os.environ.get("TD2S_ALLOW_LOCAL_REPOS", "0") == "1"
CORS_ORIGINS = os.environ.get("TD2S_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")
