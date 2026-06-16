"""Validation against EU seed data (spec FR-12, task T15).

Cross-checks pipeline output for the ``EU Web Site URLs`` rows against that
sheet's ``Site Status`` (and ``Business Purpose``) as a sanity check, reporting
an agreement rate and the notable mismatches.

Run with:  py -m src.validate
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .ingest import DEFAULT_SOURCE, load_domains
from .models import ClassifiedDomain
from .orchestrator import run as orchestrate

log = logging.getLogger(__name__)

# Map EU "Site Status" to an expected liveness for our pipeline.
#   live      -> we expect website_behind_url == "Yes"
#   not_live  -> we expect website_behind_url == "No"
#   redirect  -> we expect redirect == "Yes"
#   skip      -> excluded from the agreement rate (ambiguous)
STATUS_EXPECTATION = {
    "in production": "live",
    "plan to retire": "live",
    "in development": "live",
    "retired": "not_live",
    "redirected": "redirect",
    "undefined": "skip",
}


def _predicted(row: ClassifiedDomain) -> str:
    """Reduce a classified row to live / not_live / redirect / indeterminate."""
    if row.redirect == "Yes":
        return "redirect"
    if row.website_behind_url == "Yes":
        return "live"
    if row.website_behind_url == "No":
        return "not_live"
    return "indeterminate"


def _agrees(expected: str, predicted: str) -> bool | None:
    """True/False agreement, or None if indeterminate / not comparable."""
    if predicted == "indeterminate":
        return None
    if expected == "redirect":
        return predicted == "redirect"
    if expected == "live":
        # A live site that also redirects still counts as "present".
        return predicted in ("live", "redirect")
    if expected == "not_live":
        return predicted == "not_live"
    return None


def validate(
    source: str | Path = DEFAULT_SOURCE,
    *,
    workers: int = 16,
    cache_dir: str | Path = "cache",
    use_cache: bool = True,
) -> dict:
    """Run the pipeline on the EU-seeded domains and compute agreement."""
    domains = load_domains(source)
    seeded = [d for d in domains if d.seed_site_status]
    log.info("validation: %d EU-seeded domains found in the inventory", len(seeded))

    rows = orchestrate(seeded, workers=workers, cache_dir=cache_dir,
                       use_cache=use_cache)
    by_domain = {r.domain: r for r in rows}
    seed_status = {d.domain: (d.seed_site_status or "").strip() for d in seeded}

    comparable = 0
    agree = 0
    indeterminate = 0
    skipped = 0
    mismatches: list[tuple[str, str, str, str]] = []

    for dom, status in seed_status.items():
        row = by_domain.get(dom)
        if row is None:
            continue
        expectation = STATUS_EXPECTATION.get(status.lower(), "skip")
        if expectation == "skip":
            skipped += 1
            continue
        predicted = _predicted(row)
        verdict = _agrees(expectation, predicted)
        if verdict is None:
            indeterminate += 1
            continue
        comparable += 1
        if verdict:
            agree += 1
        else:
            mismatches.append((dom, status, predicted, row.evidence_notes))

    rate = (agree / comparable * 100) if comparable else 0.0

    report_lines = [
        "=" * 72,
        "EU SEED-DATA VALIDATION REPORT",
        "=" * 72,
        f"EU-seeded domains evaluated : {len(seeded)}",
        f"Comparable (live/not-live/redirect): {comparable}",
        f"  Agreements                : {agree}",
        f"  Mismatches                : {len(mismatches)}",
        f"Indeterminate (transient/Unknown)  : {indeterminate}",
        f"Skipped (ambiguous status)         : {skipped}",
        f"AGREEMENT RATE              : {rate:.1f}%",
        "",
        "Notable mismatches (EU status vs pipeline prediction):",
    ]
    for dom, status, predicted, ev in mismatches[:40]:
        report_lines.append(f"  - {dom}: EU='{status}' pipeline='{predicted}'")
        report_lines.append(f"      evidence: {ev[:140]}")
    if not mismatches:
        report_lines.append("  (none)")

    report = "\n".join(report_lines)

    return {
        "seeded": len(seeded),
        "comparable": comparable,
        "agree": agree,
        "mismatches": mismatches,
        "indeterminate": indeterminate,
        "skipped": skipped,
        "rate": rate,
        "report": report,
    }


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="src.validate",
                                description="Validate pipeline against EU seed data")
    p.add_argument("--source", default=DEFAULT_SOURCE)
    p.add_argument("--workers", type=int, default=16)
    p.add_argument("--cache-dir", default="cache")
    p.add_argument("--no-cache", action="store_true")
    p.add_argument("--out", default="output/validation_report.txt")
    args = p.parse_args(argv)

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")

    result = validate(args.source, workers=args.workers, cache_dir=args.cache_dir,
                      use_cache=not args.no_cache)
    print("\n" + result["report"])

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(result["report"], encoding="utf-8")
    log.info("validation report written to %s", out)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
