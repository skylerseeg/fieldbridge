# media_library
AI tagging and search for VanCon's photo and video library.

## Features
- Auto-tag photos: project, equipment, location, date, work type
- Natural language search: 'show photos of storm drain work in 2024'
- Video transcription + keyword indexing
- Link assets to Vista job numbers

## Files
- `tagger.py`       — Claude Vision: analyze + tag uploaded media
- `search.py`       — Natural language → media asset retrieval
- `ingester.py`     — Bulk import existing photo library
- `storage.py`      — Azure Blob Storage client
