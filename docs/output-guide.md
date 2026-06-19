# Output Guide: Reading `domain_inventory.xlsx` and the Decision Logic

This guide explains how to read the deliverable workbook
(`output/domain_inventory.xlsx`) and the master CSV
(`output/domain_inventory.csv`), and documents the exact logic behind every
derived decision field. It is written for the analyst who opens the workbook and
needs to understand and trust each cell.

- For *how the system is built*, see [`architecture.md`](architecture.md).
- For the *formal rules*, see [`spec.md`](spec.md) Section 5.
- The source of truth for the logic described here is
  [`classify.py`](../src/classify.py); column rendering is in
  [`output.py`](../src/output.py); summary metrics are in
  [`summary.py`](../src/summary.py).

---

## 1. The two output files

| File | What it is | When to use it |
| --- | --- | --- |
| `output/domain_inventory.xlsx` | Formatted workbook: **Inventory** + **Summary** sheets | Human review, filtering, reporting |
| `output/domain_inventory.csv` | Same 15 columns, UTF‑8‑BOM, one row per domain | Re-importing, scripting, diffing |

Both contain the **same 12 spec fields plus 3 provenance fields**, in the same
order. The xlsx adds formatting (frozen header, autofilter, color-coded
recommendation cells) and a second Summary sheet.

---

## 2. The Inventory sheet — column by column

The Inventory sheet has one row per domain. Columns 1–12 are the spec fields;
columns 13–15 are provenance carried over from the source workbook for
traceability.

| # | Column header | Allowed values | Meaning |
| --- | --- | --- | --- |
| 1 | **Domain** | registrable domain | The normalized eTLD+1 (unique key for the row) |
| 2 | **Website behind URL?** | `Yes` / `No` / `Unknown` | Does a usable site respond? |
| 3 | **Redirect?** | `Yes` / `No` / `Unknown` | Does the URL redirect elsewhere? |
| 4 | **Redirect target** | URL / category / `Unknown` | Where it redirects and what kind of destination |
| 5 | **Page opens / renders?** | `Yes` / `Partial` / `No` / `Unknown` | Did the page actually render real content? |
| 6 | **Email functionality?** | `Yes` / `No` / `Unknown` | Is the domain configured for/used by email? |
| 7 | **Date of last update found** | date / year / `Not found` | Best available freshness signal |
| 8 | **Content status** | see §3.6 | One-word health/lifecycle classification |
| 9 | **Likely purpose** | short text | Human-readable guess at why the domain exists |
| 10 | **Defensive-registration likelihood** | `High` / `Medium` / `Low` / `Unknown` | Is this a brand-protective registration? |
| 11 | **Release recommendation** | `Keep` / `Review` / `Candidate for release` / `Do not release` / `Unknown` | The actionable verdict |
| 12 | **Evidence / notes** | short text | The audit trail behind the row (always populated) |
| 13 | **Region** | source value | NA / EMEA / LATAM / APJ / Hyve / Shyft / … |
| 14 | **Source** | source value | e.g. "TD SYNNEX", "AVT (Avnet)" |
| 15 | **Country** | source value | Country from the source sheet |

### Formatting cues in the xlsx

- **Row 1 is frozen** and has an autofilter — use the dropdowns to slice by
  recommendation, region, content status, etc.
- The **Release recommendation** cell (column 11) is **color-coded**:

| Recommendation | Cell color |
| --- | --- |
| Keep | green |
| Review | yellow |
| Candidate for release | light orange |
| Do not release | orange/red |
| Unknown | grey |

- **Evidence / notes** is the widest column and is the first place to look when a
  verdict surprises you — it spells out the reasoning.

---

## 3. Decision-field logic (the "why" behind each cell)

Every derived field is **deterministic**: identical evidence always yields the
identical output. The rules below are exactly what `classify.py` implements.

### 3.1 Website behind URL? (column 2)

| Value | When |
| --- | --- |
| `Yes` | HTTP reachable with status `2xx`/`3xx` **and** a non-trivial body (or the page rendered) |
| `No` | Reachable but `4xx`/`5xx` with no usable body; or reachable `2xx`/`3xx` with an empty body; or not reachable and the failure is **not** transient (e.g. connection refused, NXDOMAIN) |
| `Unknown` | Not reachable due to a **transient** failure (timeout) — we genuinely couldn't tell |

The key distinction is **`No` (definitive) vs. `Unknown` (couldn't check)**. A
timeout is `Unknown`; a refused connection or non-existent domain is `No`.

### 3.2 Redirect? + Redirect target (columns 3–4)

Computed in [`redirect.py`](../src/redirect.py) from the redirect chain and the
origin-vs-final registrable domain.

| Redirect? | When |
| --- | --- |
| `Yes` | Final registrable domain differs from the origin, or there was more than one hop |
| `No` | No redirect hops and same domain |
| `Unknown` | Unreachable |

**Redirect target** is the final URL when staying on-domain. For off-domain
redirects it is a **category label plus the final URL** in parentheses. Categories
(from [`brands.py`](../src/brands.py)):

| Category | Meaning |
| --- | --- |
| `TD SYNNEX corporate site` | Lands on an official corporate property |
| `Subsidiary site` | Active subsidiary brand (Hyve, StreamOne, DLT, …) |
| `Legacy brand site` | Pre-merger brand (Tech Data, SYNNEX, Avnet, …) |
| `Campaign or landing page` | Known marketing/campaign microsite |
| `Partner or vendor site` | Partner/vendor destination |
| `Third-party unrelated site` | Unrelated external domain |
| `Error page` | Final status was an error (`4xx`/`5xx`) |

A redirect to a **corporate or subsidiary** property is significant: it later
forces `Do not release` (see §3.9).

### 3.3 Page opens / renders? (column 5)

Mirrors `render_status` from [`content.py`](../src/content.py).

| Value | When |
| --- | --- |
| `Yes` | `2xx`, has a `<title>` and ≥200 chars of visible text, not parked/placeholder |
| `Partial` | Reachable but thin/JS-only shell, or a parked/placeholder page |
| `No` | Error status, blank body, or connection failure with DNS present |
| `Unknown` | Transient check failure |

### 3.4 Email functionality? (column 6)

From [`email.py`](../src/email.py). This drives the strongest safety guard.

| Value | When |
| --- | --- |
| `Yes` | Has MX **or** (SPF **and** DMARC) **or** an on-page mail form |
| `No` | Domain resolves (or is NXDOMAIN) with none of the above |
| `Unknown` | DNS checks failed (timeout) so mail config couldn't be determined |

Both `Yes` **and** `Unknown` are treated as "possible email dependency" in the
Summary and block release (see §3.9 and §4).

### 3.5 Date of last update found (column 7)

Most-specific-wins, from [`content.py`](../src/content.py):

1. Explicit modified date (meta `article:modified_time`, `og:updated_time`,
   `<time datetime>`, etc.)
2. Visible copyright year
3. Most recent plausible year mentioned on the page
4. Otherwise `Not found`

### 3.6 Content status (column 8)

A single lifecycle label chosen by **strict priority order** — the first matching
rule wins:

| Priority | Value | Trigger |
| --- | --- | --- |
| 1 | `Non-responsive` | No HTTP response at all (and not transient) |
| 2 | `Broken` | Reachable but error status / TLS failure / blank render |
| 3 | `Parked` | Parking/for-sale signals matched |
| 4 | `Placeholder` | Default-server / tiny / single-purpose page |
| 5 | `Legacy` | Obsolete branding dominant with no maintenance signals |
| 6 | `Outdated` | Copyright/last-update year older than (current year − 2) and no fresh activity |
| 7 | `Maintained` | Recent year **or** activity signals (but not both) |
| 8 | `Active` | Recent year **and** ≥2 activity signals (news/blog/products/forms…) |
| 9 | `Unknown` | Insufficient evidence (e.g. transient failure) |

"Recent" means the year is ≥ (current year − 2). "Activity signals" are content
hints like news/blog/events/products/support found on the page.

### 3.7 Likely purpose (column 9)

A short human-readable string, assembled in priority order:

1. **EU seed data wins** when present — the seed `Business Purpose` (and CMS)
   from the `EU Web Site URLs` sheet is the most authoritative signal.
2. Otherwise it is synthesized from region + the strongest available signal:
   redirect target ("… redirecting to corporate site"), parked/legacy/inactive
   status, the page `<title>`, a matched brand term, or finally the source.

This field is descriptive context, not a controlled vocabulary.

### 3.8 Defensive-registration likelihood (column 10)

Estimates whether the domain exists to **protect a brand** rather than to run a
business. Uses brand-term matching (`brands.brand_term_match`) plus activity.

| Value | When |
| --- | --- |
| `High` | A brand term is in the label **and** (the site is inactive/no live site **or** it redirects to an official property); or it is part of a multi-TLD brand bundle |
| `Medium` | Brand term with an active site, or ambiguous activity; or it redirects to an official property without a brand term in the label |
| `Low` | Active business site with no defensive characteristics; or no brand term and no defensive traits |
| `Unknown` | Insufficient evidence (transient failure) |

`High` later forces `Do not release` (brand-protective).

### 3.9 Release recommendation (column 11)

The actionable verdict, evaluated in **strict order** — the first rule that
matches wins:

1. **`Unknown`** — if checks couldn't complete at all (transient failure and
   website is `Unknown`).
2. **`Do not release`** — if any of:
   - Email functionality is `Yes` (active mail dependency), **or**
   - It redirects to an official/subsidiary property, **or**
   - Defensive likelihood is `High` (brand-protective).
3. **`Review`** — if any of:
   - Email is `Unknown`, **or**
   - Website or content status is `Unknown`, **or**
   - The page renders only `Partial`, **or**
   - Defensive likelihood is `Medium`.
4. **`Keep`** — active/business-relevant: website `Yes` and content status
   `Active` or `Maintained`.
5. **`Candidate for release`** — only if **all** hold: no website (`No`), not
   brand-protective (`Low`), no email (`No`), and content status is
   `Non-responsive`/`Broken`/`Parked`/`Placeholder`.
6. Anything left over (e.g. `Outdated`/`Legacy` content) falls back to
   **`Review`** for human judgement.

> **FR-11 mail guard (hard safety net):** after the rules above, any row that is
> `Candidate for release` but has email `Yes` or `Unknown` is forcibly downgraded
> — to `Do not release` (if `Yes`) or `Review` (if `Unknown`). This guarantees no
> domain is ever proposed for release while it might still carry live mail.

This ordering is intentionally **conservative**: when in doubt, the system
prefers `Review` or `Do not release` over `Candidate for release`.

### 3.10 Evidence / notes (column 12)

Always non-empty. It is the concatenated audit trail and typically includes: DNS
state (`DNS resolves (A=…)` or the error), mail records found (`mail: MX+SPF+DMARC`),
HTTP status and scheme, TLS errors, the redirect target, copyright year, legacy
branding, parked/placeholder flags, the **defensive reasoning**, the
**recommendation reasoning**, and the EU seed status when present. Read this first
to understand any individual verdict.

---

## 4. The Summary sheet

The Summary sheet (built by [`summary.py`](../src/summary.py)) has two blocks.

### 4.1 Metrics table

| Metric | How it's counted |
| --- | --- |
| Total domains reviewed | All rows |
| Recommended: Keep / Review / Candidate for release / Do not release / Unknown | Counts of column 11 |
| Possible email dependencies | Rows where Email functionality is `Yes` **or** `Unknown` |
| Likely defensive / fraud-prevention (High) | Rows where Defensive likelihood is `High` |

These counts **reconcile** with the Inventory sheet (the five recommendation
counts sum to the total) — a built-in consistency check.

### 4.2 Pattern groups

| Pattern | What it captures |
| --- | --- |
| Multi-TLD bundles | Same second-level label registered under multiple TLDs (e.g. `brand.*`) |
| Campaign / landing domains | Known campaign terms or a "Campaign" redirect target |
| Partner / vendor domains | Partner/vendor redirect target, or Avnet/AVT source |
| Legacy brand domains | Legacy brand label, `Legacy` content status, or legacy redirect target |
| Typo / abbreviation variants | Labels within edit-distance 1–2 of a brand term |
| Regional clusters | Row counts grouped by Region |

Each pattern row shows a count and up to ~12 example domains.

---

## 5. How to read the workbook in practice

A suggested review workflow:

1. **Start on the Summary sheet** for the headline counts and pattern groups.
2. On **Inventory**, filter **Release recommendation** to `Candidate for release`
   first — these are the safest-to-drop domains (the FR-11 guard guarantees none
   carry mail). Scan **Likely purpose** and **Evidence / notes** to confirm.
3. Filter to **`Review`** next — these need a human call (ambiguous ownership,
   partial render, medium defensive, or outdated/legacy content).
4. Treat **`Do not release`** as protected (active mail, official redirect, or
   high brand-defensive value); spot-check via **Evidence / notes**.
5. Treat **`Unknown`** as "re-check": these are transient/timeout failures. A
   warm rerun (the cache skips already-resolved domains) can often resolve them.

### Reading tips

- **`No` vs `Unknown` matters.** `No` = we checked and there's nothing; `Unknown`
  = we couldn't check. Don't action `Unknown` rows without a rerun.
- **Email `Unknown` is conservative on purpose.** It counts as a possible
  dependency and prevents release — clear it by re-resolving DNS.
- **Trust, then verify with Evidence / notes.** Every verdict is explained there;
  if a row looks wrong, the evidence string usually shows why (e.g. stale seed
  data, bot-blocking `403`, or a timeout).