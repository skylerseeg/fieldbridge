"""
Project Memory Service
ChromaDB vector store for project experience.
Tenant-isolated: each tenant gets their own collection.
"""
import json
import logging
from pathlib import Path
from typing import Optional
import chromadb
from chromadb.config import Settings

log = logging.getLogger("fieldbridge.project_memory")

_PERSIST_DIR = Path(__file__).parent.parent.parent.parent.parent / "data" / "chromadb"

_clients: dict[str, chromadb.Client] = {}


def _get_collection(tenant_slug: str = "vancon"):
    """Each tenant gets their own isolated ChromaDB collection."""
    collection_name = f"{tenant_slug}_projects"

    if tenant_slug not in _clients:
        _PERSIST_DIR.mkdir(parents=True, exist_ok=True)
        _clients[tenant_slug] = chromadb.PersistentClient(
            path=str(_PERSIST_DIR),
            settings=Settings(anonymized_telemetry=False),
        )

    return _clients[tenant_slug].get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )


def upsert_project(project_id: str, project_data: dict,
                   embedding: Optional[list[float]] = None,
                   tenant_slug: str = "vancon"):
    col = _get_collection(tenant_slug)
    document = json.dumps(project_data)
    metadata = {
        "job_number": project_data.get("job_number", ""),
        "client": project_data.get("client", ""),
        "contract_value": float(project_data.get("contract_value", 0)),
        "year": int(project_data.get("year", 0)),
        "csi_codes": ",".join(str(c) for c in project_data.get("csi_codes", [])),
    }
    if embedding:
        col.upsert(ids=[project_id], documents=[document],
                   embeddings=[embedding], metadatas=[metadata])
    else:
        col.upsert(ids=[project_id], documents=[document], metadatas=[metadata])
    log.info(f"[{tenant_slug}] Upserted project {project_id}")


def query_projects(query_text: str, top_k: int = 5,
                   min_contract_value: float = 0,
                   year_from: int = 0,
                   tenant_slug: str = "vancon") -> list[dict]:
    col = _get_collection(tenant_slug)
    count = col.count()
    if count == 0:
        return []

    where_clauses = {}
    if min_contract_value > 0:
        where_clauses["contract_value"] = {"$gte": min_contract_value}
    if year_from > 0:
        where_clauses["year"] = {"$gte": year_from}

    kwargs: dict = {
        "query_texts": [query_text],
        "n_results": min(top_k, count),
        "include": ["documents", "metadatas", "distances"],
    }
    if where_clauses:
        kwargs["where"] = where_clauses

    results = col.query(**kwargs)
    projects = []
    if results["documents"] and results["documents"][0]:
        for doc, meta, dist in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            project = json.loads(doc)
            project["_similarity"] = round(1 - dist, 4)
            projects.append(project)
    return projects


def get_project_count(tenant_slug: str = "vancon") -> int:
    return _get_collection(tenant_slug).count()


def delete_project(project_id: str, tenant_slug: str = "vancon"):
    _get_collection(tenant_slug).delete(ids=[project_id])
