import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()

class Settings(BaseSettings):
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    CHROMA_PATH: str = os.getenv("CHROMA_PATH", "chroma/")
    COLLECTION_NAME: str = os.getenv("COLLECTION_NAME", "pdf_docs")
    JWT_SECRET: str = os.getenv("JWT_SECRET", "supersecretkey")
    JWT_ALGORITHM: str = os.getenv("JWT_ALGORITHM", "HS256")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))
    
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "openai")
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
    EMBEDDING_MODEL: str = os.getenv("EMBEDDING_MODEL", "text-embedding-3-large")
    CHAT_MODEL: str = os.getenv("CHAT_MODEL", "gpt-4o")

settings = Settings()
