# design_automation
Adobe InDesign AI integration for proposal + marketing materials.

## Approach (v3)
- InDesign Server REST API → place AI-generated content into templates
- ExtendScript / UXP plugin that calls FieldBridge API for content
- Automate: photo selection, caption writing, section layout

## Files
- `indesign_api.py`  — InDesign Server REST client
- `template_map.py`  — Map proposal sections to InDesign template frames
