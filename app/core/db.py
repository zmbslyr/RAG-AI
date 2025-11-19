# app/core/db.py
import chromadb
import json
from pathlib import Path
from openai import OpenAI
from app.core.settings import settings

# Determine project root (RAG AI/)
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# Path to /databases folder
DB_ROOT = BASE_DIR / "databases"
DB_ROOT.mkdir(parents=True, exist_ok=True)

# Path to persistent active DB file
ACTIVE_DB_FILE = DB_ROOT / "active_db.json"

DEFAULT_DB = "books"


def save_active_db(name: str):
    ACTIVE_DB_FILE.write_text(json.dumps({"active": name}), encoding="utf-8")


def load_active_db_name():
    if ACTIVE_DB_FILE.exists():
        try:
            data = json.loads(ACTIVE_DB_FILE.read_text(encoding="utf-8"))
            return data.get("active", DEFAULT_DB)
        except:
            return DEFAULT_DB
    else:
        return DEFAULT_DB


# Load stored DB name (or default)
ACTIVE_DB_NAME = load_active_db_name()

client_openai = OpenAI(api_key=settings.OPENAI_API_KEY)


def load_database(name: str):
    global ACTIVE_DB_NAME, chroma_client, collection

    ACTIVE_DB_NAME = name
    save_active_db(name)  # persist selection

    db_path = DB_ROOT / name
    db_path.mkdir(parents=True, exist_ok=True)

    print(f"[DB] Loading Chroma DB: {db_path}")

    chroma_client = chromadb.PersistentClient(path=str(db_path))
    collection = chroma_client.get_or_create_collection(settings.COLLECTION_NAME)

    print(f"[DB] Active DB = {ACTIVE_DB_NAME}")


# Load the selected database
load_database(ACTIVE_DB_NAME)
