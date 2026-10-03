import re

ENTITY_TYPES = [
    "PERSON",
    "ORGANIZATION",
    "PROJECT",
    "SERVICE",
    "TECHNOLOGY",
    "DATABASE",
    "CLOUD_SERVICE",
    "LOCATION",
    "CONCEPT",
    "OTHER",
]
RELATIONSHIP_TYPES = [
    "WORKS_ON",
    "USES",
    "MANAGES",
    "DEPENDS_ON",
    "HOSTED_ON",
    "PART_OF",
    "BELONGS_TO",
    "CREATED_BY",
    "LOCATED_IN",
    "RELATED_TO",
]


def validate_types(values: list[str]) -> list[str]:
    if not values or len(values) != len(set(values)):
        raise ValueError("Type lists must be nonempty with no duplicates")
    if any(re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", value) is None for value in values):
        raise ValueError("Types must be uppercase identifiers, at most 64 characters")
    if set(values) & {"HAS_CHUNK", "MENTIONS"}:
        raise ValueError("Administrative relationship types are reserved")
    return values
