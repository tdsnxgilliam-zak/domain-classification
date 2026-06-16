# Research: Worldwide Domain Inventory Analysis

This document captures the research phase of the spec-driven workflow defined against
[specification.md](specification.md). It audits the source data, researches the technical
checks required, selects tooling, and records risks and constraints. It is the input to
[spec.md](spec.md) and [tasks.md](tasks.md).

## 1. Source-Data Audit

Source workbook: [url-regional-class.xlsx](url-regional-class.xlsx) (14 sheets, 3 pivot tables).

### 1.1 Sheets and roles

| Sheet | Role | Rows / Domains |
| --- | --- | --- |
| Regional Summary | Pivot: domain count by country | 67 country rows |
| North America | Domain list | 60 |
| EMEA | Domain list | 293 |
| LATAM | Domain list | 39 |
| APJ | Domain list | 48 |
| NA - Public Sector | Domain list (DLT) | 26 |
| Hyve | Domain list (subsidiary) | 16 |
| Shyft | Domain list (subsidiary) | 3 |
| Non-Classified | Domain list (pending marketing review) | 460 |
| EU Web Site URLs | Enriched URL list (partial ground truth) | 358 |
| Pivots and Counts | Pivot/count helpers | n/a |
| Sheet1 / Sheet2 / Sheet3 | Pivot/staging helpers | n/a |

Total inventory: **945 domains** (per the workbook's own `URL Regional Classification Summary`:
North America 60, EMEA 293, LATAM 39, APJ 48 = 440 regional; NA-Public Sector 26, Hyve 16,
Shyft 3 = 45 subsidiary; Non-Classified 460). Of these, 779 are TD SYNNEX hosted and 166 use an
external provider (all in EMEA).

### 1.2 Domain-list schema (regional/subsidiary sheets)

All eight domain-list sheets share the same 7-column layout (header on row 3 for the
formatted sheets, row 1 for the raw `Sheet3`):

| Column | Field | Example |
| --- | --- | --- |
| A | Domain | `activate-here.ca` |
| B | TLD | `.ca` |
| C | Country | `Canada` |
| D | Source | `TD SYNNEX`, `AVT (Avnet)` |
| E | Domain Hosting | `TD SYNNEX` |
| F | Region | `North America`, `EMEA`, `Hyve`, ... |
| G | Classification Method | `Country designation (from registrar data)`, `Speculated (...)`, `Generic TLD, no regional signal` |

Note: formatted sheets put a title in row 1 (e.g. `North America Domains (60 total)`), leave
row 2 blank, the header in row 3, and data from row 4. Ingestion must locate the header row
rather than assuming row 1.

### 1.3 EU Web Site URLs sheet (seed / ground truth)

This sheet is the most valuable existing signal and should be used to seed and validate the
heuristics. Header on row 4, data from row 5. 9 columns:

| Column | Field | Notes |
| --- | --- | --- |
| A | URL | e.g. `www.tdevents.it`, may include a path (`www.tdblog.it/tdservices`) |
| B | Base Domain | `tdevents.it` |
| C | Root Domain | `tdevents.it` |
| D | Regional Classification | `EMEA` |
| E | EU Sub-Region | `IT` |
| F | Site Status | observed values include `Retired` (others present across rows) |
| G | Business Purpose | free text (e.g. "Website blog that promote our events...") |
| H | CMS | e.g. `Wordpress-6.1`, `Unity 3D-1.0`, `Drupal`, `Typo3`, `Umbraco`, `Laravel`, `ProcessWire`, `DatoCMS`, `Custom`, `Unknown` |
| I | Hosting Provider | e.g. `Aruba`, `Hetzner` |

CMS distribution (from the `Pivots and Counts` sheet): WordPress 97, Unknown 46, Umbraco 22,
Custom 18, Drupal 16, Laravel 8, ProcessWire 4, DatoCMS 2, Typo3 2.

This sheet already answers several spec output fields (content/site status, likely purpose,
and indirectly "website behind URL") for ~358 URLs and can be used to spot-check the pipeline.

## 2. Check Methodology Research

Mapping each `specification.md` "Required Check" (lines 37-89) to a concrete, automatable
technique.

### 2.1 Technical status (spec lines 41-49)

- **DNS resolution**: query `A` and `AAAA`. If absent, query `CNAME`. No records / NXDOMAIN =>
  domain does not resolve.
- **HTTP/HTTPS reachability**: attempt `https://<domain>` then `http://<domain>` (and `www.`
  variant) with a browser-like `User-Agent`, short connect/read timeouts, and `allow_redirects`.
- **Website behind URL**: a `2xx`/`3xx` response with a non-trivial HTML body indicates a site;
  connection refused / timeout / `4xx`-`5xx` with no body indicates none.
- **Redirects**: follow the redirect chain, record each hop and the final URL; compare final
  registrable domain to the original to decide if it redirects off-domain.
- **Render success**: heuristic only (no headless browser in the pure-Python scope) - based on
  status code, content length, presence of `<title>`/`<body>` text, and absence of JS-only
  shells. Classify as `Yes` / `Partial` / `No`.
- **Error taxonomy**: DNS failure, connection timeout, connection refused, TLS certificate
  failure (captured separately by attempting a verified request, then noting `SSLError`), HTTP
  error status, blank page, parked/placeholder page.

### 2.2 Content status (spec lines 51-56)

- Parse HTML with BeautifulSoup.
- **Last-update signals**: `Last-Modified` HTTP header; `<meta>` article/modified dates;
  visible copyright year (regex `(c)|copyright ... 20\d\d`); sitemap `lastmod` where cheaply
  available.
- **Maintenance signals**: recent year vs current year, presence of news/blog/events sections,
  active forms, product/support copy.
- **Parked/placeholder detection**: known parking strings ("domain is for sale", "parked",
  registrar landing pages), very small body, single-image pages, default server pages.
- **Obsolete-branding signals**: references to legacy names (`Tech Data`, `SYNNEX` standalone,
  `Avnet`, acquired-brand terms) and discontinued campaigns.
- Map to allowed `Content status` values: Active / Maintained / Outdated / Legacy / Parked /
  Placeholder / Broken / Non-responsive / Unknown.

### 2.3 Redirect behavior (spec lines 58-70)

- Record final URL and classify the target into the spec categories: TD SYNNEX corporate site,
  Subsidiary site, Legacy brand site, Campaign/landing page, Partner/vendor site, Third-party
  unrelated site, Error page, Unknown.
- Classification uses a curated keyword/domain map (e.g. `tdsynnex.com`, subsidiary domains,
  legacy `techdata.com`/`synnex.com`) matched against the final registrable domain.

### 2.4 Email and mail dependency (spec lines 72-76)

- Query `MX` records (primary signal).
- Query `TXT` for `SPF` (`v=spf1`), `_dmarc.<domain>` `TXT` for `DMARC` (`v=DMARC1`).
- Probe a small set of common DKIM selectors (`default`, `google`, `selector1`, `selector2`,
  `k1`, `dkim`) at `<selector>._domainkey.<domain>`.
- Detect on-page contact/newsletter/login forms (input `type=email`, `<form>` with
  mail-related action) as secondary signals.
- **Safety rule (spec line 76)**: any active or unclear mail dependency blocks a "Candidate for
  release" recommendation; force `Do not release` or `Review`.

### 2.5 Defensive registration / brand protection (spec lines 78-89)

- Brand-term match on the domain label: `tdsynnex`, `td-synnex`, `synnex`, `techdata`,
  `tech-data`, subsidiary terms (`hyve`, `shyft`, `dlt`, `apptium`, `streamone`), and known
  campaign/product terms.
- **Multi-TLD bundle** detection: same second-level label across multiple TLDs (e.g.
  `activate-here.ca` + `activate-here.us`).
- **Typo/abbreviation variants**: edit-distance to brand terms.
- **Regional variants**: same label under ccTLDs.
- A domain that is inactive but matches brand terms, or that redirects to an official property,
  scores higher defensive likelihood (High / Medium / Low / Unknown).

## 3. Candidate Tooling

Pure-Python pipeline (Python 3.13 is already installed; `py` launcher). No LLM layer.

| Concern | Library | Reason |
| --- | --- | --- |
| Read source xlsx / write deliverable xlsx | `openpyxl` | Pure Python, no native deps; already the xlsx format in use |
| Tabular handling / CSV | `pandas` (optional) or stdlib `csv` | `csv` keeps deps minimal; `pandas` convenient for joins/summary |
| DNS queries | `dnspython` | A/AAAA/CNAME/MX/TXT/DKIM selector lookups |
| HTTP(S) requests + redirects + TLS errors | `requests` | Mature, exposes `SSLError`, redirect history |
| HTML parsing | `beautifulsoup4` (+ `lxml` or stdlib parser) | Extract title, meta, copyright, forms |
| Registrable-domain / TLD parsing | `tldextract` | Correct eTLD+1 handling for redirect comparison and bundle detection |
| Concurrency | stdlib `concurrent.futures` | Thread pool for I/O-bound network checks |

All are available on PyPI and install via `pip install -r requirements.txt`. Network access is
required at run time for DNS and HTTP checks.

## 4. Risks and Constraints

- **Runtime / throughput**: 945 domains x (DNS + HTTP + HTTPS + redirects) is the main cost.
  Needs a bounded thread pool, per-request timeouts, retries, and on-disk caching so reruns are
  cheap and resumable before the Jun 19 deadline.
- **Network reliability**: transient timeouts must not be recorded as permanent "no website".
  Distinguish `Unknown` (check failed) from `No` (definitively unreachable) per the spec's
  liberal use of `Unknown`.
- **Render fidelity**: no headless browser in scope, so JS-only single-page apps may look like
  blank/partial pages. Flag these as `Partial`/`Unknown` rather than `No`.
- **Heuristic accuracy**: content status, likely purpose, and defensive likelihood are
  judgment calls. Mitigate by validating against the `EU Web Site URLs` ground-truth sheet and
  by always emitting human-readable evidence (spec line 162).
- **Mail-dependency safety**: do not recommend release when MX/SPF/DKIM/DMARC or mail forms are
  present or unclear (spec line 76).
- **Rate limiting / politeness**: cap concurrency and add jitter to avoid being blocked; respect
  that some domains are third-party/partner-owned.
- **Data hygiene**: source sheets contain titles, blank rows, whitespace-padded values
  (observed trailing spaces in CMS column) and duplicates across sheets; normalization and
  dedup are required before checks.

## 5. Open Questions Resolved

- Execution approach: pure Python heuristic pipeline (confirmed; no LLM).
- Output destination: new deliverable workbook/CSV; source xlsx left untouched (confirmed).
