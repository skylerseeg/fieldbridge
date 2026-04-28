# project_memory
Searchable vector database of VanCon's completed project experience.
Answers natural language queries like:
  "List the 3 best projects to prove experience with 500+ HP pumps,
   steel yard piping slopes, and work with [specific engineer]."

## Stack
- ChromaDB vector store (local, upgrades to Azure Cognitive Search in v3)
- Anthropic embeddings for semantic search
- Source: project closeout docs, photos, Vista job cost history

## Files
- `ingester.py`      — Load project docs into vector DB
- `search.py`        — Natural language query → ranked project list
- `project_schema.py`— Structured project record definition
