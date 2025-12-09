from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey
from sqlalchemy.sql import func
from app.core.authdb import Base

# Store user as SQL object
class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    role = Column(String, default="user")
    created_at = Column(DateTime(timezone=True), server_default=func.now())

# Store chat history as SQL object
class ChatHistory(Base):
    __tablename__ = "chat_history"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, index=True) # "default" or a uuid
    role = Column(String) # "user" or "assistant"
    content = Column(Text) # The actual text
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

# Simple Audit Log
class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, index=True)
    action = Column(String) # e.g., "UPLOAD_FILE", "DELETE_FILE"
    details = Column(String, nullable=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())