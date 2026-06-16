"""Orchestrator (spec FR-10, task T11).

Thread-pooled execution of DNS + HTTP + content + email + redirect + classify per
domain, with an on-disk JSON cache keyed by domain (resumable), per-domain error
capture that never aborts the run, and progress logging.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from . import content as content_mod
from . import dns_checks, http_checks, redirect as redirect_mod
from .classify import classify
from .email import assess
from .models import (
    ClassifiedDomain,
    ContentResult,
    DnsResult,
    HttpResult,
    InputDomain,
)

log = logging.getLogger(__name__)

DEFAULT_WORKERS = 16
DEFAULT_CACHE_DIR = "cache"

_SAFE = re.compile(r"[^a-z0-9._-]+")


def _cache_path(cache_dir: Path, domain: str) -> Path:
    safe = _SAFE.sub("_", domain.lower())
    return cache_dir / f"{safe}.json"


def _gather_evidence(
    domain: str, cache_dir: Path, use_cache: bool
) -> tuple[DnsResult, HttpResult, ContentResult, bool]:
    """Return (dns, http, content, from_cache) for a single domain.

    Network results (DNS + HTTP including HTML) are cached on disk. Content is
    re-derived from the cached HTML so logic changes apply without refetching.
    """
    path = _cache_path(cache_dir, domain)
    if use_cache and path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            dns = DnsResult.from_dict(data["dns"])
            http = HttpResult.from_dict(data["http"])
            content = content_mod.analyze(http)
            return dns, http, content, True
        except Exception as exc:  # corrupt cache -> refetch
            log.warning("cache read failed for %s (%s); refetching", domain, exc)

    dns = dns_checks.resolve(domain)
    http = http_checks.fetch(domain)
    content = content_mod.analyze(http)

    # Persist network evidence, but never cache a transient failure so reruns
    # can recover it (spec FR-10: distinguish Unknown from definitive No).
    if not _is_transient_failure(dns, http):
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            payload = {"domain": domain, "dns": dns.to_dict(), "http": http.to_dict()}
            path.write_text(json.dumps(payload), encoding="utf-8")
        except Exception as exc:  # pragma: no cover - disk issue
            log.warning("cache write failed for %s (%s)", domain, exc)

    return dns, http, content, False


def _is_transient_failure(dns: DnsResult, http: HttpResult) -> bool:
    """True if evidence looks like a transient network failure worth retrying."""
    dns_transient = (not dns.resolves) and dns.error == "Timeout"
    http_transient = (not http.reachable) and bool(http.http_error) \
        and "Timeout" in (http.http_error or "")
    return dns_transient or http_transient


def _process_one(
    inp: InputDomain, cache_dir: Path, use_cache: bool, bundle_labels: set[str]
) -> ClassifiedDomain:
    """Run the full per-domain pipeline; never raises."""
    try:
        dns, http, content, _ = _gather_evidence(inp.domain, cache_dir, use_cache)
        email = assess(dns, content)
        redirect = redirect_mod.classify_target(http, inp.domain)
        label = inp.domain.split(".")[0]
        bundle_member = label in bundle_labels
        return classify(inp, dns, http, content, email, redirect,
                        bundle_member=bundle_member)
    except Exception as exc:  # pragma: no cover - defensive
        log.exception("classification failed for %s", inp.domain)
        return ClassifiedDomain(
            domain=inp.domain,
            evidence_notes=f"pipeline error: {type(exc).__name__}: {exc}",
            region=inp.region,
            source=inp.source,
            country=inp.country,
            error=f"{type(exc).__name__}: {exc}",
        )


def _bundle_labels(domains: list[InputDomain]) -> set[str]:
    """Second-level labels that appear under more than one TLD (multi-TLD bundle)."""
    by_label: dict[str, set[str]] = {}
    for d in domains:
        parts = d.domain.split(".", 1)
        if len(parts) == 2:
            by_label.setdefault(parts[0], set()).add(parts[1])
    return {label for label, tlds in by_label.items() if len(tlds) > 1}


def run(
    domains: list[InputDomain],
    *,
    workers: int = DEFAULT_WORKERS,
    cache_dir: str | Path = DEFAULT_CACHE_DIR,
    use_cache: bool = True,
    progress_every: int = 25,
) -> list[ClassifiedDomain]:
    """Classify all ``domains`` concurrently, returning rows in input order."""
    cache_dir = Path(cache_dir)
    bundle_labels = _bundle_labels(domains)
    total = len(domains)
    results: dict[str, ClassifiedDomain] = {}
    done = 0
    lock = threading.Lock()

    log.info("orchestrator: %d domains, %d workers, cache=%s (%s)",
             total, workers, cache_dir, "on" if use_cache else "off")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_process_one, inp, cache_dir, use_cache, bundle_labels): inp
            for inp in domains
        }
        for fut in as_completed(futures):
            inp = futures[fut]
            row = fut.result()
            results[inp.domain] = row
            with lock:
                done += 1
                if done % progress_every == 0 or done == total:
                    log.info("  progress: %d/%d", done, total)

    # Preserve input order.
    ordered = [results[inp.domain] for inp in domains if inp.domain in results]
    log.info("orchestrator: completed %d rows (%d errors)",
             len(ordered), sum(1 for r in ordered if r.error))
    return ordered
