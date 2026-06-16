# Worldwide Domain Inventory Analysis Pipeline

A pure-Python heuristic pipeline that classifies every domain listed in
`url-regional-class.xlsx`, collecting DNS, HTTP/redirect/TLS, content, and email
evidence, and writes a deliverable CSV + xlsx workbook. The source workbook is
never modified.

See [`docs/spec.md`](docs/spec.md) for the specification, [`docs/research.md`](docs/research.md)
for the research phase, and [`docs/tasks.md`](docs/tasks.md) for the build tasks.

## Requirements

- Python 3.13 (uses the `py` launcher on Windows)
- Network access at run time (for DNS + HTTP checks)

## Install

```bash
py -m pip install -r requirements.txt
```

## Run

Smoke run on a handful of domains:

```bash
py -m src.run --limit 10
```

Full run (all 945 domains):

```bash
py -m src.run --workers 24
```

### CLI options

| Flag | Default | Meaning |
| --- | --- | --- |
| `--source` | `url-regional-class.xlsx` | Source workbook path |
| `--out-dir` | `output` | Output directory for CSV + xlsx |
| `--cache-dir` | `cache` | On-disk JSON cache directory |
| `--workers` | `16` | Concurrent worker threads |
| `--limit` | `0` (all) | Process only the first N domains (smoke runs) |
| `--no-cache` | off | Ignore and bypass the on-disk cache |

## Outputs

- `output/domain_inventory.csv` - master CSV, one row per domain.
- `output/domain_inventory.xlsx` - Inventory sheet + Summary sheet.

## Validation

```bash
py -m src.validate
```

Cross-checks pipeline output for `EU Web Site URLs` rows against that sheet's
`Site Status` / `Business Purpose` and reports an agreement rate.

## Deliverable summary (full run)

The full pipeline classified all **945 unique domains** (deduplicated from the
eight source sheets: NA 60, EMEA 293, LATAM 39, APJ 48, NA-Public Sector 26,
Hyve 16, Shyft 3, Non-Classified 460). The source workbook was verified
byte-identical (SHA-256) before and after the run.

### Release recommendations

| Recommendation | Count |
| --- | ---: |
| Do not release | 574 |
| Candidate for release | 157 |
| Review | 25 |
| Keep | 5 |
| Unknown (checks could not complete) | 184 |
| **Total** | **945** |

- **Possible email dependencies** (MX / SPF+DMARC / mail form, or unclear): **470**
- **Likely defensive / brand-protective (High)**: **460**

### Content status

Non-responsive 427, Unknown 251, Broken 132, Placeholder 73, Maintained 25,
Active 21, Legacy 14, Outdated 2.

### Pattern groupings

Multi-TLD bundles 95, partner/vendor domains 167, legacy-brand domains 147,
typo/abbreviation variants 22, campaign/landing domains 12, and 8 regional
clusters. (Full detail in the **Summary** sheet of `domain_inventory.xlsx`.)

### Interpretation notes

- The large `Do not release` count reflects that most of the portfolio is
  brand-protective (TD SYNNEX / Tech Data / SYNNEX / Avnet / Hyve / StreamOne
  labels) and/or carries live mail records — both of which block release.
- The **184 `Unknown`** rows are domains whose nameservers or web servers
  consistently time out (verified stable across three runs). Per the spec these
  are reported as `Unknown` ("check could not be completed") rather than `No`.
- Validation against the `EU Web Site URLs` seed sheet gives a **67.3%**
  liveness-agreement rate (101/150 comparable). The main disagreements are
  explainable: stale seed data (domains marked `In Production` that are now
  `NXDOMAIN`, e.g. the `makeanywhere.*` bundle), bot-blocking (`403`/`503`) on
  retired domains, and retired domains that now correctly redirect to corporate
  (`techdata.be`, `tdsynnex.ch`). See `output/validation_report.txt`.

## Testing

An offline test suite (no network) covers models, brand maps, ingestion counts,
content analysis, email/redirect/classification logic (every decision branch),
the FR-11 mail guard, allowed-value enforcement, summary reconciliation, and the
output contract:

```bash
py -m pytest -q
```

## Project layout

```text
src/
  models.py        # dataclasses (spec Section 3)
  brands.py        # brand / official-property / legacy maps
  ingest.py        # read + normalize + dedup the workbook
  dns_checks.py    # A/AAAA/CNAME/MX/TXT/DKIM resolution
  http_checks.py   # HTTPS/HTTP fetch, redirects, TLS
  content.py       # HTML content analysis
  email.py         # mail-dependency assessment
  redirect.py      # redirect target classification
  classify.py      # 12-field decision engine
  orchestrator.py  # concurrency + cache + resume
  output.py        # CSV + xlsx writers
  summary.py       # counts + pattern groupings
  run.py           # CLI entry point
  validate.py      # EU seed-data validation
```
