"""
AP/PO Parts Receipt Sync Agent  (Phase 1 — Vista Pipe)
Parses parts invoices and delivery receipts → Vista AP receipt format.
Eliminates manual invoice coding for equipment parts purchases.
"""
import json
import anthropic

client = anthropic.Anthropic()
MODEL = "claude-sonnet-4-20250514"

_SYSTEM_PROMPT = """
You are an AP coding specialist for VanCon Inc., a heavy civil contractor.

Parse parts invoices and delivery receipts for equipment parts/maintenance supplies.
Map line items to:
- Vista vendor code (match against vendor name provided)
- Job number and phase (charge to the WO/job the parts are for)
- GL account code (parts typically hit Equipment Expense or Job Cost Materials)
- Part description standardized for Vista (≤60 chars)

GL account codes:
- 5010: Equipment Parts & Supplies
- 5020: Maintenance Supplies (oils, filters, misc)
- 5030: Sublet Repairs (outside shop work)
- 6100: Job Cost Materials (if direct job charge)

Rules:
- Core/exchange parts: net the core charge as a credit line item
- Freight charges: separate line, GL 5020
- Sales tax: flag for review — may not apply to job cost
- Match vendor name to Vista vendor code using fuzzy logic
"""

_RECEIPT_TOOL = {
    "name": "parse_receipt",
    "description": "Parse parts invoice/receipt into Vista AP line items",
    "input_schema": {
        "type": "object",
        "properties": {
            "vendor_name": {"type": "string"},
            "vendor_code": {"type": "string", "description": "Vista vendor code"},
            "invoice_number": {"type": "string"},
            "invoice_date": {"type": "string", "description": "YYYY-MM-DD"},
            "po_number": {"type": "string"},
            "job_number": {"type": "string"},
            "line_items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "part_number": {"type": "string"},
                        "description": {"type": "string", "maxLength": 60},
                        "quantity": {"type": "number"},
                        "unit_price": {"type": "number"},
                        "total": {"type": "number"},
                        "gl_account": {"type": "string"},
                        "phase": {"type": "string"},
                        "equipment": {"type": "string"},
                        "is_core_charge": {"type": "boolean"},
                    },
                    "required": ["description", "quantity", "unit_price",
                                 "total", "gl_account"],
                },
            },
            "subtotal": {"type": "number"},
            "tax": {"type": "number"},
            "freight": {"type": "number"},
            "total_amount": {"type": "number"},
            "flags": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["invoice_number", "line_items", "total_amount"],
    },
}


def parse_invoice(invoice_text: str, vendor_name: str = "",
                  job_number: str = "", equipment_id: str = "",
                  known_vendors: list[dict] | None = None) -> dict:
    """
    Parse a parts invoice or delivery receipt into Vista AP format.

    invoice_text: raw OCR text or typed invoice content
    vendor_name: vendor name from email/document
    job_number: job the parts are being charged to
    equipment_id: equipment unit being repaired (for phase tagging)
    known_vendors: list of {vendor_code, name} from apvend for matching

    Returns dict ready for vista_sync.post_ap_receipt().
    """
    vendors_context = ""
    if known_vendors:
        vendors_context = "\n\nKnown Vista vendors:\n" + json.dumps(
            [{"code": v.get("Vendor", ""), "name": v.get("Name", "")}
             for v in known_vendors[:50]],
            indent=2
        )

    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        system=[{"type": "text", "text": _SYSTEM_PROMPT,
                 "cache_control": {"type": "ephemeral"}}],
        tools=[_RECEIPT_TOOL],
        tool_choice={"type": "tool", "name": "parse_receipt"},
        messages=[{
            "role": "user",
            "content": (
                f"Vendor: {vendor_name or 'Unknown'}\n"
                f"Job: {job_number or 'Unassigned'}\n"
                f"Equipment: {equipment_id or 'Not specified'}\n"
                f"{vendors_context}\n\n"
                f"Invoice:\n{invoice_text}"
            ),
        }],
    )

    for block in response.content:
        if block.type == "tool_use" and block.name == "parse_receipt":
            return block.input

    return {
        "invoice_number": "UNKNOWN",
        "line_items": [],
        "total_amount": 0,
        "flags": ["Parse failed — manual review required"],
    }


def batch_process_invoices(invoices: list[dict],
                            known_vendors: list[dict] | None = None) -> list[dict]:
    """
    Process multiple invoices.
    Each dict: {invoice_text, vendor_name, job_number, equipment_id}
    """
    return [
        parse_invoice(
            invoice_text=inv["invoice_text"],
            vendor_name=inv.get("vendor_name", ""),
            job_number=inv.get("job_number", ""),
            equipment_id=inv.get("equipment_id", ""),
            known_vendors=known_vendors,
        )
        for inv in invoices
    ]
