from kg_assistant.models.extraction import ExtractedEntity, ExtractedRelationship, ExtractionResult

SAMPLE = (
    "Platform Team manages Payment Service.\n"
    "Payment Service uses Redis for caching.\n"
    "Redis is hosted on AWS ElastiCache."
)


def sample_extraction() -> ExtractionResult:
    return ExtractionResult(
        entities=[
            ExtractedEntity(
                key="team",
                name="Platform Team",
                type="ORGANIZATION",
                evidence_quote="Platform Team",
            ),
            ExtractedEntity(
                key="payment",
                name="Payment Service",
                type="SERVICE",
                evidence_quote="Payment Service",
            ),
            ExtractedEntity(key="redis", name="Redis", type="TECHNOLOGY", evidence_quote="Redis"),
            ExtractedEntity(
                key="aws",
                name="AWS ElastiCache",
                type="CLOUD_SERVICE",
                evidence_quote="AWS ElastiCache",
            ),
        ],
        relationships=[
            ExtractedRelationship(
                source="team",
                target="payment",
                type="MANAGES",
                evidence_quote="Platform Team manages Payment Service.",
            ),
            ExtractedRelationship(
                source="payment",
                target="redis",
                type="USES",
                evidence_quote="Payment Service uses Redis for caching.",
            ),
            ExtractedRelationship(
                source="redis",
                target="aws",
                type="HOSTED_ON",
                evidence_quote="Redis is hosted on AWS ElastiCache.",
            ),
        ],
    )
