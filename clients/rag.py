from __future__ import annotations

import io

import chromadb
import httpx
from pypdf import PdfReader
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("all-MiniLM-L6-v2")

_solicitations_col: chromadb.Collection | None = None
_past_performance_col: chromadb.Collection | None = None


def init_collections(client: chromadb.ClientAPI | None = None) -> None:
    global _solicitations_col, _past_performance_col
    if client is None:
        client = chromadb.PersistentClient(path="./.chroma")
    _solicitations_col = client.get_or_create_collection(
        "solicitations", metadata={"hnsw:space": "cosine"}
    )
    _past_performance_col = client.get_or_create_collection(
        "past_performance", metadata={"hnsw:space": "cosine"}
    )


def _get_solicitations() -> chromadb.Collection:
    if _solicitations_col is None:
        init_collections()
    return _solicitations_col  # type: ignore[return-value]


def _get_past_performance() -> chromadb.Collection:
    if _past_performance_col is None:
        init_collections()
    return _past_performance_col  # type: ignore[return-value]


def _chunk_text(text: str, chunk_size: int = 400, overlap: int = 50) -> list[str]:
    words = text.split()
    if len(words) <= chunk_size:
        return [text]
    chunks = []
    step = chunk_size - overlap
    for start in range(0, len(words), step):
        chunk = words[start : start + chunk_size]
        chunks.append(" ".join(chunk))
        if start + chunk_size >= len(words):
            break
    return chunks


def _embed(texts: list[str]) -> list[list[float]]:
    return model.encode(texts, convert_to_numpy=True).tolist()


def ingest_solicitation_pdf(
    pdf_url: str,
    notice_id: str,
    metadata: dict,
) -> dict:
    try:
        with httpx.Client(timeout=60) as client:
            resp = client.get(pdf_url)
            resp.raise_for_status()
            pdf_bytes = resp.content
    except httpx.HTTPError as exc:
        return {"notice_id": notice_id, "error": f"Failed to download PDF: {exc}"}

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        return {"notice_id": notice_id, "error": f"Failed to parse PDF: {exc}"}

    if not text or len(text) < 100:
        return {"notice_id": notice_id, "error": "Could not extract text from PDF"}

    chunks = _chunk_text(text)
    embeddings = _embed(chunks)

    col = _get_solicitations()
    ids = [f"{notice_id}_chunk_{i}" for i in range(len(chunks))]
    metas = [
        {
            "notice_id": notice_id,
            **{k: str(v) for k, v in metadata.items()},
            "chunk_index": i,
            "total_chunks": len(chunks),
        }
        for i in range(len(chunks))
    ]
    col.upsert(ids=ids, embeddings=embeddings, documents=chunks, metadatas=metas)

    return {
        "notice_id": notice_id,
        "chunks_ingested": len(chunks),
        "total_chars": len(text),
        "source_url": pdf_url,
    }


def ingest_past_performance(
    text: str,
    project_name: str,
    metadata: dict,
) -> dict:
    chunks = _chunk_text(text)
    embeddings = _embed(chunks)

    col = _get_past_performance()
    safe_name = project_name.replace(" ", "_")
    ids = [f"pp_{safe_name}_{i}" for i in range(len(chunks))]
    metas = [
        {
            "project_name": project_name,
            **{k: str(v) for k, v in metadata.items()},
            "chunk_index": i,
            "total_chunks": len(chunks),
        }
        for i in range(len(chunks))
    ]
    col.upsert(ids=ids, embeddings=embeddings, documents=chunks, metadatas=metas)

    return {"project_name": project_name, "chunks_ingested": len(chunks)}


def search_solicitations(
    query: str,
    n_results: int = 5,
    notice_id_filter: str | None = None,
) -> list[dict]:
    col = _get_solicitations()
    query_embedding = _embed([query])[0]

    where = {"notice_id": {"$eq": notice_id_filter}} if notice_id_filter else None

    count = col.count()
    if count == 0:
        return []

    n = min(n_results, count)
    kwargs: dict = {"query_embeddings": [query_embedding], "n_results": n}
    if where:
        kwargs["where"] = where

    results = col.query(**kwargs)

    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    return [
        {
            "text": docs[i],
            "notice_id": metas[i].get("notice_id", ""),
            "title": metas[i].get("title", ""),
            "agency": metas[i].get("agency", ""),
            "distance": distances[i],
            "chunk_index": metas[i].get("chunk_index", 0),
        }
        for i in range(len(docs))
    ]


def search_past_performance(
    query: str,
    n_results: int = 5,
) -> list[dict]:
    col = _get_past_performance()
    query_embedding = _embed([query])[0]

    count = col.count()
    if count == 0:
        return []

    n = min(n_results, count)
    results = col.query(query_embeddings=[query_embedding], n_results=n)

    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    return [
        {
            "text": docs[i],
            "project_name": metas[i].get("project_name", ""),
            "contract_number": metas[i].get("contract_number", ""),
            "agency": metas[i].get("agency", ""),
            "distance": distances[i],
        }
        for i in range(len(docs))
    ]


def match_rfp_to_past_performance(
    rfp_text: str,
    top_k: int = 3,
) -> dict:
    raw = search_past_performance(rfp_text, n_results=top_k * 3)

    best_by_project: dict[str, dict] = {}
    for item in raw:
        name = item["project_name"]
        if name not in best_by_project or item["distance"] < best_by_project[name]["distance"]:
            best_by_project[name] = item

    top = sorted(best_by_project.values(), key=lambda x: x["distance"])[:top_k]

    matches = [
        {
            "project_name": m["project_name"],
            "contract_number": m["contract_number"],
            "agency": m["agency"],
            "relevance_score": round((1 - m["distance"]) * 100, 1),
            "best_matching_excerpt": m["text"][:300],
        }
        for m in top
    ]

    return {"matches": matches}


def get_collection_stats() -> dict:
    return {
        "solicitations": {"count": _get_solicitations().count()},
        "past_performance": {"count": _get_past_performance().count()},
    }
