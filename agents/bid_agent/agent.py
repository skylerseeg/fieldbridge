"""
Bid Intelligence Agent
Parses project drawings + specs → extracts material list → compares to supplier quotes.
Uses Anthropic tool_use for structured BOM extraction with prompt caching.
"""
import json
import anthropic
from backend.app.services.bid_intelligence import (
    extract_text_from_pdf, extract_text_from_docx, chunk_document
)

client = anthropic.Anthropic()

MODEL = "claude-sonnet-4-20250514"

_SYSTEM_PROMPT = """
You are a construction estimating assistant for VanCon Inc., a heavy civil contractor.
Your job is to:
1. Parse drawings and specification documents to extract a complete material and quantity list.
2. Compare that list against supplier quotes to identify coverage gaps.
3. Output structured JSON matching the schema provided via tools.

Focus on: pipe, aggregate, concrete, steel, equipment rentals, subcontractor scope.
Always include spec section references. Never invent quantities — use "TBD" if unclear.
"""

_EXTRACT_TOOL = {
    "name": "extract_bom",
    "description": "Extract bill of materials from construction document text",
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "description": {"type": "string"},
                        "quantity": {"type": "string"},
                        "unit": {"type": "string"},
                        "spec_reference": {"type": "string"},
                        "csi_code": {"type": "string"},
                        "notes": {"type": "string"},
                    },
                    "required": ["description", "quantity", "unit"],
                },
            },
            "project_name": {"type": "string"},
            "project_owner": {"type": "string"},
            "bid_date": {"type": "string"},
            "summary": {"type": "string"},
        },
        "required": ["items"],
    },
}

_COMPARE_TOOL = {
    "name": "compare_coverage",
    "description": "Compare BOM items against supplier quote coverage",
    "input_schema": {
        "type": "object",
        "properties": {
            "covered": {
                "type": "array",
                "items": {"type": "object",
                          "properties": {"item": {"type": "string"},
                                         "vendor": {"type": "string"},
                                         "unit_price": {"type": "string"}},
                          "required": ["item", "vendor"]},
            },
            "missing": {
                "type": "array",
                "items": {"type": "object",
                          "properties": {"item": {"type": "string"},
                                         "reason": {"type": "string"}},
                          "required": ["item"]},
            },
            "partial": {
                "type": "array",
                "items": {"type": "object",
                          "properties": {"item": {"type": "string"},
                                         "gap": {"type": "string"}},
                          "required": ["item", "gap"]},
            },
            "coverage_pct": {"type": "number"},
            "risk_flags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["covered", "missing", "partial", "coverage_pct"],
    },
}


def extract_materials_from_pdf(pdf_path: str) -> dict:
    """
    Send PDF content to Claude for material extraction.
    Returns structured BOM with items, quantities, units, and spec references.
    """
    text = extract_text_from_pdf(pdf_path)
    chunks = chunk_document(text)

    all_items: list[dict] = []
    metadata: dict = {}

    for chunk in chunks:
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=[_EXTRACT_TOOL],
            tool_choice={"type": "tool", "name": "extract_bom"},
            messages=[{
                "role": "user",
                "content": f"Extract all materials and quantities from this document section:\n\n{chunk}",
            }],
        )

        for block in response.content:
            if block.type == "tool_use" and block.name == "extract_bom":
                result = block.input
                all_items.extend(result.get("items", []))
                if not metadata:
                    metadata = {
                        k: result.get(k, "")
                        for k in ["project_name", "project_owner", "bid_date", "summary"]
                    }

    return {**metadata, "items": all_items, "total_line_items": len(all_items)}


def compare_to_quotes(material_list: dict, quote_emails: list[str]) -> dict:
    """
    Compare extracted BOM against supplier quote emails.
    Returns coverage report: covered, missing, partial items + coverage %.
    """
    bom_summary = json.dumps(material_list.get("items", []), indent=2)
    quotes_text = "\n\n---QUOTE---\n".join(quote_emails)

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=[
            {
                "type": "text",
                "text": _SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        tools=[_COMPARE_TOOL],
        tool_choice={"type": "tool", "name": "compare_coverage"},
        messages=[{
            "role": "user",
            "content": (
                f"Compare this bill of materials against the supplier quotes below.\n\n"
                f"BILL OF MATERIALS:\n{bom_summary}\n\n"
                f"SUPPLIER QUOTES:\n{quotes_text}"
            ),
        }],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "compare_coverage":
            return block.input

    return {"covered": [], "missing": [], "partial": [], "coverage_pct": 0}
