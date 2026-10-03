from io import BytesIO
from unittest.mock import AsyncMock

import pytest
from document_fixtures import docx_bytes, pdf_bytes
from fastapi import UploadFile
from pydantic import ValidationError

from kg_assistant.core.config import Settings
from kg_assistant.core.exceptions import IngestionError
from kg_assistant.ingestion.chunking import ChunkingService
from kg_assistant.ingestion.extraction import TextExtractionService
from kg_assistant.models.documents import ExtractedPage
from kg_assistant.services.documents import DocumentService


@pytest.fixture
def extractor():
    return TextExtractionService(100_000, 5_000_000)


def test_txt_extraction(extractor):
    pages = extractor.extract("\ufeffHello café\nNext line".encode(), "txt")
    assert pages == [ExtractedPage(text="Hello café\nNext line")]


def test_pdf_extraction(extractor):
    pages = extractor.extract(pdf_bytes(["Page one", "", "Page three"]), "pdf")
    assert [p.page_number for p in pages] == [1, 2, 3]
    assert pages[0].text.strip() == "Page one"
    assert pages[1].text == ""
    assert pages[2].text.strip() == "Page three"


def test_docx_extraction_order_and_tables(extractor):
    pages = extractor.extract(docx_bytes(), "docx")
    assert pages[0].page_number is None
    assert pages[0].text.splitlines() == [
        "Paragraph before the table",
        "First cell\tSecond cell",
        "Paragraph after the table",
    ]


@pytest.mark.parametrize("kind", ["pdf", "docx", "txt"])
def test_empty_file(extractor, kind):
    with pytest.raises(IngestionError) as caught:
        extractor.extract(b"", kind)
    assert caught.value.code == "empty_file"


@pytest.mark.parametrize(
    "kind,content", [("pdf", b"broken"), ("docx", b"broken"), ("txt", b"\xff"), ("txt", b"\x00")]
)
def test_invalid_content(extractor, kind, content):
    with pytest.raises(IngestionError) as caught:
        extractor.extract(content, kind)
    assert caught.value.code == "invalid_document"


@pytest.mark.parametrize("kind,content", [("txt", b" \n\t"), ("pdf", pdf_bytes([""]))])
def test_no_text(extractor, kind, content):
    with pytest.raises(IngestionError) as caught:
        extractor.extract(content, kind)
    assert caught.value.code == "no_text"


def test_unsupported_extractor_type(extractor):
    with pytest.raises(IngestionError) as caught:
        extractor.extract(b"text", "exe")
    assert caught.value.status_code == 415


def test_extraction_limits():
    with pytest.raises(IngestionError) as caught:
        TextExtractionService(4, 5_000_000).extract(b"12345", "txt")
    assert caught.value.code == "extraction_limit"
    with pytest.raises(IngestionError):
        TextExtractionService(100_000, 100).extract(docx_bytes(), "docx")


def test_chunking_overlap_and_no_redundant_tail():
    chunks = ChunkingService(5, 2, 100).chunk([ExtractedPage(text="abcdefghijk")], "doc")
    assert [c.text for c in chunks] == ["abcde", "defgh", "ghijk"]
    assert [c.chunk_index for c in chunks] == [0, 1, 2]
    assert all(c.document_id == "doc" and c.page_number is None for c in chunks)
    assert len({c.id for c in chunks}) == 3
    assert ChunkingService(5, 2, 100).chunk([ExtractedPage(text="abc")], "doc")[0].text == "abc"


def test_page_boundaries_and_global_indices():
    pages = [
        ExtractedPage(text="abcdef", page_number=1),
        ExtractedPage(text=" ", page_number=2),
        ExtractedPage(text="xyz", page_number=3),
    ]
    chunks = ChunkingService(4, 1, 100).chunk(pages, "doc")
    assert [(c.text, c.chunk_index, c.page_number) for c in chunks] == [
        ("abcd", 0, 1),
        ("def", 1, 1),
        ("xyz", 2, 3),
    ]
    assert chunks == ChunkingService(4, 1, 100).chunk(pages, "doc")


def test_chunk_limit():
    with pytest.raises(IngestionError) as caught:
        ChunkingService(2, 0, 1).chunk([ExtractedPage(text="abcd")], "doc")
    assert caught.value.code == "chunk_limit"


@pytest.mark.parametrize("size,overlap", [(0, 0), (5, 5), (5, -1)])
def test_invalid_chunk_configuration(size, overlap):
    with pytest.raises(ValueError):
        ChunkingService(size, overlap, 100)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, neo4j_password="test", chunk_size=size, chunk_overlap=overlap)


async def test_actual_file_size_without_size_metadata(settings, extractor):
    settings.max_file_size = 4
    repository = AsyncMock()
    service = DocumentService(settings, extractor, ChunkingService(5, 1, 100), repository)
    file = UploadFile(filename="note.txt", file=BytesIO(b"12345"))
    with pytest.raises(IngestionError) as caught:
        await service.upload(file)
    assert caught.value.status_code == 413
    repository.save.assert_not_awaited()
    assert file.file.closed
