"""AP vendor endpoints — read from Vista apvend."""
from typing import Optional
from fastapi import APIRouter, Query
from app.services.vista_sync import get_ap_vendors

router = APIRouter()


@router.get("/")
def list_vendors(
    vendor_id: Optional[str] = None,
    active_only: bool = Query(default=True),
):
    """List AP vendors from Vista apvend table."""
    return get_ap_vendors(vendor_id=vendor_id, active_only=active_only)


@router.get("/{vendor_id}")
def get_vendor(vendor_id: str):
    """Get a single vendor by Vista vendor code."""
    vendors = get_ap_vendors(vendor_id=vendor_id)
    if not vendors:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Vendor not found")
    return vendors[0]
