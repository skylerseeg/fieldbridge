"""Job cost endpoints — Vista jcjm/jcci read + AI cost coding + AP receipt sync."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.services.vista_sync import get_job_cost, post_job_cost_transaction, post_ap_receipt
from agents.ap_po_sync.agent import parse_invoice, batch_process_invoices
from app.services.vista_sync import get_ap_vendors

router = APIRouter()


class JobCostTransactionRequest(BaseModel):
    job_number: str
    phase: str
    cost_type: str
    description: str
    units: float
    unit_cost: float
    equipment: str = ""


class InvoiceParseRequest(BaseModel):
    invoice_text: str
    vendor_name: str = ""
    job_number: str = ""
    equipment_id: str = ""
    auto_post: bool = False


class BatchInvoiceRequest(BaseModel):
    invoices: list[InvoiceParseRequest]
    auto_post: bool = False


@router.get("/jobs")
def list_jobs(job_number: Optional[str] = None):
    """List jobs from Vista jcjm with cost summary."""
    return get_job_cost(job_number=job_number)


@router.get("/jobs/{job_number}")
def get_job_detail(job_number: str, phase: Optional[str] = None):
    """Get detailed cost breakdown for a specific job from Vista."""
    data = get_job_cost(job_number=job_number, phase=phase)
    if not data:
        raise HTTPException(status_code=404, detail="Job not found")
    return data


@router.post("/transactions")
def post_transaction(req: JobCostTransactionRequest):
    """Post a job cost transaction directly to Vista."""
    return post_job_cost_transaction(
        job_number=req.job_number,
        phase=req.phase,
        cost_type=req.cost_type,
        description=req.description,
        units=req.units,
        unit_cost=req.unit_cost,
        equipment=req.equipment,
    )


@router.post("/invoices/parse")
def parse_ap_invoice(req: InvoiceParseRequest):
    """
    AI-powered AP invoice parsing. Extracts line items, maps to Vista AP format,
    and optionally posts to Vista. Eliminates manual invoice coding.
    """
    vendors = get_ap_vendors()
    result = parse_invoice(
        invoice_text=req.invoice_text,
        vendor_name=req.vendor_name,
        job_number=req.job_number,
        equipment_id=req.equipment_id,
        known_vendors=vendors,
    )

    if req.auto_post and not result.get("flags"):
        try:
            vista_result = post_ap_receipt(
                vendor=result.get("vendor_code", ""),
                invoice_number=result.get("invoice_number", ""),
                invoice_date=result.get("invoice_date", ""),
                job_number=req.job_number,
                amount=result.get("total_amount", 0),
                line_items=result.get("line_items", []),
            )
            result["vista_receipt"] = vista_result
        except Exception as e:
            result["post_error"] = str(e)

    return result


@router.post("/invoices/batch")
def parse_invoices_batch(req: BatchInvoiceRequest):
    """Batch process multiple AP invoices."""
    vendors = get_ap_vendors()
    invoice_data = [inv.dict() for inv in req.invoices]
    return batch_process_invoices(invoice_data, known_vendors=vendors)


@router.post("/invoices/post")
def post_ap_receipt_direct(
    vendor: str, invoice_number: str, invoice_date: str,
    job_number: str, amount: float, line_items: list[dict],
):
    """Post a pre-parsed AP receipt directly to Vista."""
    return post_ap_receipt(vendor, invoice_number, invoice_date,
                            job_number, amount, line_items)
