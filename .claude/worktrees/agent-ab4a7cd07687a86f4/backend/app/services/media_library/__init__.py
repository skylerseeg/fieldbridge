"""
Media Library Service
Azure Blob Storage management for VanCon's photo/video library.
Handles upload, download, listing, and metadata tag index.
"""
import io
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional
from app.core.config import settings

log = logging.getLogger("fieldbridge.media_library")

_blob_client = None


def _get_client():
    global _blob_client
    if _blob_client is None:
        from azure.storage.blob import BlobServiceClient
        _blob_client = BlobServiceClient.from_connection_string(
            settings.azure_storage_connection_string
        )
    return _blob_client


def upload_media(file_bytes: bytes, filename: str, content_type: str,
                 tags: Optional[dict] = None, job_number: str = "") -> dict:
    """Upload a media file to Azure Blob and store metadata. Returns media_id + URL."""
    from azure.storage.blob import ContentSettings
    client = _get_client()
    container = client.get_container_client(settings.azure_storage_container)

    media_id = str(uuid.uuid4())
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    blob_name = f"{job_number or 'untagged'}/{media_id}.{ext}"

    blob_client = container.get_blob_client(blob_name)
    blob_client.upload_blob(
        io.BytesIO(file_bytes), overwrite=True,
        content_settings=ContentSettings(content_type=content_type),
    )

    metadata = {
        "media_id": media_id,
        "original_filename": filename,
        "job_number": job_number,
        "uploaded_at": datetime.now(tz=timezone.utc).isoformat(),
        "content_type": content_type,
        "blob_name": blob_name,
        "tags": tags or {},
    }
    container.get_blob_client(f"meta/{media_id}.json").upload_blob(
        json.dumps(metadata), overwrite=True
    )

    log.info(f"Uploaded {blob_name}")
    return {"media_id": media_id, "url": blob_client.url, "blob_name": blob_name}


def get_media_metadata(media_id: str) -> Optional[dict]:
    client = _get_client()
    container = client.get_container_client(settings.azure_storage_container)
    try:
        data = container.get_blob_client(f"meta/{media_id}.json").download_blob().readall()
        return json.loads(data)
    except Exception:
        return None


def update_tags(media_id: str, tags: dict) -> bool:
    """Merge AI tags into existing metadata record."""
    meta = get_media_metadata(media_id)
    if not meta:
        return False
    meta["tags"].update(tags)
    meta["tagged_at"] = datetime.now(tz=timezone.utc).isoformat()
    client = _get_client()
    container = client.get_container_client(settings.azure_storage_container)
    container.get_blob_client(f"meta/{media_id}.json").upload_blob(
        json.dumps(meta), overwrite=True
    )
    return True


def list_media(job_number: Optional[str] = None, limit: int = 100) -> list[dict]:
    client = _get_client()
    container = client.get_container_client(settings.azure_storage_container)
    results = []
    for blob in container.list_blobs(name_starts_with="meta/"):
        if len(results) >= limit:
            break
        try:
            data = container.get_blob_client(blob.name).download_blob().readall()
            meta = json.loads(data)
            if job_number and meta.get("job_number") != job_number:
                continue
            results.append(meta)
        except Exception:
            continue
    return results


def download_media(media_id: str) -> Optional[bytes]:
    meta = get_media_metadata(media_id)
    if not meta:
        return None
    client = _get_client()
    container = client.get_container_client(settings.azure_storage_container)
    return container.get_blob_client(meta["blob_name"]).download_blob().readall()
