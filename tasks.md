# Tasks: Worldwide Domain Inventory Analysis Pipeline

Ordered, atomic, independently verifiable build tasks implementing [spec.md](spec.md) (research
context in [research.md](research.md)). Each task lists Goal, Files, Dependencies, and an
Acceptance check. Tasks are sequenced so each can be completed and verified before the next.

Target layout:
```text
url-classification/
  requirements.txt
  README.md
  src/
    __init__.py
    models.py
    brands.py
    ingest.py
    dns_checks.py
    http_checks.py
    content.py
    email.py
    redirect.py
    classify.py
    orchestrator.py
    output.py
    summary.py
    run.py            # CLI entry point
  cache/              # gitignored on-disk cache
  output/             # generated CSV + xlsx
```

---

## T1 - Project scaffold and dependencies
- **Goal**: Create the package structure, `requirements.txt`, and a short `README.md` with run
  instructions.
- **Files**: `requirements.txt`, `README.md`, `src/__init__.py`, `.gitignore` (cache/, output/).
- **Dependencies**: none.
- **requirements.txt**: `dnspython`, `requests`, `beautifulsoup4`, `lxml`, `tldextract`,
  `openpyxl`, `pandas`.
- **Acceptance**: `py -m pip install -r requirements.txt` succeeds; `import src` works.

## T2 - Data models
- **Goal**: Implement the dataclasses from spec Section 3 (`InputDomain`, `DnsResult`,
  `HttpResult`, `ContentResult`, `EmailResult`, `ClassifiedDomain`, `Summary`).
- **Files**: `src/models.py`.
- **Dependencies**: T1.
- **Acceptance**: All dataclasses instantiate with defaults; field names/allowed-value docstrings
  match spec Section 3.

## T3 - Brand and official-property maps
- **Goal**: Curate keyword maps for brand terms (`tdsynnex`, `synnex`, `techdata`, `hyve`,
  `shyft`, `dlt`, `apptium`, `streamone`, etc.), official/subsidiary property domains, and legacy
  brand domains, used by redirect and defensive logic.
- **Files**: `src/brands.py`.
- **Dependencies**: T1.
- **Acceptance**: Lookup helpers return correct category for sample inputs (`tdsynnex.com` ->
  corporate, `techdata.com` -> legacy, `hyve*` -> subsidiary).

## T4 - Ingestion and normalization
- **Goal**: Read all eight domain-list sheets + `EU Web Site URLs` from
  [url-regional-class.xlsx](url-regional-class.xlsx); dynamically find header rows; normalize
  (lowercase, strip, drop scheme/`www.`/path, eTLD+1); de-duplicate across sheets; merge EU seed
  fields onto matching domains.
- **Files**: `src/ingest.py`.
- **Dependencies**: T2, T3.
- **Acceptance**: Returns exactly 945 unique `InputDomain` objects (reconciles with the workbook
  summary: 60+293+39+48+26+16+3+460); EU seed fields populated for matching domains; no source
  rows dropped silently (counts logged).

## T5 - DNS checks
- **Goal**: Implement `resolve(domain)` for A/AAAA/CNAME/MX/TXT(SPF)/_dmarc(DMARC)/DKIM
  selectors with timeouts and typed error reasons.
- **Files**: `src/dns_checks.py`.
- **Dependencies**: T2.
- **Acceptance**: On a known live domain returns A + MX; on a known non-existent domain returns
  `resolves=False` with `error="NXDOMAIN"`. No unhandled exceptions.

## T6 - HTTP / redirect / TLS checks
- **Goal**: Implement `fetch(domain)`: try HTTPS then HTTP (+`www.`), follow redirects, capture
  status, final URL, redirect chain, off-domain flag, TLS errors, elapsed time, and HTML body.
- **Files**: `src/http_checks.py`.
- **Dependencies**: T2.
- **Acceptance**: A redirecting domain yields a populated `redirect_chain` and correct
  `final_url`; a TLS-broken host yields `tls_error`; a refused host yields `reachable=False`
  without raising.

## T7 - Content analysis
- **Goal**: Implement `analyze(http_result)`: render status, last-update/copyright extraction,
  maintenance signals, parked/placeholder detection, obsolete-branding detection, mail-form
  detection, title.
- **Files**: `src/content.py`.
- **Dependencies**: T2, T6.
- **Acceptance**: Given saved sample HTML (active site, parked page, legacy page), returns the
  expected `render_status`, `parked`/`placeholder` flags, and a `copyright_year` when present.

## T8 - Email dependency assessment
- **Goal**: Implement `assess(dns_result, content_result)` -> `EmailResult` and the
  `email_functionality` value per spec 5.4.
- **Files**: `src/email.py`.
- **Dependencies**: T2, T5, T7.
- **Acceptance**: MX present -> `Yes`; resolves but no mail records/forms -> `No`; DNS failure ->
  `Unknown`.

## T9 - Redirect target classification
- **Goal**: Implement `classify_target(http_result)` returning (redirect Yes/No/Unknown, target
  URL or spec category) using `brands`.
- **Files**: `src/redirect.py`.
- **Dependencies**: T3, T6.
- **Acceptance**: Redirect to `tdsynnex.com` -> "TD SYNNEX corporate site"; off to unrelated
  domain -> "Third-party unrelated site"; no redirect -> ("No", origin URL).

## T10 - Classification and recommendation engine
- **Goal**: Implement `classify(...)` producing all 12 `ClassifiedDomain` fields via the decision
  logic in spec Section 5, including the FR-11 mail-dependency guard and non-empty evidence.
- **Files**: `src/classify.py`.
- **Dependencies**: T2, T3, T7, T8, T9.
- **Acceptance**: Unit cases cover each branch: active site -> Keep; brand+inactive -> High
  defensive + Do not release; unreachable non-brand -> Candidate for release; mail present blocks
  release; transient failure -> Unknown. Every field uses only allowed values.

## T11 - Orchestrator (concurrency, cache, resume)
- **Goal**: Implement `run(domains, workers, cache_dir)`: thread-pooled execution of DNS+HTTP+
  content+email+redirect+classify per domain, on-disk JSON cache keyed by domain, resumable, with
  per-domain error capture that never aborts the run.
- **Files**: `src/orchestrator.py`.
- **Dependencies**: T4-T10.
- **Acceptance**: Running twice uses cache on the second pass (near-zero network calls); a forced
  failure on one domain still yields a row with `Unknown` fields and a recorded error; progress is
  logged.

## T12 - Output writer (CSV + xlsx)
- **Goal**: Implement `write_csv` and `write_xlsx` per spec Section 6 (Inventory sheet with frozen
  header + autofilter; column order exactly as specified; provenance columns appended). Source
  workbook is never opened for writing.
- **Files**: `src/output.py`.
- **Dependencies**: T2.
- **Acceptance**: `output/domain_inventory.csv` and `.xlsx` are produced with correct headers and
  945 data rows; source xlsx unchanged (hash compared).

## T13 - Summary and pattern analysis
- **Goal**: Implement `summarize(rows)` -> `Summary`: the six required metrics plus pattern
  groupings (multi-TLD bundles, campaign domains, partner/vendor, legacy brand, typo variants,
  regional clusters); write the Summary sheet.
- **Files**: `src/summary.py` (+ wire into `src/output.py`).
- **Dependencies**: T10, T12.
- **Acceptance**: Summary counts reconcile with inventory rows; at least the multi-TLD-bundle and
  regional-cluster groups are populated from real data.

## T14 - CLI entry point
- **Goal**: Implement `run.py` argument parsing (`--source`, `--out-dir`, `--workers`,
  `--limit` for smoke runs, `--no-cache`) tying ingest -> orchestrate -> output -> summary.
- **Files**: `src/run.py`.
- **Dependencies**: T4, T11, T12, T13.
- **Acceptance**: `py -m src.run --limit 10` completes end-to-end on 10 domains and writes both
  output files.

## T15 - Validation against EU seed data
- **Goal**: Compare pipeline output for `EU Web Site URLs` domains against the sheet's
  `Site Status`/`Business Purpose`; report agreement rate and notable mismatches.
- **Files**: `src/validate.py` (or a notebook/section in `README.md`).
- **Dependencies**: T4, T10, T14.
- **Acceptance**: A validation report is produced; mismatches are explainable (e.g. transient
  network) and content-status agreement is reasonable on the seed set.

## T16 - Full run and deliverable
- **Goal**: Execute the full 945-domain run, review the summary, and finalize
  `output/domain_inventory.xlsx` plus the short written summary required by the spec.
- **Files**: `output/domain_inventory.csv`, `output/domain_inventory.xlsx`, summary section in
  `README.md`.
- **Dependencies**: T1-T15.
- **Acceptance**: All 945 domains classified with non-empty evidence; deliverable matches spec
  Section 6/7; ready before the Jun 19 deadline.

---

## Suggested execution order
T1 -> T2 -> T3 -> T4 -> (T5, T6 in parallel) -> T7 -> T8 -> T9 -> T10 -> T11 -> T12 -> T13 ->
T14 -> T15 -> T16.
