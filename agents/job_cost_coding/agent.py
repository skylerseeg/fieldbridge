"""
Job Cost Coding Agent  (Phase 1 — Vista Pipe)
AI-powered classification of field transactions to Vista job/phase/cost-type codes.
Eliminates manual coding errors and speeds up daily cost posting.
"""
import json
import anthropic

client = anthropic.Anthropic()
MODEL = "claude-sonnet-4-20250514"

_SYSTEM_PROMPT = """
You are a Vista ERP job cost coding specialist for VanCon Inc., a heavy civil contractor.

Your job: given a raw field transaction description, return the correct Vista coding:
- Job number (from the active job list provided)
- Phase code (4-digit, e.g. 0100 for mobilization, 0200 for earthwork, 0300 for pipe install)
- Cost type: L=Labor, E=Equipment, M=Material, S=Subcontract, O=Other
- CSI code (4-digit VanCon format)
- Confidence score 0-100

Common phase codes for heavy civil:
0100 Mobilization/Demobilization
0200 Site Clearing & Grubbing
0300 Earthwork & Grading
0400 Pipe Installation
0500 Structures & Manholes
0600 Paving
0700 Restoration & Cleanup
0800 Traffic Control
0900 Testing & Startup

When uncertain, flag needs_review=true. Never guess a job number not in the provided list.
"""

_CODE_TOOL = {
    "name": "code_transaction",
    "description": "Return Vista job cost coding for a field transaction",
    "input_schema": {
        "type": "object",
        "properties": {
            "job_number": {"type": "string", "description": "Vista job number"},
            "phase": {"type": "string", "description": "4-digit phase code"},
            "cost_type": {"type": "string", "enum": ["L", "E", "M", "S", "O"]},
            "csi_code": {"type": "string", "description": "4-digit CSI seq"},
            "description_clean": {"type": "string",
                                  "description": "Standardized description for Vista"},
            "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
            "needs_review": {"type": "boolean"},
            "reasoning": {"type": "string"},
        },
        "required": ["job_number", "phase", "cost_type", "confidence", "needs_review"],
    },
}


def code_transaction(description: str, active_jobs: list[dict],
                     transaction_type: str = "auto") -> dict:
    """
    Classify a raw field transaction description to Vista job cost codes.

    description: free-text from field (e.g. "D8 dozer working on storm drain at Main St job")
    active_jobs: list of {job_number, description, location} from Vista jcjm
    transaction_type: hint — 'labor' | 'equipment' | 'material' | 'subcontract' | 'auto'

    Returns Vista coding dict ready for post_job_cost_transaction().
    """
    jobs_context = json.dumps(
        [{"job": j.get("Job", j.get("job_number", "")),
          "description": j.get("Description", j.get("description", "")),
          "location": j.get("location", "")}
         for j in active_jobs[:30]],  # cap context
        indent=2
    )

    user_msg = (
        f"Transaction description: \"{description}\"\n"
        f"Transaction type hint: {transaction_type}\n\n"
        f"Active jobs:\n{jobs_context}"
    )

    response = client.messages.create(
        model=MODEL,
        max_tokens=512,
        system=[{"type": "text", "text": _SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}}],
        tools=[_CODE_TOOL],
        tool_choice={"type": "tool", "name": "code_transaction"},
        messages=[{"role": "user", "content": user_msg}],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "code_transaction":
            return block.input

    return {
        "job_number": "", "phase": "0000", "cost_type": "O",
        "confidence": 0, "needs_review": True,
        "reasoning": "Agent returned no structured output",
    }


def batch_code(transactions: list[str], active_jobs: list[dict]) -> list[dict]:
    """Code multiple transactions. Returns one result dict per input."""
    return [code_transaction(t, active_jobs) for t in transactions]
