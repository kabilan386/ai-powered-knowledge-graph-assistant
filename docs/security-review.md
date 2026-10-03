# Final scoped security and cleanup review

This is a source/configuration review and regression verification, not a penetration test, regulatory certification, or guarantee of production safety. The local unauthenticated application must remain bound to loopback. No public deployment/authentication features were added.

## Findings and actions

| Area | Reviewed actual behavior / action |
|---|---|
| Upload parsing | Fixed: file size was checked after multipart parsing could already spool input. RequestBodyLimitMiddleware now checks declared and actual streamed body bytes before parsing. Upload transport permits MAX_FILE_SIZE + 64 KiB overhead; JSON write bodies permit 128 KiB. Actual file byte limit remains authoritative. Regression tests cover declared/streamed rejection and unchanged replay. |
| Filename | Safe POSIX basenames already strip Windows/Unix directory paths; added control-character rejection to avoid misleading metadata. No source filename is used as a filesystem output path. |
| Parsing / temporary files | UploadFile is closed in finally; built-in multipart spooling is bounded by transport guard. Parser uses in-memory bytes, DOCX expansion limit, extracted-text limit, chunk count limits, encrypted/corrupt/no-text rejection. No OCR or hostile-PDF sandbox is implemented. |
| Secrets | Root .env is ignored and private; Docker build contexts exclude .env files. API keys/Neo4j passwords are backend environment variables and SecretStr settings, absent from Dockerfiles/client variables. Actual local .env values were not printed into reports. |
| Cypher | Repository parameters hold values; structural domain identifiers derive only from validated server allowlists. Retrieval is bounded/read-only; no arbitrary user/LLM Cypher endpoint exists. |
| Graph / vectors | Depth, fan-out, anchors, candidate/result/evidence counts and timeouts bounded; cycles excluded. Vector model/dimensions/fingerprint guarded. No separate vector database. |
| Errors / logs | Application logs contain operational events/counts/class codes/request IDs rather than full prompts/documents/keys. API internal exceptions are sanitized. Validation errors can echo user input; request access logs can include URLs. Do not submit secrets as queries or put credentials in URLs. |
| CORS / frontend | Default exact local origin; no credentials enabled. Origin settings are operator-controlled. CORS is not authorization. Browser renders answers/excerpts as text and links only actual backend sources. No NEXT_PUBLIC provider secret. |
| Docker | Existing non-root backend/standalone frontend, loopback ports, health checks, persistent DB volume retained. Added forwarding for Neo4j connection/health timeouts and APP_NAME, plus test/log/Git build-context exclusions. compose.yaml remains the canonical supported filename. |
| Documentation | Replaced chronological root README with final project guide; retained detailed implementation reference; documented real API/schema, final diagrams/MCA modules, demo procedure, status/limitations and executed evidence. |
| TODO/dead code/dependencies | No unfinished application TODO/FIXME/debug output identified. Runtime dependencies have implemented uses; fixture no-op methods and evaluation CLI output are intentional. No unsupported large refactor or dependency removal was justified. |

## Remaining operational boundaries

The unauthenticated API exposes uploads/retry/backfill and knowledge to any client that can reach it. There is no authorization, quota/rate limiting, TLS termination, managed secrets, tenant isolation, durable background queue, parser process isolation, automated backups, or security monitoring. The body guard bounds memory per request, not aggregate concurrency; slow clients and expensive parsing/provider work need ingress/process limits for public hosting. Keep Compose loopback bindings for the MCA demo. A dedicated database user with appropriate schema permissions is needed because schema initialization is lazy.

Prompt instructions and quote/citation checks reduce unsupported output but cannot guarantee semantic entailment or resist every prompt injection. Extraction/model quality is not yet live-evaluated. API/provider errors and partial ingestion must remain visible. Private live evaluation contains source evidence and is ignored under evaluation/runs/.

Dependency versions are pinned/locked but not thereby guaranteed free from vulnerabilities. This scoped review does not include a complete image CVE/OS audit or penetration test. A deployer must review current package/image advisories before public release. Historical screenshots and scripted evaluation must not be presented as live-model production validation.

See [final verification](milestone9-verification.md) for executed regression/build checks and [project status](project-status.md) for implementation boundaries.
