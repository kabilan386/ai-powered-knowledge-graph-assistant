import re
import unicodedata
from uuid import NAMESPACE_URL, uuid5

from kg_assistant.models.extraction import (
    ExtractionResult,
    NormalizedEntity,
    NormalizedExtraction,
    NormalizedRelationship,
)


def normalize_name(name: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", name).casefold().split())


def name_in_text(name: str, text: str) -> bool:
    return (
        re.search(r"(?<!\w)" + re.escape(normalize_name(name)) + r"(?!\w)", normalize_name(text))
        is not None
    )


def normalize_extraction(result: ExtractionResult) -> NormalizedExtraction:
    entities: dict[tuple[str, str], NormalizedEntity] = {}
    key_to_id: dict[str, str] = {}
    for item in result.entities:
        normalized = normalize_name(item.name)
        identity = (item.type, normalized)
        if identity not in entities:
            entities[identity] = NormalizedEntity(
                id=str(uuid5(NAMESPACE_URL, f"entity:{item.type}:{normalized}")),
                name=item.name.strip(),
                normalized_name=normalized,
                type=item.type,
                description=item.description,
                evidence_quote=item.evidence_quote,
            )
        key_to_id[item.key] = entities[identity].id
    relationships: dict[tuple[str, str, str], NormalizedRelationship] = {}
    for item in result.relationships:
        source, target = key_to_id[item.source], key_to_id[item.target]
        identity = (source, item.type, target)
        if identity not in relationships:
            relationships[identity] = NormalizedRelationship(
                source_id=source,
                target_id=target,
                type=item.type,
                description=item.description,
                evidence_quote=item.evidence_quote,
            )
    return NormalizedExtraction(
        entities=list(entities.values()), relationships=list(relationships.values())
    )
