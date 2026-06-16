"""Summary and pattern analysis (spec Section 6.2/6.3, task T13).

Computes the six required metrics plus pattern groupings (multi-TLD bundles,
campaign domains, partner/vendor, legacy brand, typo variants, regional
clusters) from the classified rows.
"""

from __future__ import annotations

from collections import defaultdict

from . import brands
from .models import ClassifiedDomain, Summary


def _label_and_tld(domain: str) -> tuple[str, str]:
    parts = domain.split(".", 1)
    if len(parts) == 2:
        return parts[0], parts[1]
    return domain, ""


def _multi_tld_bundles(rows: list[ClassifiedDomain]) -> list[str]:
    by_label: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        label, tld = _label_and_tld(r.domain)
        if tld:
            by_label[label].add(tld)
    examples = []
    for label, tlds in sorted(by_label.items()):
        if len(tlds) > 1:
            examples.append(f"{label}.* ({len(tlds)} TLDs)")
    return examples


def _campaign_domains(rows: list[ClassifiedDomain]) -> list[str]:
    out = []
    for r in rows:
        label, _ = _label_and_tld(r.domain)
        if label in brands.CAMPAIGN_TERMS or "Campaign" in (r.redirect_target or ""):
            out.append(r.domain)
    return out


def _partner_vendor(rows: list[ClassifiedDomain]) -> list[str]:
    return [r.domain for r in rows if brands.PARTNER in (r.redirect_target or "")
            or "AVT" in (r.source or "") or "Avnet" in (r.source or "")]


def _legacy_brand(rows: list[ClassifiedDomain]) -> list[str]:
    out = []
    for r in rows:
        label, _ = _label_and_tld(r.domain)
        if (label in brands.LEGACY_TERMS or r.content_status == "Legacy"
                or brands.LEGACY in (r.redirect_target or "")):
            out.append(r.domain)
    return out


def _typo_variants(rows: list[ClassifiedDomain]) -> list[str]:
    """Labels that are near-misses of a brand term (edit distance 1-2)."""
    out = []
    brand_terms = [t for t in brands.BRAND_TERMS if len(t) >= 5]
    for r in rows:
        label, _ = _label_and_tld(r.domain)
        if label in brands.BRAND_TERMS:
            continue
        for term in brand_terms:
            d = _edit_distance(label, term)
            if 0 < d <= 2 and abs(len(label) - len(term)) <= 2:
                out.append(f"{r.domain} (~{term})")
                break
    return out


def _regional_clusters(rows: list[ClassifiedDomain]) -> list[str]:
    by_region: dict[str, int] = defaultdict(int)
    for r in rows:
        by_region[r.region or "Unclassified"] += 1
    return [f"{region}: {count}" for region, count in
            sorted(by_region.items(), key=lambda kv: kv[1], reverse=True)]


def _edit_distance(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def summarize(rows: list[ClassifiedDomain]) -> Summary:
    s = Summary(total=len(rows))
    for r in rows:
        rec = r.release_recommendation
        if rec == "Keep":
            s.keep += 1
        elif rec == "Review":
            s.review += 1
        elif rec == "Candidate for release":
            s.candidate_release += 1
        elif rec == "Do not release":
            s.do_not_release += 1
        else:
            s.unknown += 1
        if r.email_functionality in ("Yes", "Unknown"):
            s.email_dependency += 1
        if r.defensive_likelihood == "High":
            s.defensive_high += 1

    s.patterns = {
        "Multi-TLD bundles": _multi_tld_bundles(rows),
        "Campaign / landing domains": _campaign_domains(rows),
        "Partner / vendor domains": _partner_vendor(rows),
        "Legacy brand domains": _legacy_brand(rows),
        "Typo / abbreviation variants": _typo_variants(rows),
        "Regional clusters": _regional_clusters(rows),
    }
    return s
