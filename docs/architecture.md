# System Architecture: Worldwide Domain Inventory Analysis Pipeline

This document describes the structure, architecture, and inputs/outputs of the
domain-classification pipeline. It is the practical companion to the formal
[`spec.md`](spec.md): where the spec defines *what* must be true, this document
explains *how* the code is organized and *how data flows* through it.

> Scope note: this document supersedes any older design notes. The
> `system-design.md` file in this folder is unrelated to this project and should
> be ignored.

---

## 1. What the system does

Given a source Excel workbook (`url-regional-class.xlsx`) listing ~945 corporate
domains across eight regional/subsidiary sheets, the pipeline:

1. **Ingests** every domain, normalizes it to its registrable form (eTLD+1), and
   de-duplicates across sheets.
2. **Collects evidence** for each domain over the network — DNS records,
   HTTP/redirect/TLS behavior, page content, and email configuration.
3. **Classifies** each domain deterministically into 12 output fields (does a
   website exist, does it redirect, content status, defensive-registration
   likelihood, release recommendation, etc.).
4. **Writes deliverables**: a master CSV and a formatted xlsx workbook
   (Inventory + Summary sheets).

The source workbook is treated as read-only and is never modified. The whole
thing is pure Python with a small set of well-known dependencies (no database,
no external services beyond DNS/HTTP).

---

## 2. High-level architecture

The system is a **linear evidence-gathering pipeline** with a concurrent
fan-out in the middle. The flow is:

```text
            ┌──────────┐
 xlsx ────▶ │  ingest  │ ── list[InputDomain] ──┐
            └──────────┘                         │
                                                 ▼
                                        ┌──────────────────┐
                                        │   orchestrator   │  (ThreadPool, cache)
                                        │  per domain:     │
                                        │                  │
                                        │  dns_checks ─┐   │
                                        │  http_checks │   │
                                        │       │      │   │
                                        │       ▼      │   │
                                        │   content    │   │
                                        │       │      │   │
                                        │   email ◀────┘   │
                                        │   redirect       │
                                        │       │          │
                                        │       ▼          │
                                        │   classify       │
                                        └────────┬─────────┘
                                                 │ list[ClassifiedDomain]
                                                 ▼
                                  ┌──────────┐        ┌──────────┐
                                  │ summary  │ ─────▶ │  output  │ ──▶ CSV + xlsx
                                  └──────────┘        └──────────┘
```

Two design principles drive the architecture:

- **Each concern is an isolated, pure-ish module** with a single documented entry
  point (the "module contract" in spec Section 4). Modules transform typed
  dataclasses, which makes each stage independently testable and offline-testable.
- **Failure is data, not an exception.** Network modules never raise for
  resolution/connection problems; they return a result object with a typed error
  reason. A failure for one domain never aborts the run — it yields `Unknown`
  fields with recorded evidence.

---

## 3. Project structure

```text
url-classification/
├── url-regional-class.xlsx   # INPUT: source workbook (read-only, never modified)
├── README.md                 # usage + headline results
├── requirements.txt          # pinned dependencies
├── docs/
│   ├── architecture.md       # this document
│   ├── spec.md               # formal specification (FRs, models, decision logic)
│   ├── specification.md      # original spec source
│   ├── research.md           # research phase notes
│   └── tasks.md              # atomic build steps
├── src/                      # the pipeline package
│   ├── __init__.py
│   ├── models.py             # dataclasses for every stage (the data contracts)
│   ├── brands.py             # curated brand / corporate / legacy / campaign maps
│   ├── ingest.py             # read + normalize + dedup the workbook
│   ├── dns_checks.py         # A/AAAA/CNAME/MX/TXT(SPF)/DMARC/DKIM resolution
│   ├── http_checks.py        # HTTPS/HTTP fetch, redirect chain, TLS handling
│   ├── content.py            # HTML analysis (render/parked/dates/branding)
│   ├── email.py              # mail-dependency assessment
│   ├── redirect.py           # redirect-target categorization
│   ├── classify.py           # the 12-field decision engine
│   ├── orchestrator.py       # concurrency + on-disk cache + resume
│   ├── summary.py            # counts + pattern groupings
│   ├── output.py             # CSV + xlsx writers
│   ├── run.py                # CLI entry point (ingest → run → summary → output)
│   └── validate.py           # FR-12 cross-check against EU seed data
├── tests/
│   └── test_pipeline.py      # offline test suite (no network)
├── cache/                    # GENERATED: per-domain JSON evidence cache
└── output/                   # GENERATED: domain_inventory.csv / .xlsx / report
```

### Module responsibilities at a glance

| Module | Entry point | Responsibility |
| --- | --- | --- |
| `models` | dataclasses | The typed data contracts passed between stages |
| `brands` | lookup helpers | Curated brand knowledge: corporate/subsidiary/legacy/campaign terms and domains |
| `ingest` | `load_domains(xlsx)` | Read sheets, normalize to eTLD+1, dedup, merge EU seeds |
| `dns_checks` | `resolve(domain)` | Resolve all DNS record types via public resolvers |
| `http_checks` | `fetch(domain)` | Try HTTPS/HTTP + `www.`, follow redirects, capture HTML/TLS |
| `content` | `analyze(http)` | Parse HTML for render/parking/dates/branding/mail-form |
| `email` | `assess(dns, content)` | Combine mail records + on-page forms into one signal |
| `redirect` | `classify_target(http, origin)` | Classify final redirect target into a category |
| `classify` | `classify(...)` | Apply decision logic → the 12 output fields |
| `orchestrator` | `run(domains, ...)` | Fan out per-domain work concurrently, cache, resume |
| `summary` | `summarize(rows)` | Compute metrics + pattern groupings |
| `output` | `write_csv` / `write_xlsx` | Render the deliverables |
| `run` | `main()` | Wire everything together as a CLI |
| `validate` | `validate()` | Sanity-check predictions against EU seed data |

---

## 4. The data model (the contracts between stages)

All inter-stage communication uses plain dataclasses defined in
[`models.py`](../src/models.py). Each stage consumes one or more of these and
produces the next. This is the backbone that keeps modules decoupled.

| Dataclass | Produced by | Key fields |
| --- | --- | --- |
| `InputDomain` | `ingest` | `domain` (eTLD+1, unique key), `original`, `region`, `source`, EU `seed_*` fields |
| `DnsResult` | `dns_checks` | `resolves`, `a/aaaa/cname/mx`, `spf`, `dmarc`, `dkim_selectors`, `error` |
| `HttpResult` | `http_checks` | `reachable`, `status_code`, `final_url`, `redirect_chain`, `tls_error`, `html` |
| `ContentResult` | `content` | `render_status`, `copyright_year`, `parked`, `placeholder`, `obsolete_branding`, `has_mail_form` |
| `EmailResult` | `email` | `has_mx/spf/dmarc/dkim`, `has_mail_form`, `email_functionality` |
| `ClassifiedDomain` | `classify` | the 12 spec output fields + provenance (`region/source/country`) + `error` |
| `Summary` | `summary` | counts (`keep/review/...`) + `patterns` dict |

`DnsResult`, `HttpResult`, `ContentResult`, and `EmailResult` provide
`to_dict()` / `from_dict()` so network evidence can be serialized to and from the
on-disk cache.

Allowed-value vocabularies (e.g. `CONTENT_STATUS_VALUES`,
`RECOMMENDATION_VALUES`) are declared as constants in `models.py` and enforced by
the classification engine, guaranteeing every output cell uses only its permitted
values.

---

## 5. Stage-by-stage walkthrough (the "ins and outs")

### 5.1 Ingest — `ingest.py`

- **In:** path to `url-regional-class.xlsx`.
- **Out:** `list[InputDomain]`, de-duplicated by registrable domain.
- **How:** Opens the workbook read-only with `openpyxl`. Reads the eight domain
  sheets (`North America`, `EMEA`, `LATAM`, `APJ`, `NA - Public Sector`, `Hyve`,
  `Shyft`, `Non-Classified`), dynamically locating each header row. Each raw value
  is normalized by `registrable_domain()` — lowercased, scheme/path/port/`www.`
  stripped, then reduced to eTLD+1 via `tldextract` (using a bundled
  public-suffix snapshot so it works offline, with private suffixes honored so
  e.g. `synnex.br.com` stays distinct).
- **Dedup:** First occurrence wins (sheet order), but empty fields are back-filled
  from later duplicates. The `EU Web Site URLs` sheet is read separately and its
  seed fields (status, purpose, CMS, hosting) are merged onto matching domains —
  these become the strongest evidence later.

`registrable_domain()` is the single normalization function and is reused by
`http_checks` and `redirect` to compare origin vs. final domains consistently.

### 5.2 DNS checks — `dns_checks.py`

- **In:** a domain string.
- **Out:** `DnsResult`.
- **How:** Uses `dnspython` against **public resolvers** (8.8.8.8 / 1.1.1.1 and
  backups) rather than the local stub resolver, which is far more reliable under
  concurrency. Resolves A, AAAA, CNAME, then MX, TXT (for SPF), `_dmarc` TXT, and
  probes a short list of common DKIM selectors. It short-circuits on `NXDOMAIN` /
  persistent timeout to avoid wasted queries, and treats MX-only domains as
  "resolving" for mail purposes. Every failure mode maps to a typed `error`
  string (`NXDOMAIN`, `NoAnswer`, `Timeout`, ...); the module never raises.

### 5.3 HTTP checks — `http_checks.py`

- **In:** a domain string.
- **Out:** `HttpResult` (including the raw HTML body).
- **How:** With `requests`, attempts in order: `https://domain`,
  `https://www.domain`, `http://domain`, `http://www.domain`, following redirects.
  On a TLS error it retries once with verification disabled so it can still read
  the body *and* record that a TLS error exists. It records the status code, the
  full redirect chain, the final URL, an off-domain flag (origin eTLD+1 vs. final
  eTLD+1), elapsed time, and the body (capped at ~2 MB). All network exceptions
  become typed `http_error` strings (`Timeout:...`, `ConnectionError:...`, etc.).

### 5.4 Content analysis — `content.py`

- **In:** an `HttpResult`.
- **Out:** `ContentResult`.
- **How:** Parses the HTML with BeautifulSoup (`lxml`, falling back to the
  built-in parser). Derives:
  - **render_status** (`Yes`/`Partial`/`No`/`Unknown`) from title + visible text
    length + error status.
  - **parked / placeholder** flags from curated signal phrase lists.
  - **last-update / copyright_year** from meta dates, `<time>` tags, copyright
    regex, then a fallback "most recent plausible year on the page".
  - **maintenance_signals** (news/blog/careers/products/...) as an activity proxy.
  - **obsolete_branding** via `brands.is_legacy_term`.
  - **has_mail_form** (email input, contact/subscribe form action, or `mailto:`).

  Note content is re-derived from cached HTML on cache hits, so improving the
  analysis logic does **not** require re-fetching the network.

### 5.5 Email assessment — `email.py`

- **In:** `DnsResult` + `ContentResult`.
- **Out:** `EmailResult` with `email_functionality` ∈ `Yes/No/Unknown`.
- **How:** `Yes` if MX exists, OR (SPF and DMARC), OR a mail form is present.
  `No` if the domain resolves (or is `NXDOMAIN`) with none of those. `Unknown`
  only when DNS genuinely failed (timeout). This feeds the safety guard below.

### 5.6 Redirect classification — `redirect.py`

- **In:** `HttpResult` + origin domain.
- **Out:** `(redirect, target)` where `redirect` ∈ `Yes/No/Unknown`.
- **How:** Compares the origin registrable domain to the final one and inspects
  the hop chain. Off-domain targets are categorized via `brands.categorize_domain`
  into: TD SYNNEX corporate, Subsidiary, Legacy brand, Campaign/landing,
  Partner/vendor, Third-party, or Error page. The final URL is always preserved
  in the target string for traceability.

### 5.7 Classification — `classify.py`

- **In:** `InputDomain`, `DnsResult`, `HttpResult`, `ContentResult`,
  `EmailResult`, the redirect tuple, plus a `bundle_member` flag.
- **Out:** a fully populated `ClassifiedDomain` (the deliverable row).
- **How:** This is the deterministic decision engine implementing spec Section 5.
  It derives each of the 12 fields in priority order — website presence, page
  render, email, last update, **content status** (Non-responsive → Broken →
  Parked → Placeholder → Legacy → Outdated → Maintained → Active → Unknown),
  **defensive-registration likelihood** (brand-term + activity heuristics), a
  human-readable **likely purpose**, and the final **release recommendation**
  (`Keep`/`Review`/`Candidate for release`/`Do not release`/`Unknown`).

  Two safety properties live here:
  - **FR-11 mail guard:** a row can never be `Candidate for release` if it has an
    active or unclear mail dependency — that is downgraded to `Do not release` /
    `Review` even if other logic suggested release.
  - **`evidence_notes` is always non-empty** — every row carries a concise,
    human-readable trail (DNS state, HTTP status, redirect target, copyright year,
    defensive reasoning, recommendation reasoning, and EU seed status).

### 5.8 Orchestration — `orchestrator.py`

- **In:** `list[InputDomain]` + run options (workers, cache dir, use_cache).
- **Out:** `list[ClassifiedDomain]` in input order.
- **How:** A `ThreadPoolExecutor` fans out `_process_one` per domain. Network
  I/O dominates, so threads (not processes) give good throughput. Per-domain
  evidence (DNS + HTTP/HTML) is cached as JSON keyed by a filesystem-safe domain
  name, making runs **resumable** and warm reruns network-free. Crucially,
  **transient failures are never cached** so a later run can recover them and
  distinguish `Unknown` from a definitive `No`. Any unexpected exception is caught
  and turned into an error row, so one bad domain can't abort the batch. It also
  pre-computes multi-TLD "bundle" membership to inform defensive scoring.

### 5.9 Summary — `summary.py`

- **In:** the classified rows.
- **Out:** a `Summary` (counts + pattern groupings).
- **How:** Tallies recommendation counts, email dependencies, and high-defensive
  counts, then builds pattern groups: multi-TLD bundles, campaign/landing
  domains, partner/vendor, legacy-brand, typo/abbreviation variants (via edit
  distance against brand terms), and regional clusters.

### 5.10 Output — `output.py`

- **In:** rows + `Summary`.
- **Out:** `output/domain_inventory.csv` and `output/domain_inventory.xlsx`.
- **How:** CSV uses UTF-8-BOM (Excel-friendly) with the 12 spec columns in exact
  order plus provenance. The xlsx has an **Inventory** sheet (styled header,
  frozen panes, autofilter, color-coded recommendation cells) and a **Summary**
  sheet (metrics table + pattern tables).

### 5.11 Validation — `validate.py`

- **In:** the source workbook (uses only EU-seeded rows).
- **Out:** an agreement-rate report (`output/validation_report.txt`).
- **How:** Runs the pipeline on the EU-seeded domains and compares the predicted
  liveness/redirect against the seed sheet's `Site Status` as an independent
  sanity check, printing the agreement rate and notable mismatches.

---

## 6. Inputs and outputs (summary)

### Inputs

| Input | Form | Notes |
| --- | --- | --- |
| `url-regional-class.xlsx` | Excel workbook | 8 domain sheets + `EU Web Site URLs` seed sheet. Read-only. |
| Network (DNS + HTTP) | Live calls | Required for a real run; cache enables offline reruns. |
| CLI flags | `src.run` args | `--source --out-dir --cache-dir --workers --limit --no-cache --verbose` |

### Outputs

| Output | Path | Contents |
| --- | --- | --- |
| Master CSV | `output/domain_inventory.csv` | One row per domain, 12 spec fields + provenance |
| Deliverable workbook | `output/domain_inventory.xlsx` | Inventory + Summary sheets |
| Validation report | `output/validation_report.txt` | EU seed agreement rate + mismatches |
| Evidence cache | `cache/<domain>.json` | Serialized DNS + HTTP evidence (resumable runs) |

### Running it

```bash
py -m pip install -r requirements.txt   # one-time setup
py -m src.run --limit 10                # smoke run on 10 domains
py -m src.run --workers 24              # full run
py -m src.validate                      # cross-check against EU seed data
py -m pytest -q                         # offline test suite
```

---

## 7. Cross-cutting design decisions

- **Errors as typed values.** DNS/HTTP modules return results with error reasons
  instead of raising. This lets the classifier distinguish "definitely no site"
  from "couldn't check" — central to the `No` vs. `Unknown` distinction.
- **Cache the expensive part, recompute the cheap part.** Only network evidence
  (DNS + raw HTML) is cached; content analysis and classification run fresh every
  time, so logic improvements take effect on warm reruns with zero new requests.
- **Determinism.** Classification is rule-based with a fixed priority order, so
  the same evidence always yields the same output — important for auditability and
  for the offline test suite that exercises every decision branch.
- **Safety first for release decisions.** The FR-11 mail guard and the
  "redirects to an official property → Do not release" rule bias the system
  toward *not* recommending release when there is any doubt.
- **Brand knowledge is centralized.** `brands.py` is the single source of truth
  for what counts as corporate/subsidiary/legacy/campaign, so redirect
  categorization, defensive scoring, and pattern grouping all stay consistent.
- **The source is sacred.** The workbook is only ever opened read-only; the
  spec's acceptance criteria require it to be byte-identical before and after a
  run.