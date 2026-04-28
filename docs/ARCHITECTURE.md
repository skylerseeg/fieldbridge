# FieldBridge Architecture

## Data Flow

```
M365 Email ──────────────────────┐
GPS Telematics ────────────────── FieldBridge API Engine ── Vista SQL (apvend/emem/emwo/jcjm/preh)
Field App Input ─────────────────┘          │
                                            │
                              ┌─────────────┴──────────────┐
                              │         Agents              │
                              │  bid_agent (drawings→BOM)   │
                              │  proposal_agent (writer)    │
                              │  project_search (ChromaDB)  │
                              │  media_agent (Vision tag)   │
                              └─────────────────────────────┘
```

## Service Boundaries

| Service            | Owns                              | Calls               |
|--------------------|-----------------------------------|---------------------|
| email_bridge       | M365 auth, email parse, CSI infer | vista_sync (write)  |
| vista_sync         | Vista SQL + REST API              | —                   |
| bid_intelligence   | PDF parse, BOM extraction         | email_bridge, agents|
| project_memory     | ChromaDB vector store             | —                   |
| proposal_engine    | Section drafting, assembly        | project_memory, media_library |
| media_library      | Azure Blob, tagging index         | agents/media_agent  |

## Security Rules
- Vista SQL: **read-only** service account. All writes go through Vista REST API or CSV import.
- M365: OAuth2 app-only permissions. No user passwords stored anywhere.
- Secrets: `.env` only. Never committed. Use Azure Key Vault in production.
