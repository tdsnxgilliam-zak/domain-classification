"""Classification and recommendation engine (spec Section 5, task T10).

Applies the deterministic decision logic to all collected evidence and produces
the 12 ``ClassifiedDomain`` fields with only allowed values, a non-empty
evidence string, and the FR-11 mail-dependency guard.
"""

from __future__ import annotations

from datetime import datetime

from . import brands
from .models import (
    ClassifiedDomain,
    ContentResult,
    DnsResult,
    EmailResult,
    HttpResult,
    InputDomain,
)

CURRENT_YEAR = datetime.now().year
OUTDATED_BEFORE = CURRENT_YEAR - 2


def _is_transient(http: HttpResult, dns: DnsResult) -> bool:
    """True if failure looks transient (timeout) rather than definitive."""
    if http and http.http_error and "Timeout" in (http.http_error or ""):
        return True
    if dns and not dns.resolves and dns.error == "Timeout":
        return True
    return False


def _website_behind_url(http: HttpResult, dns: DnsResult, content: ContentResult) -> str:
    if http and http.reachable:
        status = http.status_code or 0
        has_body = bool(http.html and len(http.html.strip()) > 0)
        if 200 <= status < 400 and (has_body or content.render_status in ("Yes", "Partial")):
            return "Yes"
        if status >= 400 and not has_body:
            return "No"
        # 2xx/3xx but empty body.
        return "No" if not has_body else "Yes"
    # Not reachable.
    if _is_transient(http, dns):
        return "Unknown"
    return "No"


def _date_last_update(content: ContentResult) -> str:
    if content.last_update:
        return content.last_update
    if content.copyright_year:
        return str(content.copyright_year)
    return "Not found"


def _content_status(http: HttpResult, dns: DnsResult, content: ContentResult,
                    website: str) -> str:
    # 1. Non-responsive: resolves but no HTTP response.
    if not (http and http.reachable):
        if _is_transient(http, dns):
            return "Unknown"
        if dns and dns.resolves:
            return "Non-responsive"
        # DNS does not resolve at all -> no response possible.
        return "Non-responsive" if (dns and dns.error == "NXDOMAIN") else "Non-responsive"

    status = http.status_code or 0
    # 2. Broken: error status / TLS failure / blank render.
    if status >= 400 or content.render_status == "No":
        return "Broken"

    # 3. Parked.
    if content.parked:
        return "Parked"
    # 4. Placeholder.
    if content.placeholder:
        return "Placeholder"
    # 5. Legacy: obsolete branding dominant.
    if content.obsolete_branding and not content.maintenance_signals:
        return "Legacy"

    year = content.copyright_year
    if not year and content.last_update and content.last_update.isdigit():
        year = int(content.last_update)

    fresh_year = bool(year and year >= OUTDATED_BEFORE)
    has_activity = len(content.maintenance_signals) >= 2

    # 6. Outdated.
    if year and year < OUTDATED_BEFORE and not has_activity:
        return "Outdated"
    # 8. Active.
    if fresh_year and has_activity:
        return "Active"
    # 7. Maintained.
    if fresh_year or has_activity:
        return "Maintained"
    # If it renders fine but we have no dating signal, call it Maintained-ish
    # only when there is some content; else Unknown.
    if content.render_status == "Yes":
        return "Maintained"
    return "Unknown"


def _defensive_likelihood(inp: InputDomain, http: HttpResult, content: ContentResult,
                          website: str, redirect_target: str,
                          bundle_member: bool = False) -> tuple[str, str]:
    """Return (likelihood, reason)."""
    brand = brands.brand_term_match(inp.domain)
    redirects_official = any(
        cat in (redirect_target or "")
        for cat in (brands.CORPORATE, brands.SUBSIDIARY)
    )
    inactive = website in ("No", "Unknown") or content.render_status in ("No",)
    active_business = website == "Yes" and content.render_status in ("Yes", "Partial") \
        and not content.parked and not content.placeholder

    if brand and (inactive or redirects_official) or bundle_member and brand:
        return "High", f"brand term '{brand}'" + (
            "; inactive/no live site" if inactive else
            "; redirects to official property" if redirects_official else
            "; multi-TLD brand bundle")
    if brand and active_business:
        return "Medium", f"brand term '{brand}' with active site"
    if brand:
        return "Medium", f"brand term '{brand}', ambiguous activity"
    if redirects_official:
        return "Medium", "redirects to official property (no brand term in label)"
    if active_business:
        return "Low", "active business site, no defensive characteristics"
    if website == "Unknown":
        return "Unknown", "insufficient evidence (transient failure)"
    return "Low", "no brand term, no defensive characteristics"


def _likely_purpose(inp: InputDomain, content: ContentResult, redirect: str,
                    redirect_target: str, content_status: str) -> str:
    parts: list[str] = []

    # Seed data is the strongest signal when present.
    if inp.seed_purpose:
        parts.append(inp.seed_purpose.strip().rstrip(".")[:120])
    if inp.seed_cms:
        cms = inp.seed_cms.strip()
        if cms and cms.lower() != "unknown":
            parts.append(f"CMS: {cms}")

    if not parts:
        region = inp.region or "Unclassified"
        subsidiary = inp.region in ("Hyve", "Shyft")
        brand = brands.brand_term_match(inp.domain)
        if redirect == "Yes" and any(
            c in (redirect_target or "")
            for c in (brands.CORPORATE, brands.SUBSIDIARY, brands.LEGACY)
        ):
            tgt = (redirect_target or "").split(" (")[0]
            parts.append(f"{region} domain redirecting to {tgt.lower()}")
        elif content_status == "Parked":
            parts.append(f"{region} parked/for-sale domain")
        elif content_status in ("Legacy",):
            parts.append(f"{region} legacy-brand domain")
        elif content_status in ("Non-responsive", "Broken"):
            parts.append(f"{region} inactive domain ({content_status.lower()})")
        elif content.title:
            parts.append(f"{region} site: {content.title.strip()[:80]}")
        elif brand:
            parts.append(f"{region} brand-related domain ('{brand}')")
        else:
            parts.append(f"{region} domain ({inp.source or 'source n/a'})")

    return "; ".join(p for p in parts if p)[:240] or "Unknown purpose"


def _release_recommendation(
    website: str, email_func: str, content_status: str,
    defensive: str, redirect_target: str, content: ContentResult,
    transient: bool,
) -> tuple[str, str]:
    """Return (recommendation, reason). FR-11 mail guard enforced."""
    redirects_protected = any(
        c in (redirect_target or "")
        for c in (brands.CORPORATE, brands.SUBSIDIARY)
    )

    # 5. Unknown if checks could not be completed at all.
    if transient and website == "Unknown":
        return "Unknown", "checks incomplete (transient failure)"

    # 1. Do not release.
    if email_func == "Yes":
        return "Do not release", "active mail dependency present"
    if redirects_protected:
        return "Do not release", "redirects to official/subsidiary property"
    if defensive == "High":
        return "Do not release", "high defensive-registration likelihood (brand-protective)"

    # 2. Review.
    if email_func == "Unknown":
        return "Review", "email dependency unclear"
    if website == "Unknown" or content_status == "Unknown":
        return "Review", "insufficient/ambiguous evidence"
    if content.render_status == "Partial":
        return "Review", "partial functionality / thin page"
    if defensive == "Medium":
        return "Review", "medium defensive likelihood; ownership/purpose unclear"

    active = website == "Yes" and content_status in ("Active", "Maintained")

    # 4. Keep (business-relevant / active) - evaluated before release candidate.
    if active:
        return "Keep", "active / business-relevant site"

    # 3. Candidate for release (hard-blocked by FR-11 mail guard).
    no_website = website == "No"
    no_email = email_func == "No"
    not_protective = defensive == "Low"
    no_business_purpose = content_status in ("Non-responsive", "Broken", "Parked",
                                             "Placeholder")
    if no_website and not_protective and no_email and no_business_purpose:
        return "Candidate for release", "no live site, no mail, not brand-protective"

    # Anything else falls to Review for human judgement.
    if content_status in ("Outdated", "Legacy"):
        return "Review", f"{content_status.lower()} content; needs human review"
    return "Review", "no clear keep/release signal"


def classify(
    inp: InputDomain,
    dns: DnsResult,
    http: HttpResult,
    content: ContentResult,
    email: EmailResult,
    redirect: tuple[str, str],
    *,
    bundle_member: bool = False,
) -> ClassifiedDomain:
    """Produce the 12-field ClassifiedDomain from all evidence."""
    redirect_flag, redirect_target = redirect if redirect else ("Unknown", "Unknown")

    website = _website_behind_url(http, dns, content)
    page_renders = content.render_status if (http and http.reachable) else (
        "Unknown" if _is_transient(http, dns) else "No"
    )
    email_func = email.email_functionality
    date_last = _date_last_update(content)
    content_status = _content_status(http, dns, content, website)
    defensive, defensive_reason = _defensive_likelihood(
        inp, http, content, website, redirect_target, bundle_member
    )
    likely_purpose = _likely_purpose(
        inp, content, redirect_flag, redirect_target, content_status
    )
    transient = _is_transient(http, dns)
    recommendation, rec_reason = _release_recommendation(
        website, email_func, content_status, defensive, redirect_target, content,
        transient,
    )

    # FR-11 safety net: never release with an active/unclear mail dependency.
    if recommendation == "Candidate for release" and email_func in ("Yes", "Unknown"):
        recommendation = "Do not release" if email_func == "Yes" else "Review"
        rec_reason = "FR-11 mail guard: " + (
            "active mail dependency" if email_func == "Yes" else "mail dependency unclear"
        )

    # Build human-readable evidence (always non-empty).
    ev: list[str] = []
    if dns:
        if dns.resolves:
            ev.append("DNS resolves" + (f" (A={len(dns.a)})" if dns.a else ""))
        else:
            ev.append(f"DNS: {dns.error or 'no records'}")
        mail_bits = []
        if dns.mx:
            mail_bits.append("MX")
        if dns.spf:
            mail_bits.append("SPF")
        if dns.dmarc:
            mail_bits.append("DMARC")
        if dns.dkim_selectors:
            mail_bits.append("DKIM")
        if content and content.has_mail_form:
            mail_bits.append("mail-form")
        if mail_bits:
            ev.append("mail: " + "+".join(mail_bits))
    if http:
        if http.reachable:
            ev.append(f"HTTP {http.status_code} via {http.scheme_used}")
            if http.tls_error:
                ev.append("TLS error")
        elif http.http_error:
            ev.append(f"HTTP fail: {http.http_error.split(':')[0]}")
    if redirect_flag == "Yes":
        ev.append(f"redirect-> {redirect_target}")
    if content:
        if content.copyright_year:
            ev.append(f"copyright {content.copyright_year}")
        if content.obsolete_branding:
            ev.append("legacy branding: " + ",".join(content.obsolete_branding))
        if content.parked:
            ev.append("parked")
        if content.placeholder:
            ev.append("placeholder")
    ev.append(f"defensive: {defensive_reason}")
    ev.append(f"rec: {rec_reason}")
    if inp.seed_site_status:
        ev.append(f"EU seed status: {inp.seed_site_status}")

    evidence_notes = "; ".join(ev) or "no evidence collected"

    return ClassifiedDomain(
        domain=inp.domain,
        website_behind_url=website,
        redirect=redirect_flag,
        redirect_target=redirect_target,
        page_opens_renders=page_renders,
        email_functionality=email_func,
        date_last_update=date_last,
        content_status=content_status,
        likely_purpose=likely_purpose,
        defensive_likelihood=defensive,
        release_recommendation=recommendation,
        evidence_notes=evidence_notes,
        region=inp.region,
        source=inp.source,
        country=inp.country,
    )
