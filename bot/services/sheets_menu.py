from __future__ import annotations

import logging
import re
import time
from urllib.parse import parse_qs, urlparse

import httpx

logger = logging.getLogger(__name__)

SHEET_URL_RE = re.compile(
    r"docs\.google\.com/spreadsheets/d/(?P<sheet_id>[a-zA-Z0-9-_]+)"
)

_cache_key: tuple[str, int] | None = None
_cache_images: list[bytes] = []
_cache_at: float = 0
_CACHE_TTL_SEC = 30 * 60


def parse_sheet_url(url: str) -> tuple[str, int | None]:
    match = SHEET_URL_RE.search(url)
    if not match:
        raise ValueError("Не удалось распознать ссылку на Google Sheets")
    sheet_id = match.group("sheet_id")
    parsed = urlparse(url)
    gid_raw = parse_qs(parsed.query).get("gid", [None])[0]
    if gid_raw is None and parsed.fragment:
        fragment = parse_qs(parsed.fragment.lstrip("#"))
        gid_raw = fragment.get("gid", [None])[0]
    gid = int(gid_raw) if gid_raw else None
    return sheet_id, gid


def build_pdf_export_url(sheet_id: str, gid: int) -> str:
    return (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/export"
        f"?format=pdf&gid={gid}&portrait=false&fitw=true"
        f"&gridlines=false&printtitle=false&sheetnames=false"
    )


def _render_pdf_as_single_image(pdf_bytes: bytes) -> bytes:
    """Все страницы PDF склеиваем в одну PNG, чтобы меню уходило одним сообщением."""
    import pymupdf

    src = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    if src.page_count == 1:
        pixmap = src[0].get_pixmap(matrix=pymupdf.Matrix(2, 2))
        return pixmap.tobytes("png")

    width = max(page.rect.width for page in src)
    height = sum(page.rect.height for page in src)
    combined = pymupdf.open()
    page = combined.new_page(width=width, height=height)
    top = 0.0
    for index in range(src.page_count):
        rect = src[index].rect
        target = pymupdf.Rect(0, top, rect.width, top + rect.height)
        page.show_pdf_page(target, src, index)
        top += rect.height

    pixmap = page.get_pixmap(matrix=pymupdf.Matrix(2, 2))
    logger.info("Permanent menu stitched from %s PDF pages", src.page_count)
    return pixmap.tobytes("png")


async def download_menu_images(sheet_id: str, gid: int) -> list[bytes]:
    """Скачиваем лист как PDF и рендерим в одну PNG."""
    global _cache_key, _cache_images, _cache_at

    key = (sheet_id, gid)
    if (
        _cache_key == key
        and _cache_images
        and time.monotonic() - _cache_at < _CACHE_TTL_SEC
    ):
        return _cache_images

    url = build_pdf_export_url(sheet_id, gid)
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        response = await client.get(url)
        response.raise_for_status()
        pdf_bytes = response.content

    image = _render_pdf_as_single_image(pdf_bytes)
    _cache_key = key
    _cache_images = [image]
    _cache_at = time.monotonic()
    logger.info("Permanent menu rendered: 1 image")
    return _cache_images
