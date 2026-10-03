# Large synthetic document test

Upload `large-service-handbook.txt` through Documents. It is 52,453 bytes and produces 66 TXT chunks with chunk_size=1000/chunk_overlap=200, verified using the implemented extraction/chunking services. Different settings produce different counts. No real provider calls were made to create or verify this document. Expected facts below are source annotations, not executed PASS results.

The fictional handbook includes 12 service chapters and a distinct Research Team appendix, covering caching, storage, dependencies, observability, release configuration, audit and documentation chains. Technology names are real but the described system is fictional.

| Question | Expected source-supported answer / chain |
|---|---|
| What caching solution does the payment application use? | Redis |
| Which service is managed by Finance Team? | Billing Service |
| Which database stores Customer Service transactional records? | MySQL |
| What service does Order Service depend on? | Inventory Service |
| What technology is used by the service managed by Platform Team? | Platform Team → MANAGES → Payment Service → USES → Redis; Platform Team also manages Configuration Service, so the question can have additional supported technologies |
| Which cloud service hosts the cache used by Payment Service? | Payment Service → USES → Redis → HOSTED_ON → AWS ElastiCache |
| Which cloud service hosts the caching technology used by the service managed by Research Team? | Research Team → MANAGES → Experiment Service → USES → Hazelcast → HOSTED_ON → Azure Virtual Machines |
| What technology is used by the archive service on which Audit Service depends? | Audit Service → DEPENDS_ON → Archive Service → USES → Amazon S3 |
| Which managed hosting service hosts the event technology used by Notification Service? | Notification Service → USES → Apache Kafka → HOSTED_ON → Amazon MSK |
| Who founded Experiment Service? | Insufficient evidence |
| What is the production API password? | Insufficient evidence; no credentials in the document |
| What is Payment Service's measured response time? | Insufficient evidence; no measured performance numbers provided |

Inspect citations and verify that excerpts contain the claimed supporting fact. TXT has no page_number; source cards should not invent PDF pages. Some entities have multiple documented relationships: inspect actual evidence rather than assuming a single response. The graph snapshot may be truncated by node/edge limits; graph retrieval has independent traversal bounds.

66 chunks require many extraction calls and can take several minutes or exceed the browser's five-minute synchronous upload timeout. API billing depends on your provider/account. If the UI times out, processing may still be active: inspect document extraction status/backfill state before uploading another copy. Failed/partial extraction is not completion. Use the recovery endpoints described in README and docs/api.md. The existing small platform-services.txt is faster for a first successful end-to-end demo.
