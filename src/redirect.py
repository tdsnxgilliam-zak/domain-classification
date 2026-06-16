"""Redirect target classification (spec FR-7 / 5.2, task T9).

Decides whether a domain redirects and classifies the final target into the
spec categories using the ``brands`` map.
"""

from __future__ import annotations

from . import brands
from .ingest import registrable_domain
from .models import HttpResult


def classify_target(http_result: HttpResult, origin_domain: str | None = None) -> tuple[str, str]:
    """Return ``(redirect, target)``.

    ``redirect`` is one of Yes / No / Unknown. ``target`` is either the final
    URL (when not redirecting / staying on-domain) or a spec category string for
    off-domain redirects, plus the final URL for traceability.
    """
    if http_result is None or not http_result.reachable:
        return "Unknown", "Unknown"

    final_url = http_result.final_url or ""
    chain = http_result.redirect_chain or []

    # Determine the origin registrable domain.
    origin = registrable_domain(origin_domain) if origin_domain else None
    if not origin and chain:
        origin = registrable_domain(chain[0])

    final_reg = registrable_domain(final_url)

    # An error status at the end is an error page regardless of hops.
    status = http_result.status_code or 0
    if status >= 400:
        return ("Yes" if http_result.redirected_offdomain or len(chain) > 1 else "No",
                f"{brands.ERROR_PAGE} ({final_url})")

    # No redirect hops and same domain -> No.
    multi_hop = len(chain) > 1
    offdomain = http_result.redirected_offdomain

    if not multi_hop and not offdomain:
        return "No", final_url or (chain[0] if chain else "Unknown")

    # There is a redirect.
    if offdomain and final_reg:
        category = brands.categorize_domain(final_reg, final_url)
        return "Yes", f"{category} ({final_url})"

    # On-domain redirect (e.g. http->https or path change).
    return "Yes", final_url
