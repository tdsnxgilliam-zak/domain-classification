"""DNS checks (spec FR-3, task T5).

Resolves A / AAAA / CNAME / MX / TXT(SPF) / _dmarc(DMARC) and probes a small set
of common DKIM selectors. Every failure is captured as a typed error reason;
this module never raises for resolution problems.
"""

from __future__ import annotations

import logging

import dns.exception
import dns.resolver

from .models import DnsResult

log = logging.getLogger(__name__)

# Common DKIM selectors to probe at <selector>._domainkey.<domain>.
DKIM_SELECTORS = ("default", "google", "selector1", "selector2", "k1", "dkim", "mail", "s1")

DEFAULT_TIMEOUT = 2.5
DEFAULT_LIFETIME = 3.0

# Reliable public resolvers - far more dependable under concurrency than the
# local stub resolver, which silently times out when overwhelmed.
PUBLIC_NAMESERVERS = ["8.8.8.8", "1.1.1.1", "8.8.4.4", "1.0.0.1"]


def _make_resolver(timeout: float, lifetime: float) -> dns.resolver.Resolver:
    r = dns.resolver.Resolver(configure=False)
    r.nameservers = list(PUBLIC_NAMESERVERS)
    r.timeout = timeout
    r.lifetime = lifetime
    return r


def _query(resolver, name: str, rtype: str, retries: int = 1) -> tuple[list[str], str | None]:
    """Run one query (with a retry on timeout); return (records, error_reason)."""
    last_err = None
    for attempt in range(retries + 1):
        try:
            answers = resolver.resolve(name, rtype)
            return [r.to_text().strip().strip('"') for r in answers], None
        except dns.resolver.NXDOMAIN:
            return [], "NXDOMAIN"
        except dns.resolver.NoAnswer:
            return [], "NoAnswer"
        except dns.resolver.NoNameservers:
            return [], "NoNameservers"
        except (dns.resolver.LifetimeTimeout, dns.exception.Timeout):
            last_err = "Timeout"
            continue  # retry timeouts
        except dns.exception.DNSException as exc:
            return [], type(exc).__name__
        except Exception as exc:  # pragma: no cover - defensive
            return [], f"Error:{type(exc).__name__}"
    return [], last_err or "Timeout"


def resolve(
    domain: str,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    lifetime: float = DEFAULT_LIFETIME,
    dkim_selectors: tuple[str, ...] = DKIM_SELECTORS,
) -> DnsResult:
    """Resolve all DNS records for ``domain`` into a DnsResult."""
    result = DnsResult()
    if not domain:
        result.error = "EmptyDomain"
        return result

    resolver = _make_resolver(timeout, lifetime)

    a, a_err = _query(resolver, domain, "A")

    # Short-circuit when the authoritative nameservers do not exist or are
    # unresponsive: further record types would only repeat the same failure.
    if not a and a_err in ("NXDOMAIN", "Timeout", "NoNameservers"):
        result.error = a_err
        return result

    aaaa, _ = _query(resolver, domain, "AAAA")
    cname, _ = _query(resolver, domain, "CNAME")

    result.a = a
    result.aaaa = aaaa
    result.cname = cname

    # A domain "resolves" if it has any address/cname record.
    result.resolves = bool(a or aaaa or cname)

    if not result.resolves:
        result.error = a_err or "NoAddress"

    # Mail-related records (queried even if A failed, in case of MX-only setups).
    mx, _ = _query(resolver, domain, "MX")
    result.mx = mx
    if mx and not result.resolves:
        # MX-only domains still "resolve" in the mail sense; mark resolves True
        # so email assessment treats it as a live domain.
        result.resolves = True
        result.error = None

    # SPF / DMARC TXT records.
    txt, _ = _query(resolver, domain, "TXT")
    for rec in txt:
        low = rec.lower()
        if low.startswith("v=spf1") or "v=spf1" in low:
            result.spf = rec
            break

    dmarc_txt, _ = _query(resolver, f"_dmarc.{domain}", "TXT")
    for rec in dmarc_txt:
        if "v=dmarc1" in rec.lower():
            result.dmarc = rec
            break

    # DKIM selector probing (only if domain resolves / has MX to limit work).
    if result.resolves or mx:
        found = []
        for sel in dkim_selectors:
            recs, _ = _query(resolver, f"{sel}._domainkey.{domain}", "TXT")
            if any("v=dkim1" in r.lower() or "p=" in r.lower() for r in recs):
                found.append(sel)
        result.dkim_selectors = found

    return result
