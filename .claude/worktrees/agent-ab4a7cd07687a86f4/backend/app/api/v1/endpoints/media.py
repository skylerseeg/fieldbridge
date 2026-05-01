"""Media library endpoints — upload, AI tagging, search."""
from typing import Optional
from fastapi import APIRouter, UploadFile, File, HTTPException, Query
from pydantic import BaseModel
from agents.media_agent.agent import tag_image
from app.services.media_library import (
    upload_media, get_media_metadata, update_tags, list_media, download_media
)
import tempfile, os

router = APIRouter()


class TagUpdateRequest(BaseModel):
    tags: dict


@router.post("/upload")
async def upload_and_tag(
    file: UploadFile = File(...),
    job_number: str = Query(default=""),
    auto_tag: bool = Query(default=True),
):
    """
    Upload a construction photo to Azure Blob.
    If auto_tag=true, runs Claude Vision tagging automatically.
    Returns media_id, URL, and AI tags.
    """
    allowed = {".jpg", ".jpeg", ".png", ".webp"}
    ext = os.path.splitext(file.filename or "")[1].lower()
    if ext not in allowed:
        raise HTTPException(status_code=400,
                            detail=f"Unsupported file type. Allowed: {allowed}")

    content = await file.read()

    tags = {}
    if auto_tag:
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            tags = tag_image(tmp_path)
        finally:
            os.unlink(tmp_path)

    result = upload_media(
        file_bytes=content,
        filename=file.filename,
        content_type=file.content_type or "image/jpeg",
        tags=tags,
        job_number=job_number,
    )
    result["tags"] = tags
    return result


@router.get("/{media_id}")
def get_media(media_id: str):
    """Get metadata and tags for a media asset."""
    meta = get_media_metadata(media_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Media not found")
    return meta


@router.post("/{media_id}/retag")
def retag_media(media_id: str):
    """Re-run AI tagging on an existing media asset."""
    meta = get_media_metadata(media_id)
    if not meta:
        raise HTTPException(status_code=404, detail="Media not found")

    raw = download_media(media_id)
    if not raw:
        raise HTTPException(status_code=404, detail="Media file not accessible")

    ext = os.path.splitext(meta.get("blob_name", ""))[1].lower()
    with tempfile.NamedTemporaryFile(suffix=ext or ".jpg", delete=False) as tmp:
        tmp.write(raw)
        tmp_path = tmp.name
    try:
        tags = tag_image(tmp_path)
    finally:
        os.unlink(tmp_path)

    update_tags(media_id, tags)
    return {"media_id": media_id, "tags": tags}


@router.patch("/{media_id}/tags")
def update_media_tags(media_id: str, req: TagUpdateRequest):
    """Manually update or override tags on a media asset."""
    if not update_tags(media_id, req.tags):
        raise HTTPException(status_code=404, detail="Media not found")
    return {"media_id": media_id, "updated": True}


@router.get("/")
def list_media_assets(
    job_number: Optional[str] = None,
    limit: int = Query(default=50, le=200),
):
    """List media assets, optionally filtered by job number."""
    return list_media(job_number=job_number, limit=limit)
