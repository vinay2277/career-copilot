"""Turn whatever the user pasted or uploaded into plain text.

Four inputs, one output. Each parser raises `ParseError` with a message meant
for the user — these failures are usually fixable by them (a scanned PDF, a
login-walled URL), so the message needs to say which.
"""

from __future__ import annotations

import io
import logging
import re

import httpx2 as httpx
from selectolax.parser import HTMLParser

from app.core.config import settings

logger = logging.getLogger(__name__)

#: Below this many characters, a "successful" parse is almost certainly a
#: scanned page or a failed fetch. Better to say so than to hand the extraction
#: agent three words and let it invent a job.
MIN_USABLE_CHARS = 120

_BLANK_LINES = re.compile(r"\n{3,}")
_TRAILING_SPACE = re.compile(r"[ \t]+$", re.MULTILINE)


class ParseError(ValueError):
    """Input could not be turned into usable text. Message is user-facing."""


def tidy(text: str) -> str:
    """Normalize whitespace without touching content.

    PDF and OCR output is full of ragged spacing that costs tokens and makes
    the validation agent's verbatim-quote check harder to satisfy.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _TRAILING_SPACE.sub("", text)
    text = _BLANK_LINES.sub("\n\n", text)
    return text.strip()


def _guard_length(text: str, what: str) -> str:
    cleaned = tidy(text)
    if len(cleaned) < MIN_USABLE_CHARS:
        raise ParseError(
            f"Only got {len(cleaned)} characters of text from {what}. "
            "If this is a scanned document or a screenshot, try the image "
            "upload instead; otherwise paste the text directly."
        )
    return cleaned


# --------------------------------------------------------------------------- #
# Plain text
# --------------------------------------------------------------------------- #


def from_text(raw: str) -> str:
    """Pasted text. Still length-guarded — an empty paste is a common slip."""
    return _guard_length(raw, "the pasted text")


# --------------------------------------------------------------------------- #
# PDF
# --------------------------------------------------------------------------- #


def from_pdf(data: bytes) -> str:
    """Extract text from a PDF byte stream.

    Text-layer only. A scanned PDF has no text layer and will trip the length
    guard, which tells the user to use image upload — running OCR over every
    page automatically would turn a fast path into a slow one for everybody.
    """
    try:
        from pypdf import PdfReader
    except ImportError as e:  # pragma: no cover
        raise ParseError("PDF support is not installed (pip install pypdf).") from e

    try:
        reader = PdfReader(io.BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages]
    except Exception as e:
        raise ParseError(f"Could not read that PDF: {e}") from e

    return _guard_length("\n\n".join(pages), "the PDF")


# --------------------------------------------------------------------------- #
# Image (OCR)
# --------------------------------------------------------------------------- #


def from_image(data: bytes) -> str:
    """OCR an image — typically a screenshot of a posting.

    Requires the Tesseract binary on the host; `pytesseract` is only a wrapper.
    The error message says so explicitly, because "TesseractNotFoundError" is
    not a useful thing to show a user.
    """
    try:
        import pytesseract
        from PIL import Image
    except ImportError as e:  # pragma: no cover
        raise ParseError(
            "Image support is not installed (pip install pillow pytesseract)."
        ) from e

    if settings.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd

    try:
        image = Image.open(io.BytesIO(data))
        # Greyscale first: screenshots of dark-mode job boards OCR much better
        # without the colour channel confusing the thresholding.
        text = pytesseract.image_to_string(image.convert("L"))
    except pytesseract.TesseractNotFoundError as e:
        raise ParseError(
            "Tesseract OCR is not installed on this machine, or its path is "
            "not set. Install it and set TESSERACT_CMD in .env."
        ) from e
    except Exception as e:
        raise ParseError(f"Could not read that image: {e}") from e

    return _guard_length(text, "the image")


# --------------------------------------------------------------------------- #
# URL
# --------------------------------------------------------------------------- #

#: Elements that never contain the posting and reliably pollute the text.
_STRIP_TAGS = (
    "script",
    "style",
    "nav",
    "header",
    "footer",
    "aside",
    "noscript",
    "svg",
    "form",
)

#: Tried in order; the first that yields usable text wins. Most job boards put
#: the posting in one of these.
_CONTENT_SELECTORS = (
    "article",
    "main",
    '[class*="job-description"]',
    '[class*="jobDescription"]',
    '[class*="description"]',
    '[id*="job-description"]',
    '[role="main"]',
)

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)


def from_url(url: str, timeout: float = 20.0) -> str:
    """Fetch a URL and pull the posting text out of the HTML.

    Single-shot fetch, no JavaScript. Boards that render the posting client-side
    return a shell that trips the length guard; the user is told to paste
    instead. Adding a headless browser would be the fix, and it is deliberately
    out of scope — it triples the deployment footprint for a minority of URLs.
    """
    if not url.startswith(("http://", "https://")):
        raise ParseError("That doesn't look like a URL. It needs to start with https://.")

    try:
        response = httpx.get(
            url,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": _BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"},
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        if code in (401, 403):
            raise ParseError(
                f"That site refused the request ({code}) — it likely requires a "
                "login. Open the posting and paste the text instead."
            ) from e
        raise ParseError(f"That URL returned {code}.") from e
    except httpx.TimeoutException as e:
        raise ParseError(f"That URL took longer than {timeout:g}s to respond.") from e
    except httpx.HTTPError as e:
        raise ParseError(f"Could not fetch that URL: {e}") from e

    tree = HTMLParser(response.text)
    for tag in _STRIP_TAGS:
        for node in tree.css(tag):
            node.decompose()

    # Try each container, keep the longest plausible hit. Longest wins because
    # a nested `[class*="description"]` often matches a short teaser as well as
    # the full body.
    best = ""
    for selector in _CONTENT_SELECTORS:
        for node in tree.css(selector):
            candidate = tidy(node.text(separator="\n"))
            if len(candidate) > len(best):
                best = candidate

    if len(best) < MIN_USABLE_CHARS and tree.body is not None:
        best = tidy(tree.body.text(separator="\n"))

    return _guard_length(best, "that page")
