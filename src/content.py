"""Content analysis (spec FR-5, task T7).

Derives render status, last-update / copyright signals, maintenance signals,
parked / placeholder detection, obsolete-branding signals, and mail-form
detection from a fetched HttpResult's HTML body.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

from bs4 import BeautifulSoup

from . import brands
from .models import ContentResult, HttpResult

log = logging.getLogger(__name__)

CURRENT_YEAR = datetime.now().year

# Parking / for-sale signals.
PARKING_SIGNALS = (
    "domain is for sale",
    "this domain is for sale",
    "buy this domain",
    "the domain you are looking for is parked",
    "parked free, courtesy of",
    "domain parking",
    "this web page is parked",
    "is parked",
    "domain for sale",
    "this domain may be for sale",
    "godaddy.com",
    "sedo.com",
    "hugedomains",
    "inquire about this domain",
    "domain name is available",
)

# Placeholder / default-server signals.
PLACEHOLDER_SIGNALS = (
    "index of /",
    "it works!",
    "welcome to nginx",
    "apache2 ubuntu default page",
    "default web site page",
    "site under construction",
    "coming soon",
    "under construction",
    "test page for the apache",
    "future home of something quite cool",
    "iis windows server",
)

# Maintenance / activity signals (presence implies active upkeep).
MAINTENANCE_HINTS = (
    "news", "blog", "events", "webinar", "press release", "careers",
    "products", "solutions", "support", "contact us", "newsletter",
    "sign in", "log in", "register", "shop", "store", "resources",
)

COPYRIGHT_RE = re.compile(
    r"(?:\u00a9|&copy;|copyright|\(c\))\s*[^0-9]{0,20}(20\d{2})(?:\s*[-\u2013]\s*(20\d{2}))?",
    re.IGNORECASE,
)
ANY_YEAR_RE = re.compile(r"\b(20\d{2})\b")
DATE_META_NAMES = (
    "article:modified_time",
    "og:updated_time",
    "last-modified",
    "date",
    "dcterms.modified",
    "revised",
)


def _visible_text(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    return soup.get_text(separator=" ", strip=True)


def _extract_copyright_year(text: str) -> int | None:
    best: int | None = None
    for m in COPYRIGHT_RE.finditer(text):
        for g in m.groups():
            if g:
                y = int(g)
                if 2000 <= y <= CURRENT_YEAR + 1:
                    best = max(best or 0, y)
    return best


def _extract_meta_date(soup: BeautifulSoup) -> str | None:
    for meta in soup.find_all("meta"):
        name = (meta.get("property") or meta.get("name") or "").lower()
        if name in DATE_META_NAMES:
            content = (meta.get("content") or "").strip()
            if content:
                return content
    # <time datetime="...">
    t = soup.find("time")
    if t and t.get("datetime"):
        return t.get("datetime").strip()
    return None


def _detect_mail_form(soup: BeautifulSoup) -> bool:
    if soup.find("input", attrs={"type": "email"}):
        return True
    for form in soup.find_all("form"):
        action = (form.get("action") or "").lower()
        if "mail" in action or "contact" in action or "subscribe" in action \
                or "newsletter" in action:
            return True
    if soup.find("a", href=re.compile(r"^mailto:", re.IGNORECASE)):
        return True
    return False


def analyze(http_result: HttpResult) -> ContentResult:
    """Analyze the HTML of an HttpResult into a ContentResult."""
    result = ContentResult()

    if http_result is None or not http_result.reachable:
        result.render_status = "Unknown" if (http_result and http_result.http_error
                                             and "Timeout" in (http_result.http_error or "")) else "No"
        return result

    html = http_result.html or ""
    status = http_result.status_code or 0

    if not html.strip():
        # Reachable but empty body.
        result.render_status = "No"
        return result

    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")

    title = (soup.title.string.strip() if soup.title and soup.title.string else None)
    result.title = title

    text = _visible_text(soup)
    low_text = text.lower()
    low_html = html.lower()
    text_len = len(text)

    # --- Parking / placeholder detection ---------------------------------- #
    result.parked = any(sig in low_text or sig in low_html for sig in PARKING_SIGNALS) \
        and text_len < 4000
    result.placeholder = (
        any(sig in low_text for sig in PLACEHOLDER_SIGNALS)
        or (text_len < 80 and not result.parked)
    )

    # --- Obsolete branding ------------------------------------------------- #
    result.obsolete_branding = brands.is_legacy_term(low_text[:20000])

    # --- Last-update / copyright ------------------------------------------ #
    meta_date = _extract_meta_date(soup)
    cyear = _extract_copyright_year(text)
    result.copyright_year = cyear
    if meta_date:
        result.last_update = meta_date
    elif cyear:
        result.last_update = str(cyear)
    else:
        # Fall back to the most recent plausible year mentioned on the page.
        years = [int(y) for y in ANY_YEAR_RE.findall(low_text) if 2000 <= int(y) <= CURRENT_YEAR + 1]
        if years:
            result.last_update = str(max(years))

    # --- Maintenance signals ---------------------------------------------- #
    signals = [hint for hint in MAINTENANCE_HINTS if hint in low_text]
    result.maintenance_signals = signals

    # --- Mail form -------------------------------------------------------- #
    result.has_mail_form = _detect_mail_form(soup)

    # --- Render status ---------------------------------------------------- #
    has_body_text = text_len >= 200
    has_title = bool(title)
    is_error_status = status >= 400

    if is_error_status:
        result.render_status = "No"
    elif result.parked or result.placeholder:
        result.render_status = "Partial"
    elif has_title and has_body_text:
        result.render_status = "Yes"
    elif has_title or text_len >= 50:
        # JS-only shell or thin page.
        result.render_status = "Partial"
    else:
        result.render_status = "No"

    return result
