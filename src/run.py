"""CLI entry point (task T14).

Ties ingest -> orchestrate -> output -> summary together.

Examples
--------
    py -m src.run --limit 10          # smoke run on 10 domains
    py -m src.run --workers 24        # full run
    py -m src.run --no-cache          # bypass the on-disk cache
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

from .ingest import DEFAULT_SOURCE, load_domains
from .orchestrator import run as orchestrate
from .output import write_csv, write_xlsx
from .summary import summarize


def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="src.run",
        description="Worldwide Domain Inventory Analysis Pipeline",
    )
    p.add_argument("--source", default=DEFAULT_SOURCE,
                   help="source workbook path (default: %(default)s)")
    p.add_argument("--out-dir", default="output",
                   help="output directory (default: %(default)s)")
    p.add_argument("--cache-dir", default="cache",
                   help="on-disk cache directory (default: %(default)s)")
    p.add_argument("--workers", type=int, default=16,
                   help="concurrent worker threads (default: %(default)s)")
    p.add_argument("--limit", type=int, default=0,
                   help="process only the first N domains (0 = all)")
    p.add_argument("--no-cache", action="store_true",
                   help="bypass the on-disk cache")
    p.add_argument("--verbose", "-v", action="store_true", help="debug logging")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    log = logging.getLogger("run")

    start = time.time()

    source = Path(args.source)
    if not source.exists():
        log.error("source workbook not found: %s", source)
        return 2

    domains = load_domains(source)
    if args.limit and args.limit > 0:
        domains = domains[: args.limit]
        log.info("limiting run to first %d domains", len(domains))

    rows = orchestrate(
        domains,
        workers=args.workers,
        cache_dir=args.cache_dir,
        use_cache=not args.no_cache,
    )

    summary = summarize(rows)

    out_dir = Path(args.out_dir)
    csv_path = write_csv(rows, out_dir / "domain_inventory.csv")
    xlsx_path = write_xlsx(rows, summary, out_dir / "domain_inventory.xlsx")

    elapsed = time.time() - start
    log.info("=" * 60)
    log.info("DONE in %.1fs - %d domains", elapsed, summary.total)
    log.info("  Keep=%d Review=%d Candidate=%d DoNotRelease=%d Unknown=%d",
             summary.keep, summary.review, summary.candidate_release,
             summary.do_not_release, summary.unknown)
    log.info("  Email-dependency=%d  Defensive-High=%d",
             summary.email_dependency, summary.defensive_high)
    log.info("  CSV : %s", csv_path)
    log.info("  XLSX: %s", xlsx_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
