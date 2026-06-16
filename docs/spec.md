# Specification: Worldwide Domain Inventory Analysis Pipeline

Refined, implementable specification derived from [specification.md](specification.md) and
[research.md](research.md). Defines functional requirements, data models, module contracts,
classification decision logic, and the output contract for a pure-Python heuristic pipeline
that classifies all 945 domains in [url-regional-class.xlsx](url-regional-class.xlsx) and writes
a new deliverable. The atomic build steps are in [tasks.md](tasks.md).

## 1. Goal

For every domain in the source workbook, collect technical, content, redirect, and email
evidence and assign the 12 required output fields plus a workbook-level summary, without
modifying the source file.

## 2. Functional Requirements

Each requirement is testable.

- **FR-1 Ingest**: Read all eight domain-list sheets and the `EU Web Site URLs` sheet,
  locating the header row dynamically. Produce a normalized, de-duplicated domain set.
- **FR-2 Normalize**: Lowercase, strip whitespace/`www.`, drop scheme/path, derive registrable
  domain (eTLD+1). Preserve original source metadata (TLD, Country, Source, Hosting, Region,
  Classification Method) and EU seed fields where present.
- **FR-3 DNS**: For each domain resolve `A`, `AAAA`, `CNAME`, `MX`, `TXT` (SPF), `_dmarc` TXT
  (DMARC), and a set of common DKIM selectors. Record results or a typed failure reason.
- **FR-4 HTTP**: Attempt HTTPS then HTTP (and `www.` fallback), follow redirects, record status
  code(s), final URL, redirect chain, TLS errors, response time, and the HTML body.
- **FR-5 Content**: From the fetched HTML derive render status, last-update signals, maintenance
  signals, parked/placeholder detection, and obsolete-branding signals.
- **FR-6 Email**: Combine DNS mail records and on-page mail forms into an email-dependency
  signal.
- **FR-7 Redirect classification**: Classify the final redirect target into the spec categories.
- **FR-8 Classify**: Apply decision logic (Section 5) to produce the 12 output fields with only
  allowed values, including human-readable evidence.
- **FR-9 Output**: Write a master CSV and a formatted xlsx (inventory sheet + summary sheet).
  Source workbook is never modified.
- **FR-10 Resilience**: Bounded concurrency, per-domain timeouts/retries, on-disk caching, and
  resumable runs. A failure for one domain never aborts the run; it yields `Unknown` fields with
  a recorded error.
- **FR-11 Safety**: Never emit `Candidate for release` when an active or unclear mail dependency
  exists (spec line 76).
- **FR-12 Validate**: Cross-check pipeline output for the `EU Web Site URLs` rows against that
  sheet's `Site Status`/`Business Purpose` as a sanity check.

## 3. Data Models

Plain dataclasses; all fields optional unless noted. Types are indicative.

### 3.1 InputDomain
```text
domain: str            # normalized registrable domain (required, unique key)
original: str          # original cell value as listed
tld: str
country: str
source: str            # e.g. "TD SYNNEX", "AVT (Avnet)"
hosting: str           # "Domain Hosting" column
region: str            # North America | EMEA | LATAM | APJ | NA - Public Sector | Hyve | Shyft | Non-Classified
classification_method: str
seed_url: str | None         # from EU Web Site URLs (col A)
seed_site_status: str | None # EU col F
seed_purpose: str | None     # EU col G
seed_cms: str | None         # EU col H
seed_hosting_provider: str | None # EU col I
```

### 3.2 DnsResult
```text
resolves: bool
a: list[str]
aaaa: list[str]
cname: list[str]
mx: list[str]
spf: str | None        # raw SPF TXT if present
dmarc: str | None      # raw _dmarc TXT if present
dkim_selectors: list[str]  # selectors that returned a record
error: str | None      # NXDOMAIN | NoAnswer | Timeout | ...
```

### 3.3 HttpResult
```text
reachable: bool
scheme_used: str | None    # https | http
final_url: str | None
status_code: int | None
redirect_chain: list[str]  # ordered URLs
redirected_offdomain: bool
tls_error: str | None
http_error: str | None
elapsed_ms: int | None
html: str | None           # raw body (cached, not emitted)
```

### 3.4 ContentResult
```text
render_status: str          # Yes | Partial | No | Unknown
last_update: str | None     # date | year | None
copyright_year: int | None
maintenance_signals: list[str]
parked: bool
placeholder: bool
obsolete_branding: list[str]
has_mail_form: bool
title: str | None
```

### 3.5 EmailResult
```text
has_mx: bool
has_spf: bool
has_dmarc: bool
has_dkim: bool
has_mail_form: bool
email_functionality: str    # Yes | No | Unknown
```

### 3.6 ClassifiedDomain (the deliverable row)
The 12 spec output fields plus the join key. Allowed values exactly match
[specification.md](specification.md) lines 95-108.
```text
domain: str
website_behind_url: str        # Yes | No | Unknown
redirect: str                  # Yes | No | Unknown
redirect_target: str           # URL | <category> | Unknown
page_opens_renders: str        # Yes | No | Partial | Unknown
email_functionality: str       # Yes | No | Unknown
date_last_update: str          # Date | Year | Not found
content_status: str            # Active|Maintained|Outdated|Legacy|Parked|Placeholder|Broken|Non-responsive|Unknown
likely_purpose: str            # short text
defensive_likelihood: str      # High | Medium | Low | Unknown
release_recommendation: str    # Keep | Review | Candidate for release | Do not release | Unknown
evidence_notes: str            # short text
```

## 4. Module Contracts

One module per concern under a `src/` package. Signatures are the contract; implementations live
in [tasks.md](tasks.md).

| Module | Entry point | Input -> Output |
| --- | --- | --- |
| `ingest` | `load_domains(xlsx_path) -> list[InputDomain]` | source xlsx -> normalized, de-duped domains with seed data |
| `dns_checks` | `resolve(domain) -> DnsResult` | domain -> DNS records |
| `http_checks` | `fetch(domain) -> HttpResult` | domain -> HTTP/redirect/TLS result + HTML |
| `content` | `analyze(http_result) -> ContentResult` | HttpResult -> content signals |
| `email` | `assess(dns_result, content_result) -> EmailResult` | DNS + content -> email signal |
| `redirect` | `classify_target(http_result) -> (str, str)` | HttpResult -> (redirect Yes/No/Unknown, target/category) |
| `classify` | `classify(input, dns, http, content, email, redirect) -> ClassifiedDomain` | all evidence -> 12 fields |
| `orchestrator` | `run(domains, *, workers, cache_dir) -> list[ClassifiedDomain]` | domains -> classified rows (concurrent, cached, resumable) |
| `output` | `write_csv(rows, path)`, `write_xlsx(rows, summary, path)` | rows -> CSV + xlsx |
| `summary` | `summarize(rows) -> Summary` | rows -> counts + pattern groupings |

Cross-cutting: a `models` module holds the dataclasses; a `brands` module holds the curated
brand-term / official-property / subsidiary maps used by `redirect` and `classify`.

## 5. Classification Decision Logic

Deterministic rules. Evidence string is always populated.

### 5.1 Website behind URL
- `Yes` if any scheme returned `2xx`/`3xx` with non-trivial HTML.
- `No` if DNS resolves but all schemes give connection refused / `4xx`-`5xx` with no usable body,
  or DNS does not resolve (no site possible).
- `Unknown` if all attempts failed due to timeout/transient error.

### 5.2 Redirect / Redirect target
- `redirect = Yes` if final registrable domain differs from origin, or path changed via 3xx.
- `redirect = No` if no redirect hops.
- `redirect = Unknown` if unreachable.
- Target category via `brands` map applied to final eTLD+1: TD SYNNEX corporate site |
  Subsidiary site | Legacy brand site | Campaign or landing page | Partner or vendor site |
  Third-party unrelated site | Error page | Unknown. Store the final URL too.

### 5.3 Page opens / renders
- `Yes`: `2xx`, has `<title>`/visible body text, not parked/placeholder.
- `Partial`: reachable but thin body, JS-only shell, or mixed/secondary errors.
- `No`: error status / blank / connection failure with DNS present.
- `Unknown`: check failed transiently.

### 5.4 Email functionality
- `Yes` if `has_mx` OR (`has_spf` and `has_dmarc`) OR a mail form is present.
- `No` if domain resolves and none of the above.
- `Unknown` if DNS checks failed.

### 5.5 Date of last update
- Most specific available: explicit modified date > `Last-Modified` header > visible copyright
  year; else `Not found`.

### 5.6 Content status
Priority order:
1. `Non-responsive` - DNS resolves but no HTTP response at all.
2. `Broken` - reachable but error status / TLS failure / blank render.
3. `Parked` - parking signals matched.
4. `Placeholder` - tiny/default/single-image page, no real content.
5. `Legacy` - obsolete branding (Tech Data / standalone SYNNEX / Avnet / acquired brand) dominant.
6. `Outdated` - copyright/last-update year older than (current year - 2), no fresh maintenance
   signals.
7. `Maintained` - recent year present but limited fresh activity.
8. `Active` - recent year AND maintenance signals (news/blog/events/forms/products).
9. `Unknown` - insufficient evidence.

### 5.7 Likely purpose
Short text combining `Region`/`Source`/subsidiary, brand match, redirect target, and content
signals (e.g. "Regional EMEA marketing microsite (WordPress, retired)", "Defensive ccTLD variant
of activate-here", "Subsidiary (Hyve) brand domain redirecting to corporate site").

### 5.8 Defensive-registration likelihood
- `High`: brand-term match AND (inactive/no website OR redirects to official property) OR part of
  a multi-TLD bundle of a brand label.
- `Medium`: brand-term/typo/regional variant match with some activity, or ambiguous bundle.
- `Low`: active business-purpose site with no defensive characteristics.
- `Unknown`: insufficient evidence.

### 5.9 Release recommendation (spec lines 110-132)
Apply in order:
1. `Do not release` if: email dependency `Yes`, OR redirects to an official/subsidiary property,
   OR `defensive_likelihood = High` and protective, OR security-sensitive.
2. `Review` if: unclear ownership/purpose, partial functionality, email `Unknown`, ambiguous
   redirect, or insufficient evidence.
3. `Candidate for release` if: no website, not brand-protective (`defensive_likelihood` Low),
   no email dependency, no visible business purpose. (Hard-blocked by the FR-11 mail guard.)
4. `Keep` if: active/business-relevant/customer-facing/regional/subsidiary or protective of a
   current brand, and not already `Do not release`.
5. `Unknown` if checks could not be completed.

## 6. Output Contract

### 6.1 Master CSV (`output/domain_inventory.csv`)
One row per domain. Columns in this exact order:
`Domain, Website behind URL?, Redirect?, Redirect target, Page opens / renders?,
Email functionality?, Date of last update found, Content status, Likely purpose,
Defensive-registration likelihood, Release recommendation, Evidence / notes`.
Plus appended provenance columns: `Region, Source, Country` (for traceability; after the 12
spec fields).

### 6.2 Deliverable workbook (`output/domain_inventory.xlsx`)
- **Inventory** sheet: the 12 spec fields (+ provenance), frozen header, autofilter.
- **Summary** sheet (spec lines 168-176):
  - Total domains reviewed.
  - Count recommended Keep.
  - Count Review.
  - Count Candidate for release.
  - Count with possible email dependencies.
  - Count likely defensive / fraud-prevention.
  - Patterns: multi-TLD bundles, campaign domains, partner/vendor domains, legacy brand domains,
    typo variants, regional clusters (each as a small grouped table or count).

### 6.3 Summary model
```text
total: int
keep: int
review: int
candidate_release: int
do_not_release: int
unknown: int
email_dependency: int
defensive_high: int
patterns: dict[str, list[str]]   # pattern name -> example domains
```

## 7. Acceptance Criteria

- All 945 domains appear exactly once in the output (dedup verified).
- Every output field uses only its allowed values; `evidence_notes` is non-empty.
- No `Candidate for release` row has email dependency `Yes`/`Unknown`.
- Source [url-regional-class.xlsx](url-regional-class.xlsx) is byte-identical before/after.
- Summary counts reconcile with the inventory rows.
- Re-running with a warm cache does not repeat network calls.
