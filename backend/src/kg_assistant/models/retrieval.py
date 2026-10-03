from pydantic import BaseModel, ConfigDict, Field


class VectorSearchRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    query: str = Field(min_length=1, max_length=24000)
    top_k: int = Field(default=5, ge=1, le=100, strict=True)


class VectorSearchResult(BaseModel):
    chunk_id: str
    text: str
    score: float = Field(ge=0, le=1)
    document_id: str
    filename: str
    page_number: int | None = Field(default=None, ge=1)
    chunk_index: int = Field(ge=0)


class VectorSearchResponse(BaseModel):
    query: str
    results: list[VectorSearchResult]
