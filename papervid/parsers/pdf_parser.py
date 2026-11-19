"""PDF parser — renders PDF pages to images for vision model."""

import logging
from pathlib import Path

from pdf2image import convert_from_path
from pypdf import PdfReader

from .models import PageImage, PaperData, PaperMetadata

logger = logging.getLogger(__name__)


def parse_pdf(
    pdf_path: Path,
    dpi: int = 200,
    max_pages: int = 20,
    out_dir: Path | None = None,
) -> PaperData:
    """Render PDF pages to images only — no text extraction.

    Pages are saved as PNG files. The vision-capable LLM will analyze
    these images directly to understand the paper content.

    Args:
        pdf_path: Path to the PDF file.
        dpi: Resolution for page rendering.
        max_pages: Maximum number of pages to render.
        out_dir: Where to save page PNGs (default: <pdf dir>/_papervid_pages).

    Returns:
        PaperData with page images and minimal metadata.
    """
    data = PaperData()
    data.pdf_path = pdf_path

    # Extract minimal metadata (title, authors)
    reader = PdfReader(str(pdf_path))
    meta = reader.metadata or {}
    data.metadata = PaperMetadata()
    data.metadata.title = (meta.get("/Title") or "").strip()
    authors_raw = (meta.get("/Author") or "").strip()
    if authors_raw:
        data.metadata.authors = [a.strip() for a in authors_raw.split(";") if a.strip()]
    data.metadata.date = (meta.get("/Date") or "").strip()

    total_pages = min(len(reader.pages), max_pages)
    logger.info(f"Rendering {total_pages} PDF pages at {dpi} DPI...")

    images = convert_from_path(
        str(pdf_path),
        dpi=dpi,
        first_page=1,
        last_page=total_pages,
        fmt="png",
    )

    out_dir = out_dir or pdf_path.parent / "_papervid_pages"
    out_dir.mkdir(parents=True, exist_ok=True)

    for i, img in enumerate(images):
        page_num = i + 1
        img_path = out_dir / f"page_{page_num:03d}.png"
        img.save(str(img_path), "PNG")
        data.pages.append(PageImage(
            page_number=page_num,
            image_path=img_path,
            width=img.width,
            height=img.height,
        ))

    logger.info(f"Rendered {len(data.pages)} pages")
    return data
