# app/main.py
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pathlib import Path
import importlib
import pkgutil

# Local imports
from app import routes
from fastapi import Depends
from app.core import db as db_core
from app.routes.auth import require_admin
from app.memory import clear_all_active_files

# Initialize app
app = FastAPI()

# Dynamically load all routes in app/routes
for _, module_name, _ in pkgutil.iter_modules(routes.__path__):
    module = importlib.import_module(f"app.routes.{module_name}")
    if hasattr(module, "router"):
        app.include_router(module.router)

# === Database Management Routes ===
@app.get("/databases")
def list_databases():
    """Return available Chroma database folders."""
    return {
        "databases": [p.name for p in db_core.DB_ROOT.iterdir() if p.is_dir()]
    }

@app.get("/active_database")
def get_active_database():
    """Return currently active database (live from db.py)."""
    return {"active": db_core.ACTIVE_DB_NAME}

@app.post("/set_database")
def set_database(name: str, user=Depends(require_admin)):
    """Switch active database (admin only)."""
    db_core.load_database(name)
    # Clear active files when database resets
    clear_all_active_files()
    return {"message": f"Active database switched to {name}"}

# --- Paths (make sure they point to app/static and app/templates) ---
#__file__ refers to the current file 
#.resolve ensures full path with no /../ 
#.parent removes the file name from the path, returning a path variable to the folder which contains the file.
BASE_DIR = Path(__file__).resolve().parent

# mounting allows the app to use files found on the disk at the specified location. This allows the HTML to load.
app.mount(
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static"
)

# --- Mount uploaded files so PDFs can be viewed ---
app.mount(
    "/uploads",
    StaticFiles(directory="uploads"),
    name="uploads"
)

# templates is an object that allows jinja to know wherer to read templates from
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# this loads the web page when accessed through the browser
@app.get("/", response_class=HTMLResponse) #FastAPI expects JSON by default so we must specify HTML
def serve_index(request: Request): #The request object is created and passed to this function in the background by FastAPI, populated by the HTTP metadata
    return templates.TemplateResponse("index.html", {"request": request})
