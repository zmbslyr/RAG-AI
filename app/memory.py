# app/memory.py
from collections import deque

# --- Simple short-term memory store ---
session_memory = {}
MAX_MEMORY_TURNS = 5  # Keep only last 5 exchanges per session

def get_session_context(session_id: str):
    """Return concatenated short-term memory for this session."""
    memory = session_memory.get(session_id, deque(maxlen=MAX_MEMORY_TURNS))
    return "\n".join([f"User: {m['user']}\nAssistant: {m['assistant']}" for m in memory])

def update_session_memory(session_id: str, user_text: str, assistant_text: str):
    """Add new turn to memory."""
    if session_id not in session_memory:
        session_memory[session_id] = deque(maxlen=MAX_MEMORY_TURNS)
    session_memory[session_id].append({
        "user": user_text,
        "assistant": assistant_text
    })

# --- Track last active file per session ---
active_file_memory = {}  # {session_id: filename}

def get_last_active_file(session_id: str):
    """Return the last file used in this session."""
    return active_file_memory.get(session_id)

def set_last_active_file(session_id: str, filename: str):
    """Remember the file name for later follow-ups."""
    active_file_memory[session_id] = filename

