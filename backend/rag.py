"""
RAG retriever for Scam Sentinel.
Indexes real FTC/APWG scam cases and retrieves similar past cases at inference time.
Uses ChromaDB's built-in embedding function (avoids sentence-transformers GPU conflicts on Windows).
"""

import json
from pathlib import Path
from typing import Any

RAG_CASES_PATH = Path("data/rag_cases.jsonl")
VECTOR_STORE_PATH = Path("data/vector_store")
COLLECTION_NAME = "scam_cases"


class ScamCaseRetriever:
    def __init__(self, top_k: int = 3):
        import chromadb
        from chromadb.utils import embedding_functions

        self.top_k = top_k
        self.ef = embedding_functions.DefaultEmbeddingFunction()
        self.client = chromadb.PersistentClient(path=str(VECTOR_STORE_PATH))
        self.collection = self.client.get_or_create_collection(
            COLLECTION_NAME, embedding_function=self.ef
        )

    def retrieve(self, query: str) -> list[dict[str, Any]]:
        if not query.strip():
            return []
        count = self.collection.count()
        if count == 0:
            return []
        n = min(self.top_k, count)
        results = self.collection.query(query_texts=[query], n_results=n)
        cases = []
        for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
            cases.append({
                "title": meta.get("title", ""),
                "summary": doc,
                "outcome": meta.get("outcome", ""),
                "year": meta.get("year", ""),
            })
        return cases


def build_index() -> None:
    """Index all cases from rag_cases.jsonl into ChromaDB."""
    import chromadb
    from chromadb.utils import embedding_functions

    print("Loading cases...")
    cases = []
    with open(RAG_CASES_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    print(f"  Loaded {len(cases)} cases")

    VECTOR_STORE_PATH.mkdir(parents=True, exist_ok=True)
    ef = embedding_functions.DefaultEmbeddingFunction()
    client = chromadb.PersistentClient(path=str(VECTOR_STORE_PATH))

    # Recreate collection to ensure clean state
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    collection = client.create_collection(COLLECTION_NAME, embedding_function=ef)

    print("Embedding and indexing (using chromadb default embedder)...")
    ids, documents, metadatas = [], [], []
    for case in cases:
        text = f"{case['summary']} Patterns: {', '.join(case.get('patterns', []))}"
        ids.append(case["case_id"])
        documents.append(text)
        metadatas.append({
            "title": case["title"],
            "outcome": case["outcome"],
            "year": str(case["year"]),
            "category": case["category"],
        })

    collection.add(ids=ids, documents=documents, metadatas=metadatas)
    print(f"Indexed {len(cases)} cases into ChromaDB at {VECTOR_STORE_PATH}")
    print(f"Collection count: {collection.count()}")


if __name__ == "__main__":
    build_index()
