CONSTRAINTS = (
    "CREATE CONSTRAINT entity_id_unique IF NOT EXISTS FOR (e:Entity) REQUIRE e.id IS UNIQUE",
    "CREATE CONSTRAINT entity_identity_unique IF NOT EXISTS "
    "FOR (e:Entity) REQUIRE (e.type, e.normalized_name) IS UNIQUE",
)
