"""Curated brand-term, official-property, subsidiary, and legacy-brand maps.

Used by ``redirect.py`` (to categorize redirect targets) and ``classify.py``
(for defensive-registration scoring). All matching is done on lowercased
strings; helpers accept either a full domain or a registrable domain and try to
match on the second-level label and/or full domain.
"""

from __future__ import annotations

# --------------------------------------------------------------------------- #
# Redirect-target categories (spec 5.2)
# --------------------------------------------------------------------------- #
CORPORATE = "TD SYNNEX corporate site"
SUBSIDIARY = "Subsidiary site"
LEGACY = "Legacy brand site"
CAMPAIGN = "Campaign or landing page"
PARTNER = "Partner or vendor site"
THIRD_PARTY = "Third-party unrelated site"
ERROR_PAGE = "Error page"
UNKNOWN = "Unknown"

# --------------------------------------------------------------------------- #
# Official TD SYNNEX corporate registrable domains.
# --------------------------------------------------------------------------- #
CORPORATE_DOMAINS: set[str] = {
    "tdsynnex.com",
    "tdsynnex.ca",
    "tdsynnex.co.uk",
    "tdsynnex.de",
    "tdsynnex.fr",
    "tdsynnex.it",
    "tdsynnex.es",
    "tdsynnex.nl",
    "tdsynnex.eu",
    "tdsynnex.com.au",
    "tdsynnex.co.nz",
    "tdsynnex.cn",
    "tdsynnex.in",
    "tdsynnex.com.mx",
    "tdsynnex.com.br",
    "tdsynnex.sg",
}

# Subsidiary / acquired-but-active brand domains (still operating brands).
SUBSIDIARY_DOMAINS: set[str] = {
    "hyve.com",
    "hyvesolutions.com",
    "shyfttechnologies.com",
    "shyft.com",
    "dlt.com",
    "apptium.com",
    "streamone.com",
    "maverick.com",
    "maverickav.com",
    "hyvedesign.com",
}

# Legacy / pre-merger brand domains (TD SYNNEX was formed from Tech Data + SYNNEX).
LEGACY_DOMAINS: set[str] = {
    "techdata.com",
    "techdata.ca",
    "techdata.co.uk",
    "techdata.de",
    "techdata.fr",
    "techdata.it",
    "techdata.es",
    "techdata.nl",
    "techdata.eu",
    "synnex.com",
    "synnex.ca",
    "synnexcorp.com",
    "synnex.org",
    "westconcomstor.com",
    "avnet.com",
}

# --------------------------------------------------------------------------- #
# Brand-term labels (matched against the domain's second-level label).
# --------------------------------------------------------------------------- #
CORPORATE_TERMS: set[str] = {"tdsynnex", "td-synnex", "tdsynex", "td synnex"}

LEGACY_TERMS: set[str] = {
    "techdata",
    "tech-data",
    "synnex",
    "synnexcorp",
    "avnet",
    "westcon",
    "comstor",
}

SUBSIDIARY_TERMS: set[str] = {
    "hyve",
    "shyft",
    "dlt",
    "apptium",
    "streamone",
    "stream-one",
    "maverick",
}

# Generic TD SYNNEX product / campaign / microsite terms that signal a
# brand-owned property rather than an arbitrary third party.
CAMPAIGN_TERMS: set[str] = {
    "activate-here",
    "activatehere",
    "techselect",
    "techgate",
    "tdcloud",
    "tdblog",
    "tdevents",
    "tdmobility",
    "tdeducation",
    "azzurri",
    "destination",
    "td-academy",
    "tdacademy",
    "varnex",
}

# All brand-ish terms used for defensive matching (union of the above plus
# common abbreviations / tokens that appear in TD SYNNEX-owned labels).
BRAND_TERMS: set[str] = (
    CORPORATE_TERMS | LEGACY_TERMS | SUBSIDIARY_TERMS | CAMPAIGN_TERMS | {"td"}
)

# Hosts that look like generic error / parking / registrar landing destinations.
ERROR_HOST_HINTS: tuple[str, ...] = (
    "sedoparking.com",
    "sedo.com",
    "parkingcrew.net",
    "bodis.com",
    "afternic.com",
    "godaddy.com/forsale",
    "hugedomains.com",
    "dan.com",
)


def _label_of(registrable: str) -> str:
    """Return the second-level label of a registrable domain (eTLD+1).

    ``activate-here.ca`` -> ``activate-here``; ``foo.co.uk`` -> ``foo``.
    """
    if not registrable:
        return ""
    return registrable.split(".")[0].strip().lower()


def categorize_domain(registrable: str, full_host: str | None = None) -> str:
    """Categorize a registrable domain into a redirect-target category.

    Matching priority: corporate > subsidiary > legacy > error-host > campaign
    term > brand/partner heuristics > third-party.
    """
    if not registrable:
        return UNKNOWN

    registrable = registrable.strip().lower()
    host = (full_host or registrable).strip().lower()
    label = _label_of(registrable)

    if registrable in CORPORATE_DOMAINS or label in CORPORATE_TERMS:
        return CORPORATE
    if registrable in SUBSIDIARY_DOMAINS or label in SUBSIDIARY_TERMS:
        return SUBSIDIARY
    if registrable in LEGACY_DOMAINS or label in LEGACY_TERMS:
        return LEGACY

    for hint in ERROR_HOST_HINTS:
        if hint in host:
            return ERROR_PAGE

    if label in CAMPAIGN_TERMS:
        return CAMPAIGN

    # Compound-label fallback (e.g. "hyvesolutions", "tdsynnex-cloud"): map a
    # contained brand term to its category.
    term = brand_term_match(registrable)
    if term:
        if term in CORPORATE_TERMS:
            return CORPORATE
        if term in SUBSIDIARY_TERMS:
            return SUBSIDIARY
        if term in LEGACY_TERMS:
            return LEGACY
        if term in CAMPAIGN_TERMS:
            return CAMPAIGN

    return THIRD_PARTY


def is_official_property(registrable: str) -> bool:
    """True if the domain is an official corporate or active subsidiary property."""
    if not registrable:
        return False
    registrable = registrable.strip().lower()
    label = _label_of(registrable)
    return (
        registrable in CORPORATE_DOMAINS
        or registrable in SUBSIDIARY_DOMAINS
        or label in CORPORATE_TERMS
        or label in SUBSIDIARY_TERMS
    )


def brand_term_match(registrable: str) -> str | None:
    """Return the brand term matched by the domain label, or None.

    Checks the second-level label first, then substring containment for
    compound labels (e.g. ``tdsynnex-cloud``).
    """
    if not registrable:
        return None
    label = _label_of(registrable)
    if label in BRAND_TERMS:
        return label
    for term in sorted(BRAND_TERMS, key=len, reverse=True):
        if len(term) >= 4 and term in label:
            return term
    return None


def is_legacy_term(text: str) -> list[str]:
    """Return legacy brand terms found in arbitrary text (for content analysis)."""
    if not text:
        return []
    low = text.lower()
    found = []
    # Use spaced/cased legacy names for on-page detection.
    for name in ("tech data", "synnex", "avnet", "westcon", "comstor"):
        if name in low:
            found.append(name)
    return found
