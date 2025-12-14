# app/memory.py
from sqlalchemy.orm import Session
from app import models

# --- Persistent Chat Memory (SQLite) ---

def get_session_context(db: Session, session_id: str, limit: int = 5):
    """
    Return concatenated short-term memory for this session from the database.
    Fetches the last 'limit' exchanges (user + assistant).
    """
    # Query the last N messages for this session, ordered by time
    # We multiply limit by 2 because one "turn" = User + Assistant
    messages = (
        db.query(models.ChatHistory)
        .filter(models.ChatHistory.session_id == session_id)
        .order_by(models.ChatHistory.timestamp.desc())
        .limit(limit * 2) 
        .all()
    )

    # --- DEBUG PRINT ---
    print(f"\n[MEMORY DEBUG] Session ID: {session_id}")
    print(f"[MEMORY DEBUG] Found {len(messages)} rows in DB.")
    for m in messages:
        print(f" - {m.role}: {m.content[:50]}...") # Print first 50 chars
    print("----------------\n")
    # -------------------
    
    # The query returns newest first (descending), so we reverse them 
    # to reconstruct the conversation flow (oldest -> newest).
    messages.reverse()

    # Format as text
    context_lines = []
    for msg in messages:
        role_label = "User" if msg.role == "user" else "Assistant"
        context_lines.append(f"{role_label}: {msg.content}")
        
    return "\n".join(context_lines)

def update_session_memory(db: Session, session_id: str, user_text: str, assistant_text: str):
    """
    Save the new turn (User + Assistant) to the database.
    """
    # Create User Message
    user_msg = models.ChatHistory(
        session_id=session_id,
        role="user",
        content=user_text
    )
    db.add(user_msg)
    
    # Create Assistant Message
    asst_msg = models.ChatHistory(
        session_id=session_id,
        role="assistant",
        content=assistant_text
    )
    db.add(asst_msg)
    
    db.commit()

# --- Ephemeral State (Keep in RAM for now) ---
# It is okay if the "last active file" resets on reboot.
active_file_memory = {}  # {session_id: filename}

def get_last_active_file(session_id: str):
    """Return the last file used in this session."""
    return active_file_memory.get(session_id)

def set_last_active_file(session_id: str, filename: str):
    """Remember the file name for later follow-ups."""
    active_file_memory[session_id] = filename

def clear_all_active_files():
    """Clear active file context for all sessions."""
    active_file_memory.clear()
    print("\n==========\n[DEBUG] active_file cleared\n==========\n")