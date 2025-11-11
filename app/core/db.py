import chromadb
from openai import OpenAI

# Local imports
from app.core.settings import settings

# --- Chroma client ---
chroma_client = chromadb.PersistentClient(path=settings.CHROMA_PATH)
collection = chroma_client.get_or_create_collection(settings.COLLECTION_NAME)

# --- OpenAI client ---
client_openai = OpenAI(api_key=settings.OPENAI_API_KEY)
print("API key initialized. Loading Database...")
