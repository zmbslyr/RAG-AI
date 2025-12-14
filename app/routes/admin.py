# app/routes/admin.py
from fastapi import APIRouter, Depends, HTTPException, Request, Body
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pathlib import Path
import re
import shutil

# Local imports
from app.core.deps import get_db
from app.routes.auth import require_admin
from app import models
from app.core import db as db_core
from app.services.chroma_service import delete_from_collection
from app.routes.list_files import list_files
from app.core.security import get_password_hash

router = APIRouter(prefix="/admin", tags=["admin"])

# Setup templates
BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

# --- Serve the UI ---
@router.get("/", response_class=HTMLResponse)
async def admin_panel(request: Request, user=Depends(require_admin)):
    """Serve the Admin HTML page (Admins only)."""
    return templates.TemplateResponse("admin.html", {"request": request, "user": user})

# --- User Management ---
@router.get("/users")
async def list_users(db: Session = Depends(get_db), user=Depends(require_admin)):
    users = db.query(models.User).all()
    return [{"id": u.id, "username": u.username, "role": u.role, "created_at": u.created_at} for u in users]

@router.post("/users")
async def create_user_admin(payload: dict = Body(...), db: Session = Depends(get_db), user=Depends(require_admin)):
    """Create a new user manually."""
    username = payload.get("username", "").strip()
    password = payload.get("password", "").strip()
    role = payload.get("role", "user")

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password are required.")
    
    if len(password) < 4:
         raise HTTPException(status_code=400, detail="Password must be at least 4 characters.")

    # Check if exists
    existing = db.query(models.User).filter(models.User.username == username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists.")
    
    new_user = models.User(
        username=username,
        hashed_password=get_password_hash(password),
        role=role
    )
    db.add(new_user)
    db.commit()
    return {"message": f"User '{username}' created."}

@router.delete("/users/{user_id}")
async def delete_user(user_id: int, db: Session = Depends(get_db), user=Depends(require_admin)):
    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.username == "admin":
         raise HTTPException(status_code=400, detail="Cannot delete the root admin.")
    
    db.delete(target)
    db.commit()
    return {"message": f"User {target.username} deleted."}

@router.put("/users/{user_id}/promote")
async def promote_user(user_id: int, db: Session = Depends(get_db), user=Depends(require_admin)):
    """Promote a user to Admin."""
    target = db.query(models.User).filter(models.User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    
    target.role = "admin"
    db.commit()
    return {"message": f"User {target.username} is now an Admin."}

# --- Database Management (NEW) ---
@router.post("/create_database")
async def create_database(payload: dict = Body(...), user=Depends(require_admin)):
    """Create a new folder in the databases directory."""
    name = payload.get("name", "").strip()
    
    # Validation: Alphanumeric and underscores only, 3-20 chars
    if not name or not re.match(r"^[a-zA-Z0-9_]{3,20}$", name):
        raise HTTPException(status_code=400, detail="Invalid name. Use 3-20 letters/numbers/underscores only.")
    
    new_db_path = db_core.DB_ROOT / name
    
    if new_db_path.exists():
        raise HTTPException(status_code=400, detail="Database already exists.")
    
    try:
        new_db_path.mkdir(parents=True, exist_ok=False)
        return {"message": f"Database '{name}' created successfully."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error creating database: {str(e)}")
    
@router.get("/databases")
async def list_databases_admin(user=Depends(require_admin)):
    """List all database folders."""
    if not db_core.DB_ROOT.exists():
        return []
    
    # Return list of folder names
    dbs = [p.name for p in db_core.DB_ROOT.iterdir() if p.is_dir()]
    return sorted(dbs)

@router.delete("/databases/{name}")
async def delete_database(name: str, user=Depends(require_admin)):
    """Delete a database folder (Cannot delete the Active one)."""
    
    # Safety Checks
    if name == db_core.ACTIVE_DB_NAME:
        raise HTTPException(status_code=400, detail="Cannot delete the currently ACTIVE database. Switch to another one first.")
    
    target_path = db_core.DB_ROOT / name
    
    if not target_path.exists():
        raise HTTPException(status_code=404, detail="Database not found.")

    # Nuke it
    try:
        shutil.rmtree(target_path)
        return {"message": f"Database '{name}' deleted."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting database: {str(e)}")

# --- System Logs ---
@router.get("/logs")
async def get_system_logs(limit: int = 200, db: Session = Depends(get_db), user=Depends(require_admin)):
    """Fetch recent chat history (Limit increased to 200)."""
    active_suffix = f"-{db_core.ACTIVE_DB_NAME}"
    
    logs = (
        db.query(models.ChatHistory)
        .filter(models.ChatHistory.session_id.like(f"%{active_suffix}"))
        .order_by(models.ChatHistory.timestamp.desc())
        .limit(limit)
        .all()
    )
    return logs

@router.delete("/logs")
async def clear_logs(db: Session = Depends(get_db), user=Depends(require_admin)):
    """Nuke chat history for this specific database."""
    active_suffix = f"-{db_core.ACTIVE_DB_NAME}"
    db.query(models.ChatHistory)\
      .filter(models.ChatHistory.session_id.like(f"%{active_suffix}"))\
      .delete(synchronize_session=False)
    db.commit()
    return {"message": "Chat logs cleared for active database."}

# --- Danger Zone ---
@router.delete("/reset_chroma")
async def reset_chroma(user=Depends(require_admin)):
    """Delete ALL files in the Chroma Vector DB."""
    files_data = await list_files()
    files = files_data.get("files", [])
    count = 0
    for f in files:
        file_id = f.get("file_id")
        if file_id:
            try:
                delete_from_collection(file_id)
                count += 1
            except Exception as e:
                print(f"[ADMIN] Error deleting {file_id}: {e}")
    return {"message": f"Wiped {count} files from ChromaDB."}
