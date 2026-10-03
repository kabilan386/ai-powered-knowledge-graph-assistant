INDEX_NAME = "chunk_embedding_index"

CREATE_INDEX = """
CREATE VECTOR INDEX chunk_embedding_index IF NOT EXISTS
FOR (c:Chunk) ON (c.embedding)
OPTIONS {indexConfig: {`vector.dimensions`: $dimensions,
                      `vector.similarity_function`: 'cosine'}}
"""

SPACE_CONSTRAINT = (
    "CREATE CONSTRAINT embedding_space_id IF NOT EXISTS "
    "FOR (s:EmbeddingSpace) REQUIRE s.id IS UNIQUE"
)
