# app/routes/auth.py
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from passlib.context import CryptContext
from jose import JWTError, jwt
from datetime import datetime, timedelta
from typing import Optional
from pathlib import Path
from pydantic import BaseModel
import json

# === Setup paths ===
USERS_DIR = Path("app/users")
USERS_FILE = USERS_DIR / "users.json"
USERS_DIR.mkdir(parents=True, exist_ok=True)

# --- User storage helpers ---
def load_users():
    if USERS_FILE.exists():
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

def save_users(data):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

users_db = load_users()

# === Config ===
SECRET_KEY = "supersecretkey"  # change for production
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

router = APIRouter(prefix="/auth", tags=["auth"])

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

# === Helpers ===
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    if not isinstance(password, str):
        raise ValueError("Password must be a string.")
    # bcrypt limit
    password = password[:72]
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_user(username: str):
    return users_db.get(username)

def authenticate_user(username: str, password: str):
    user = get_user(username)
    if not user or not verify_password(password, user["hashed_password"]):
        return None
    return user

# === Request models ===
class RegisterRequest(BaseModel):
    username: str
    password: str

# === Routes ===
@router.post("/register")
async def register(payload: RegisterRequest):
    """Register a new user and save to users.json (accepts JSON)."""
    username = payload.username.strip()
    password = payload.password.strip()

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password are required.")
    if len(password) > 72:
        raise HTTPException(status_code=400, detail="Password too long (max 72 characters).")
    if username in users_db:
        raise HTTPException(status_code=400, detail="Username already exists.")

    users_db[username] = {
        "username": username,
        "hashed_password": get_password_hash(password),
        "created_at": datetime.utcnow().isoformat()
    }
    save_users(users_db)

    return {"message": f"User '{username}' registered successfully."}



@router.post("/token")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """Authenticate and return JWT."""
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user["username"]}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}


async def get_current_user(token: str = Depends(oauth2_scheme)):
    """Extract and verify current user from JWT token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None or username not in users_db:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.")
        return users_db[username]
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials.")
