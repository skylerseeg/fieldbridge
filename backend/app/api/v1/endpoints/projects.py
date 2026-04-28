"""Project experience endpoints — vector search and proposal generation."""
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from agents.project_search_agent.agent import search_projects
from agents.proposal_agent.agent import write_section, assemble_proposal
from app.services.project_memory import upsert_project, get_project_count, delete_project

router = APIRouter()


class ProjectUpsertRequest(BaseModel):
    project_id: str
    project_data: dict


class ProposalSectionRequest(BaseModel):
    section_type: str
    context: dict


class ProposalRequest(BaseModel):
    project_context: dict
    past_projects: list[dict] = []
    sections: Optional[list[str]] = None
    auto_search: bool = True
    search_query: str = ""


@router.get("/search")
def search_project_experience(
    q: str = Query(..., description="Natural language query"),
    top_k: int = Query(default=3, le=10),
    min_value: float = Query(default=0),
    year_from: int = Query(default=0),
):
    """
    Natural language search over VanCon's project history.
    Returns top matching projects with similarity scores and suggested narratives.
    """
    return search_projects(q, top_k=top_k,
                           min_contract_value=min_value, year_from=year_from)


@router.post("/")
def upsert_project_record(req: ProjectUpsertRequest):
    """Add or update a project record in the vector store."""
    upsert_project(req.project_id, req.project_data)
    return {"project_id": req.project_id, "status": "upserted",
            "total_count": get_project_count()}


@router.delete("/{project_id}")
def remove_project(project_id: str):
    """Remove a project from the vector store."""
    delete_project(project_id)
    return {"project_id": project_id, "status": "deleted"}


@router.get("/count")
def project_count():
    """Return total number of projects in vector store."""
    return {"count": get_project_count()}


@router.post("/proposal/section")
def generate_proposal_section(req: ProposalSectionRequest):
    """
    Generate a single proposal section using AI.
    section_type: executive_summary | experience | approach | team | safety
    """
    text = write_section(req.section_type, req.context)
    return {"section_type": req.section_type, "content": text}


@router.post("/proposal/full")
def generate_full_proposal(req: ProposalRequest):
    """
    Generate a complete bid proposal. If auto_search=true and search_query is provided,
    automatically retrieves the best past projects to populate the experience section.
    """
    past_projects = req.past_projects
    if req.auto_search and req.search_query and not past_projects:
        past_projects = search_projects(
            req.search_query, top_k=5,
            min_contract_value=req.project_context.get("estimated_value", 0) * 0.3,
        )

    return assemble_proposal(
        project_context=req.project_context,
        past_projects=past_projects,
        sections=req.sections,
    )
