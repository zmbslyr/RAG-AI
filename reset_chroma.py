# reset_chroma.py
import chromadb
import os
from dotenv import load_dotenv

# Load environment variables (in case your Chroma path or OpenAI key is there)
load_dotenv()

# Optional: If you use a persistent directory for Chroma
# (for example "./chroma" or "./data/chroma")
PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./chroma")

# Connect to Chroma client
client = chromadb.PersistentClient(path=PERSIST_DIR)

# Name of the collection you want to reset
COLLECTION_NAME = "embeddings"

# --- Step 1: Check if it exists ---
collections = [c.name for c in client.list_collections()]
if COLLECTION_NAME in collections:
    print(f"🧹 Deleting existing collection '{COLLECTION_NAME}'...")
    client.delete_collection(COLLECTION_NAME)
    print("Collection deleted.")
else:
    print(f"ℹNo existing collection named '{COLLECTION_NAME}' found.")

# --- Step 2: Recreate it cleanly ---
print(f"Creating new collection '{COLLECTION_NAME}'...")
collection = client.create_collection(COLLECTION_NAME)
print("New collection created successfully!")

# --- Optional sanity check ---
print("\nCurrent collections:")
for c in client.list_collections():
    print(" •", c.name)

print("\nDone. You can now re-run your upload script to rebuild embeddings.")
