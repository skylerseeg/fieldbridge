# proposal_engine
AI-assisted proposal writer. Claude agent with access to:
- project_memory (past experience, relevant projects)
- media_library (project photos)
- bid_intelligence (material lists, scope)
- Company boilerplate (capabilities, certs, safety record)

## Files
- `section_writer.py`   — Draft individual proposal sections
- `project_picker.py`   — Select best projects for experience section
- `assembler.py`        — Combine sections → final proposal draft
- `indesign_bridge.py`  — Export structured content for InDesign layout (v3)
