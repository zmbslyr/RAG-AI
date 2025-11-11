from app.core.db import collection

def query_collection(
    query_embeddings=None,
    query_embedding=None,
    where=None,
    n_results=10,
    include=None
):
    """Wrapper around collection.query() that supports both single or multi-query style."""
    # backward compatibility: allow either `query_embedding` or `query_embeddings`
    if query_embeddings is None and query_embedding is not None:
        query_embeddings = [query_embedding]

    return collection.query(
        query_embeddings=query_embeddings,
        where=where if where else None,
        n_results=n_results,
        include=include or ["documents", "metadatas"]
    )

def add_to_collection(ids, embeddings, metadatas, documents):
    collection.add(
        ids=ids,
        embeddings=embeddings,
        metadatas=metadatas,
        documents=documents
    )

def delete_from_collection(file_id: str):
    collection.delete(where={"file_id": file_id})

def list_metadata():
    return collection.get(include=["metadatas"])
