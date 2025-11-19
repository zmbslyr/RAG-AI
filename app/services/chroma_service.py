from app.core import db
from app.core.db import load_database, ACTIVE_DB_NAME

def query_collection(query_embeddings=None, where=None, n_results=10, include=None):
    # CHANGE: Access db.collection dynamically
    return db.collection.query(
        query_embeddings=query_embeddings,
        where=where if where else None,
        n_results=n_results,
        include=include or ["documents", "metadatas"]
    )

def add_to_collection(ids, embeddings, metadatas, documents):
    # CHANGE: Access db.collection dynamically
    db.collection.add(
        ids=ids,
        embeddings=embeddings,
        metadatas=metadatas,
        documents=documents
    )

def delete_from_collection(file_id: str):
    # CHANGE: Access db.collection dynamically
    db.collection.delete(where={"file_id": file_id})

def list_metadata():
    return db.collection.get(include=["metadatas"])
