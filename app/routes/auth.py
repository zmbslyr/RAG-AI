# app/routes/auth.py
import os
from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
from typing import Optional
from pydantic import BaseModel
from sqlalchemy.orm import Session

# Local imports
from app.core.security import (
    get_password_hash,
    verify_password,
    create_access_token
)
from app.core.settings import settings
from app import models
from app.core.deps import get_db

# === Config ===
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

router = APIRouter(prefix="/auth", tags=["auth"])

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)

# === Helpers ===
def get_user(db: Session, username: str):
    return db.query(models.User).filter(models.User.username == username).first()

def authenticate_user(db: Session, username: str, password: str):
    user = get_user(db, username)
    if not user:
        return False
    if not verify_password(password, user.hashed_password):
        return False
    return user

# === Request models ===
class RegisterRequest(BaseModel):
    username: str
    password: str

# === Routes ===
@router.post("/register")
async def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    """Register a new user and save to users.json (accepts JSON)."""
    username = payload.username.strip()
    password = payload.password.strip()

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password are required.")
    if len(password) > 72:
        raise HTTPException(status_code=400, detail="Password too long (max 72 characters).")
    user = get_user(db, username=username)
    if user:
        raise HTTPException(status_code=400, detail="Username already exists.")

    new_user = models.User(
        username=username,
        hashed_password=get_password_hash(password),
        role="user"  # Default role
    )
    # Transaction
    db.add(new_user)
    db.commit()      # Saves to app.db
    db.refresh(new_user) # Reloads attributes (like auto-generated ID)

    print(f"""
        User: {username} created.
        Password saved.
        Created at: {datetime.now().isoformat()}.
        """
        )

    return {"message": f"User '{username}' registered successfully."}

@router.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """Authenticate and return JWT."""
    # Pass 'db' into the helper
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    
    access_token = create_access_token(
        data={"sub": user.username, "role": user.role},
        expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

async def get_current_user(
    request: Request, 
    token: Optional[str] = Depends(oauth2_scheme), 
    db: Session = Depends(get_db)
):
    # Check header for token, if not found, checks cookies for access token
    if not token:
        token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    
    """Extract and verify current user from JWT token."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.")
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.")
    
    user = get_user(db, username=username)

    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.")
    
    return {
        "username": user.username, 
        "role": user.role,
        "id": user.id
    }

@router.post("/logout")
async def logout(current_user: dict = Depends(get_current_user)):
    """Log the user out (informational only)."""
    print(f"\n{current_user['username']} has logged out at {datetime.now().isoformat()}\n")
    return {"message": "Logout logged successfully"}

async def require_admin(user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admins only.")
    return user
