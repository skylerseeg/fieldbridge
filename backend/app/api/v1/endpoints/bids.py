"""Bid intelligence endpoints — PDF extraction, quote comparison, job cost coding."""
from typing import Optional
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel
from agents.bid_agent.agent import extract_materials_from_pdf, compare_to_quotes
from agents.job_cost_coding.agent import code_transaction, batch_code
from app.services.vista_sync import get_job_cost
import tempfile, os

router = APIRouter()


class QuoteCompareRequest(BaseModel):
    material_list: dict
    quote_emails: list[str]


class CodeTransactionRequest(BaseModel):
    description: str
    transaction_type: str = "auto"


class BatchCodeRequest(BaseModel):
    transactions: list[str]


@router.post("/extract")
async def extract_from_document(file: UploadFile = File(...)):
    """
    Upload a PDF spec book or drawings package.
    Returns AI-extracted bill of materials with quantities, units, and spec refs.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files supported")

    content = await file.read()
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        result = extract_materials_from_pdf(tmp_path)
    finally:
        os.unlink(tmp_path)

    return result


@router.post("/compare-quotes")
def compare_quotes(req: QuoteCompareRequest):
    """
    Compare extracted BOM against supplier quote emails.
    Returns coverage report: covered items, gaps, partial coverage, and risk flags.
    """
    return compare_to_quotes(req.material_list, req.quote_emails)


@router.post("/code-transaction")
def code_single_transaction(req: CodeTransactionRequest):
    """
    AI job cost coding: classify a field description to Vista job/phase/cost-type.
    Returns coding with confidence score and review flag.
    """
    active_jobs = get_job_cost()
    # Deduplicate to job-level for context
    seen = set()
    unique_jobs = []
    for j in active_jobs:
        jn = j.get("Job", "")
        if jn and jn not in seen:
            seen.add(jn)
            unique_jobs.append(j)
    return code_transaction(req.description, unique_jobs, req.transaction_type)


@router.post("/code-transactions/batch")
def code_transactions_batch(req: BatchCodeRequest):
    """Batch job cost coding for multiple field transactions."""
    active_jobs = get_job_cost()
    seen = set()
    unique_jobs = []
    for j in active_jobs:
        jn = j.get("Job", "")
        if jn and jn not in seen:
            seen.add(jn)
            unique_jobs.append(j)
    return batch_code(req.transactions, unique_jobs)
