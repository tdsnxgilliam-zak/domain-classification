"""HTTP / redirect / TLS checks (spec FR-4, task T6).

Attempts HTTPS then HTTP (with a ``www.`` fallback), follows redirects, and
records status code(s), final URL, the redirect chain, an off-domain flag, TLS
errors, elapsed time, and the HTML body. Never raises for network problems.
"""

from __future__ import annotations

import logging
import time

import requests
import urllib3
from requests.exceptions import (
    ConnectionError as ReqConnectionError,
    ReadTimeout,
    ConnectTimeout,
    Timeout,
    TooManyRedirects,
    SSLError,
)

from .ingest import registrable_domain
from .models import HttpResult

log = logging.getLogger(__name__)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_TIMEOUT = (5, 12)  # (connect, read) seconds
MAX_BYTES = 2_000_000      # cap stored HTML at ~2 MB


def _headers() -> dict:
    return {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }


def _attempt(url: str, timeout) -> tuple[requests.Response | None, str | None, str | None]:
    """One GET attempt. Returns (response, tls_error, http_error)."""
    try:
        resp = requests.get(
            url,
            headers=_headers(),
            timeout=timeout,
            allow_redirects=True,
            verify=True,
            stream=False,
        )
        return resp, None, None
    except SSLError as exc:
        # Retry once without verification so we can still read the body and
        # record that a TLS error exists.
        try:
            resp = requests.get(
                url,
                headers=_headers(),
                timeout=timeout,
                allow_redirects=True,
                verify=False,
                stream=False,
            )
            return resp, f"SSLError:{_short(exc)}", None
        except Exception as exc2:
            return None, f"SSLError:{_short(exc)}", _short(exc2)
    except (ConnectTimeout, ReadTimeout, Timeout) as exc:
        return None, None, f"Timeout:{_short(exc)}"
    except TooManyRedirects as exc:
        return None, None, f"TooManyRedirects:{_short(exc)}"
    except ReqConnectionError as exc:
        return None, None, f"ConnectionError:{_short(exc)}"
    except Exception as exc:  # pragma: no cover - defensive
        return None, None, f"{type(exc).__name__}:{_short(exc)}"


def _short(exc: object, n: int = 120) -> str:
    s = str(exc).replace("\n", " ").strip()
    return s[:n]


def _build_result(domain: str, resp: requests.Response, scheme: str,
                  tls_error: str | None, elapsed_ms: int) -> HttpResult:
    chain = [r.url for r in resp.history] + [resp.url]
    final_url = resp.url
    final_reg = registrable_domain(final_url)
    origin_reg = registrable_domain(domain)
    offdomain = bool(final_reg) and bool(origin_reg) and final_reg != origin_reg

    text = ""
    try:
        content = resp.content[:MAX_BYTES]
        encoding = resp.encoding or resp.apparent_encoding or "utf-8"
        text = content.decode(encoding, errors="replace")
    except Exception:
        text = resp.text[:MAX_BYTES] if resp.text else ""

    return HttpResult(
        reachable=True,
        scheme_used=scheme,
        final_url=final_url,
        status_code=resp.status_code,
        redirect_chain=chain,
        redirected_offdomain=offdomain,
        tls_error=tls_error,
        http_error=None,
        elapsed_ms=elapsed_ms,
        html=text,
    )


def fetch(domain: str, *, timeout=DEFAULT_TIMEOUT) -> HttpResult:
    """Fetch ``domain`` trying HTTPS, HTTP, and www. variants in order."""
    if not domain:
        return HttpResult(http_error="EmptyDomain")

    attempts = [
        ("https", f"https://{domain}"),
        ("https", f"https://www.{domain}"),
        ("http", f"http://{domain}"),
        ("http", f"http://www.{domain}"),
    ]

    last_tls_error: str | None = None
    last_http_error: str | None = None

    for scheme, url in attempts:
        start = time.monotonic()
        resp, tls_error, http_error = _attempt(url, timeout)
        elapsed_ms = int((time.monotonic() - start) * 1000)

        if tls_error:
            last_tls_error = tls_error
        if http_error:
            last_http_error = http_error

        if resp is not None:
            return _build_result(domain, resp, scheme, tls_error, elapsed_ms)

    # All attempts failed.
    return HttpResult(
        reachable=False,
        tls_error=last_tls_error,
        http_error=last_http_error or "Unreachable",
    )
