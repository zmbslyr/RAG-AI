# app/main.py

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from pathlib import Path

import importlib
import pkgutil

from app import routes
from app.config import collection

# Initialize app
app = FastAPI()

# Dynamically load all routes in app/routes
for _, module_name, _ in pkgutil.iter_modules(routes.__path__):
    module = importlib.import_module(f"app.routes.{module_name}")
    if hasattr(module, "router"):
        app.include_router(module.router)

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

# templates is an object that allows jinja to know wherer to read templates from
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# this loads the web page when accessed through the browser
@app.get("/", response_class=HTMLResponse) #FastAPI expects JSON by default so we must specify HTML
def serve_index(request: Request): #The request object is created and passed to this function in the background by FastAPI, populated by the HTTP metadata
    return templates.TemplateResponse("index.html", {"request": request})


# MOSTLY VESTIGIAL. Working on a more thorough debug route, with better display parameters
@app.get("/debug_metadata")
async def debug_metadata():
    """Inspect what metadata actually exists inside Chroma."""
    results = collection.get(include=["metadatas", "documents"], limit=5)
    metas = results.get("metadatas", [])
    print("\n\n=== METADATA DEBUG ===")
    for i, m in enumerate(metas[:10]):
        print(f"[{i}] {m}")
    print("======================\n\n")
    return metas
