# Tools and technologies verified in the repository

| Technology | Actual use / declared configuration |
|---|---|
| Python | Backend requires >=3.12,<3.14; Docker python:3.12.12-slim |
| FastAPI / Uvicorn | API framework and ASGI server; locked dependencies under backend/ |
| Pydantic / pydantic-settings | Request/output schemas and environment settings |
| Neo4j / Python neo4j driver | Only database; Docker 5.26.0-community; async graph transactions/vector search |
| pypdf | PDF page text extraction |
| python-docx | DOCX body paragraph/table extraction |
| python-multipart | Multipart upload parsing |
| OpenAI Python SDK | Configured async Responses structured outputs and embeddings; no production alternative provider adapter yet |
| Next.js / React | App Router dashboard; package.json pins Next.js 16.3.8 and React 19.3.0 |
| TypeScript | Frontend typed components/API contracts; 5.9.3 declared |
| Tailwind CSS | Dashboard styling; 4.3.3 and PostCSS plugin declared |
| Cytoscape.js | Interactive actual Entity graph rendering; 3.34.3 declared |
| Node / npm | Frontend tooling; Node >=24.15; Docker 24.19.0-bookworm-slim; npm lockfile |
| Docker Compose | Loopback frontend/backend/Neo4j services, dependency health checks, named database volume |
| pytest / pytest-asyncio / httpx | Backend async/unit/API/integration tests with mocked provider calls |
| Ruff | Backend lint/format verification |
| Vitest / jsdom / Testing Library | Mocked frontend behavior/component/API tests |
| ESLint / Prettier / tsc | Frontend lint, format, and type checks |
| uv / Hatchling | Backend lock/dependency workflow and package build configuration |
| Mermaid / Markdown / JSON / JUnit XML | Architecture diagrams, docs, deterministic evaluation and audited test reports |

Exact backend versions/hashes are in `backend/uv.lock` and `requirements.lock`; frontend versions in `package-lock.json`. Tags/configuration above describe the actual repository, not a promise that they are the newest releases or vulnerability-free. There is no Pinecone, Qdrant, Chroma, Weaviate, FAISS, pgvector, separate SQL database, external reranker, or additional UI framework in application dependencies.
