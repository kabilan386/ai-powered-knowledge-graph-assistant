# System design

## Problem and objectives

Semantic text retrieval can miss a relationship chain spread across supporting chunks. This project combines Chunk similarity search and a labeled property graph to expose both passages and multi-hop facts to a grounded answer generator. Objectives are modular ingestion, bounded retrieval, source provenance, honest insufficient-evidence handling, and reproducible comparison against a text-only baseline. Improvement in real-model quality is a research question; it has not been established by scripted tests.

## Modules and interactions

The frontend contains layout, upload/session history, chat/citations, and Cytoscape visualization. FastAPI route contracts inject settings, services, driver/repositories, and enabled providers. Extraction/chunking, knowledge graph persistence, embeddings/vector retrieval, query anchor extraction/BFS, context fusion, and answer validation are separate modules. See [architecture](../architecture.md) and [API](../api.md) for actual interactions.

## Context DFD reference

```mermaid
flowchart LR
    User[User] -->|Document / question| Assistant[Knowledge Assistant system]
    Assistant -->|Answer / sources / graph| User
    Assistant -->|Structured extraction / embeddings / generation| Provider[Configured AI provider]
    Provider -->|Validated output| Assistant
    Assistant <-->|Chunks / vectors / entities / provenance| DB[(Neo4j)]
```

## Level-one DFD reference

```mermaid
flowchart TD
    User[User] --> Upload[1. Validate and extract document]
    Upload --> Chunk[2. Chunk text]
    Chunk --> Store[(Neo4j)]
    Chunk --> AI[3. Embeddings and knowledge extraction]
    AI --> Store
    User --> Retrieve[4. Vector and graph retrieval]
    Store --> Retrieve
    Retrieve --> Fuse[5. Build bounded context]
    Fuse --> Answer[6. Generate and validate grounded answer]
    Answer --> User
```

These diagrams describe data flow; they are references for formal DFD/UML artwork, not claims of additional services or concurrent ingestion. The actual upload stages execute sequentially after base persistence; query retrieval branches execute concurrently.

## Query sequence reference

```mermaid
sequenceDiagram
    actor User
    participant UI as Next.js
    participant API as FastAPI / GraphRAGService
    participant DB as Neo4j
    participant AI as Configured provider
    User->>UI: Submit question
    UI->>API: POST /api/graphrag/ask
    par Semantic evidence
        API->>AI: Embed question
        API->>DB: Chunk vector search
    and Relationship evidence
        API->>AI: Extract anchors/intent
        API->>DB: Resolve anchors / bounded neighbors / provenance
    end
    API->>DB: Verify and hydrate source chunks
    API->>API: Deduplicate and limit context
    API->>AI: Generate structured grounded answer
    API->>API: Validate citations or report error/insufficiency
    API-->>UI: Answer, sources, retrieval metadata
    UI-->>User: Render answer and expandable citations
```

No-evidence questions bypass generation. Provider/retrieval errors are explicit rather than being labeled insufficient. The application has no auth/users/tenant model, background queue, external vector store, or arbitrary Cypher route. [Status](../project-status.md) records these boundaries.
