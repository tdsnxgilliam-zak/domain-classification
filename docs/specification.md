# Worldwide Domain Inventory Analysis Specification

## Objective

Create a worldwide inventory of company-owned or company-related domains and classify each domain by current use, technical status, business purpose, and retention recommendation.

The goal is to determine which domains are actively used, which are inactive or abandoned, which exist for brand protection, and which may be candidates for release after business and security review.

## Background

TD SYNNEX has a large number of domains across regions, brands, subsidiaries, campaigns, acquisitions, and defensive registrations. We have the domain list, but we do not yet have a reliable understanding of:

- Whether each domain is active.
- Whether a website exists behind each domain.
- Whether the domain redirects to another destination.
- Whether the content is maintained, outdated, abandoned, parked, or broken.
- Whether the domain may support email or other business-critical services.
- Whether the domain protects TD SYNNEX, SYNNEX, Tech Data, subsidiary, or legacy brand identity.

## Scope

Analyze every domain in the provided source file. For each domain, collect evidence and assign a classification using the fields defined in this specification.

Include domains related to:

- TD SYNNEX
- SYNNEX
- Tech Data
- Legacy acquired brands
- Subsidiaries
- Regional businesses
- Campaigns or microsites
- Partner or vendor activity
- Abbreviations, typo variants, and alternate TLDs
- Defensive or fraud-prevention registrations

## Required Checks

For each domain, perform the following checks.

### Technical Status

- Check whether the domain resolves.
- Check whether HTTP and HTTPS are reachable.
- Check whether a website exists behind the URL.
- Check whether the URL redirects to another domain or path.
- Record the final destination after redirects.
- Check whether the page loads and renders successfully.
- Identify errors such as DNS failure, connection timeout, TLS certificate failure, HTTP error, blank page, or script/render failure.

### Content Status

- Identify whether the site appears active, maintained, outdated, legacy, abandoned, parked, placeholder-only, broken, or non-responsive.
- Capture visible indicators of maintenance, such as recent copyright year, news posts, events, product updates, blog posts, support notices, or active forms.
- Record the latest visible update date, if one can be found.
- Note whether content references obsolete branding, discontinued campaigns, outdated products, expired events, or legacy company names.

### Redirect Behavior

- Identify whether the domain redirects.
- Record the redirect target.
- Classify the redirect target as one of:
  - TD SYNNEX corporate site
  - Subsidiary site
  - Legacy brand site
  - Campaign or landing page
  - Partner or vendor site
  - Third-party unrelated site
  - Error page
  - Unknown

### Email and Mail Dependency

- Check whether the domain has mail-related dependencies or functionality.
- Look for MX records, SPF records, DKIM records, DMARC records, mail subdomains, contact forms, newsletter signup forms, login portals, or other email-related behavior.
- Do not recommend release for a domain with active or unclear mail dependencies until ownership and usage are confirmed.

### Defensive Registration and Brand Protection

Identify domains that may exist to prevent fraud, typo-squatting, impersonation, customer confusion, or brand abuse.

Consider a domain more likely to be defensive if it contains:

- TD SYNNEX, SYNNEX, Tech Data, or subsidiary brand terms.
- Common misspellings, abbreviations, or typo variants.
- Alternate TLDs for the same brand or phrase.
- Regional variants of known company domains.
- Domains that redirect to an official company property.
- Domains that are inactive but clearly protect a brand, product, or campaign name.

## Required Output Fields

Deliver one completed row per domain with the following fields.

| Field | Description | Allowed Values / Format |
| --- | --- | --- |
| Domain | Original domain from the source list. | Domain name |
| Website behind URL? | Whether a reachable website exists. | Yes / No / Unknown |
| Redirect? | Whether the domain redirects. | Yes / No / Unknown |
| Redirect target | Final URL or destination category, if applicable. | URL or Unknown |
| Page opens / renders? | Whether the page loads and renders usable content. | Yes / No / Partial / Unknown |
| Email functionality? | Whether mail records, forms, or mail dependencies are present. | Yes / No / Unknown |
| Date of last update found | Latest visible content update date. | Date / Year / Not found |
| Content status | Current content classification. | Active / Maintained / Outdated / Legacy / Parked / Placeholder / Broken / Non-responsive / Unknown |
| Likely purpose | Best assessment of why the domain exists. | Short text |
| Defensive-registration likelihood | Likelihood that the domain is held for fraud prevention or brand protection. | High / Medium / Low / Unknown |
| Release recommendation | Recommended disposition. | Keep / Review / Candidate for release / Do not release / Unknown |
| Evidence / notes | Short explanation supporting the classification. | Short text |

## Classification Guidance

Use the following guidance when assigning recommendations.

### Keep

Use `Keep` when the domain appears active, business-relevant, customer-facing, regionally relevant, tied to a subsidiary, or clearly protective of a current brand.

### Review

Use `Review` when the domain has unclear ownership, unclear business purpose, partial functionality, possible mail dependencies, ambiguous redirects, or insufficient evidence to safely decide.

### Candidate for release

Use `Candidate for release` when the domain appears unused, non-responsive, not brand-protective, has no visible business purpose, and has no apparent mail dependency.

### Do not release

Use `Do not release` when the domain is active, supports email, redirects to an official property, protects a brand, appears security-sensitive, or may prevent impersonation or customer confusion.

### Unknown

Use `Unknown` when checks could not be completed or available evidence is insufficient.

## Subsidiary Reference

Consider the following subsidiaries and business units when assessing domain purpose and brand protection value.

| Name | Description |
| --- | --- |
| Hyve | Hyve Solutions designs and deploys hyperscale digital infrastructure solutions, including server, storage, and networking solutions for data centers. |
| Shyft Services | Shyft provides end-to-end technology lifecycle services, including supply chain management, integration, repair, deployment, and asset disposition. |
| DLT | DLT specializes in IT distribution for the U.S. public sector, including federal, state and local government, education, healthcare, and utility markets. |
| Apptium | Apptium specializes in XaaS and cloud commerce solutions, with a focus on multi-cloud operations and subscription-based service adoption. Apptium provides the platform for StreamOne ION, the future standard cloud commerce platform. |

## Suggested Workflow

1. Normalize the domain list and remove duplicate entries.
2. Check DNS resolution and key records, including A, CNAME, MX, TXT, SPF, DKIM, and DMARC where available.
3. Test HTTP and HTTPS behavior.
4. Follow redirects and record the final destination.
5. Capture page load status, render status, HTTP status codes, TLS issues, and visible errors.
6. Review visible page content for maintenance signals, outdated references, and business purpose.
7. Check for email or form functionality.
8. Assign classifications and recommendations using the guidance above.
9. Add concise evidence for every recommendation.
10. Flag domains that require business owner, legal, brand, security, or infrastructure review.

## Tooling

Teams may use any available tools, including Cursor, Copilot, browser automation, DNS tools, HTTP clients, scripts, spreadsheets, or other approved analysis utilities.

Automation is encouraged, but final recommendations should include human-readable evidence and should not rely only on automated status codes.

## Deliverables

Submit the completed domain inventory in a spreadsheet or structured table with all required output fields.

Include a short summary covering:

- Total domains reviewed.
- Number of domains recommended to keep.
- Number of domains requiring review.
- Number of domains that are candidates for release.
- Number of domains with possible email dependencies.
- Number of domains likely used for defensive registration or fraud prevention.
- Any patterns discovered, such as multi-TLD bundles, campaign domains, partner/vendor domains, legacy brand domains, typo variants, or regional clusters.

## Deadline

Team submissions are due Friday, June 19 at 5:00 PM local time.