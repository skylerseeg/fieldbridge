"""
Project Search Agent
Natural language search over VanCon's project experience database via ChromaDB.
Example query: 'List 3 best projects for 500+ HP pump experience with XYZ engineer'
"""
import json
import anthropic
import sys
from pathlib import Path

# Allow import from backend services when run standalone
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "backend"))

from app.services.project_memory import query_projects

client = anthropic.Anthropic()
MODEL = "claude-sonnet-4-20250514"

_SYSTEM_PROMPT = """
You are a construction proposal assistant with access to VanCon Inc.'s complete
project history. When asked to find relevant projects, search the database and return
the top matches. For each project provide:
- Project name, owner, engineer, year, contract value
- Relevant scope items matching the query
- Key stats (pump HP, pipe diameter, depth, contract value)
- Suggested 2-3 sentence narrative for a proposal experience section

Always cite specific, verifiable project details. Never invent projects.
If fewer than 3 strong matches exist, say so rather than padding with weak matches.
"""


def search_projects(query: str, top_k: int = 3,
                    min_contract_value: float = 0,
                    year_from: int = 0) -> list[dict]:
    """
    Natural language query → ranked list of relevant past projects.

    Returns projects with _similarity scores and suggested narratives.
    """
    # Step 1: vector retrieval from ChromaDB
    candidates = query_projects(
        query_text=query,
        top_k=top_k * 2,  # over-fetch then rerank with Claude
        min_contract_value=min_contract_value,
        year_from=year_from,
    )

    if not candidates:
        return []

    # Step 2: Claude reranking and narrative generation
    candidates_json = json.dumps(candidates, indent=2, default=str)

    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=[
            {
                "type": "text",
                "text": _SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{
            "role": "user",
            "content": (
                f"Query: {query}\n\n"
                f"Candidate projects (pre-ranked by vector similarity):\n{candidates_json}\n\n"
                f"Return the top {top_k} most relevant projects as a JSON array. "
                f"Each object must have: project_name, owner, engineer, year, "
                f"contract_value, relevant_scope (list), key_stats (dict), "
                f"suggested_narrative (string), similarity_score (float)."
            ),
        }],
    )

    text = response.content[0].text
    import re
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            pass

    return candidates[:top_k]
