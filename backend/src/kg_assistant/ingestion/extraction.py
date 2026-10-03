from io import BytesIO
from zipfile import ZipFile

from docx import Document as read_docx
from docx.table import Table
from docx.text.paragraph import Paragraph
from pypdf import PdfReader

from kg_assistant.core.exceptions import IngestionError
from kg_assistant.models.documents import ExtractedPage, FileType


class TextExtractionService:
    def __init__(self, max_characters: int, max_docx_uncompressed_bytes: int) -> None:
        self.max_characters = max_characters
        self.max_docx_uncompressed_bytes = max_docx_uncompressed_bytes

    def extract(self, content: bytes, file_type: FileType) -> list[ExtractedPage]:
        if not content:
            raise IngestionError("empty_file", "The uploaded file is empty.", 400)
        try:
            if file_type == "txt":
                text = content.decode("utf-8-sig")
                if "\x00" in text:
                    raise ValueError("Binary content is not supported as TXT")
                pages = [ExtractedPage(text=text)]
            elif file_type == "pdf":
                reader = PdfReader(BytesIO(content))
                if reader.is_encrypted:
                    raise IngestionError("encrypted_pdf", "Encrypted PDFs are not supported.", 422)
                pages = []
                total = 0
                for number, page in enumerate(reader.pages, start=1):
                    text = page.extract_text() or ""
                    total += len(text)
                    self._check_length(total)
                    pages.append(ExtractedPage(text=text, page_number=number))
            elif file_type == "docx":
                with ZipFile(BytesIO(content)) as archive:
                    if sum(info.file_size for info in archive.infolist()) > (
                        self.max_docx_uncompressed_bytes
                    ):
                        raise IngestionError(
                            "extraction_limit", "DOCX expanded contents exceed the limit.", 413
                        )
                document = read_docx(BytesIO(content))
                parts: list[str] = []
                for block in document.iter_inner_content():
                    if isinstance(block, Paragraph):
                        parts.append(block.text)
                    elif isinstance(block, Table):
                        parts.extend(
                            "\t".join(cell.text for cell in row.cells) for row in block.rows
                        )
                pages = [ExtractedPage(text="\n".join(parts))]
            else:
                raise IngestionError("unsupported_file", "Supported types: PDF, DOCX, TXT.", 415)
        except IngestionError:
            raise
        except Exception as exc:
            raise IngestionError(
                "invalid_document", "Unable to read the document. TXT must use UTF-8 encoding.", 422
            ) from exc
        self._check_length(sum(len(page.text) for page in pages))
        if not any(page.text.strip() for page in pages):
            raise IngestionError(
                "no_text", "The document contains no extractable text. OCR is not supported.", 422
            )
        return pages

    def _check_length(self, length: int) -> None:
        if length > self.max_characters:
            raise IngestionError("extraction_limit", "Extracted text exceeds the limit.", 413)
