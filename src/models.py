"""Data models for the domain inventory pipeline (spec Section 3).

Plain dataclasses. All fields are optional (have defaults) unless noted as the
unique key. Allowed-value sets are documented inline and enforced by the
classification engine in ``classify.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


# --------------------------------------------------------------------------- #
# Allowed value vocabularies (spec Section 3.6 / specification.md 95-108)
# --------------------------------------------------------------------------- #

YES_NO_UNKNOWN = ("Yes", "No", "Unknown")
RENDER_VALUES = ("Yes", "No", "Partial", "Unknown")
CONTENT_STATUS_VALUES = (
    "Active",
    "Maintained",
    "Outdated",
    "Legacy",
    "Parked",
    "Placeholder",
    "Broken",
    "Non-responsive",
    "Unknown",
)
DEFENSIVE_VALUES = ("High", "Medium", "Low", "Unknown")
RECOMMENDATION_VALUES = (
    "Keep",
    "Review",
    "Candidate for release",
    "Do not release",
    "Unknown",
)


# --------------------------------------------------------------------------- #
# 3.1 InputDomain
# --------------------------------------------------------------------------- #
@dataclass
class InputDomain:
    """A normalized source domain plus original metadata and EU seed fields."""

    domain: str = ""              # normalized registrable domain (unique key)
    original: str = ""           # original cell value as listed
    tld: str = ""
    country: str = ""
    source: str = ""             # e.g. "TD SYNNEX", "AVT (Avnet)"
    hosting: str = ""            # "Domain Hosting" column
    region: str = ""             # North America | EMEA | LATAM | APJ | ...
    classification_method: str = ""

    seed_url: Optional[str] = None              # EU col A
    seed_site_status: Optional[str] = None      # EU col F
    seed_purpose: Optional[str] = None          # EU col G
    seed_cms: Optional[str] = None              # EU col H
    seed_hosting_provider: Optional[str] = None  # EU col I

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #
# 3.2 DnsResult
# --------------------------------------------------------------------------- #
@dataclass
class DnsResult:
    resolves: bool = False
    a: list[str] = field(default_factory=list)
    aaaa: list[str] = field(default_factory=list)
    cname: list[str] = field(default_factory=list)
    mx: list[str] = field(default_factory=list)
    spf: Optional[str] = None        # raw SPF TXT if present
    dmarc: Optional[str] = None      # raw _dmarc TXT if present
    dkim_selectors: list[str] = field(default_factory=list)
    error: Optional[str] = None      # NXDOMAIN | NoAnswer | Timeout | ...

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "DnsResult":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# --------------------------------------------------------------------------- #
# 3.3 HttpResult
# --------------------------------------------------------------------------- #
@dataclass
class HttpResult:
    reachable: bool = False
    scheme_used: Optional[str] = None      # https | http
    final_url: Optional[str] = None
    status_code: Optional[int] = None
    redirect_chain: list[str] = field(default_factory=list)
    redirected_offdomain: bool = False
    tls_error: Optional[str] = None
    http_error: Optional[str] = None
    elapsed_ms: Optional[int] = None
    html: Optional[str] = None             # raw body (cached, not emitted)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "HttpResult":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# --------------------------------------------------------------------------- #
# 3.4 ContentResult
# --------------------------------------------------------------------------- #
@dataclass
class ContentResult:
    render_status: str = "Unknown"         # Yes | Partial | No | Unknown
    last_update: Optional[str] = None      # date | year | None
    copyright_year: Optional[int] = None
    maintenance_signals: list[str] = field(default_factory=list)
    parked: bool = False
    placeholder: bool = False
    obsolete_branding: list[str] = field(default_factory=list)
    has_mail_form: bool = False
    title: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ContentResult":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# --------------------------------------------------------------------------- #
# 3.5 EmailResult
# --------------------------------------------------------------------------- #
@dataclass
class EmailResult:
    has_mx: bool = False
    has_spf: bool = False
    has_dmarc: bool = False
    has_dkim: bool = False
    has_mail_form: bool = False
    email_functionality: str = "Unknown"   # Yes | No | Unknown

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "EmailResult":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# --------------------------------------------------------------------------- #
# 3.6 ClassifiedDomain (the deliverable row)
# --------------------------------------------------------------------------- #
@dataclass
class ClassifiedDomain:
    domain: str = ""
    website_behind_url: str = "Unknown"    # Yes | No | Unknown
    redirect: str = "Unknown"              # Yes | No | Unknown
    redirect_target: str = "Unknown"       # URL | <category> | Unknown
    page_opens_renders: str = "Unknown"    # Yes | No | Partial | Unknown
    email_functionality: str = "Unknown"   # Yes | No | Unknown
    date_last_update: str = "Not found"     # Date | Year | Not found
    content_status: str = "Unknown"         # see CONTENT_STATUS_VALUES
    likely_purpose: str = ""                # short text
    defensive_likelihood: str = "Unknown"   # High | Medium | Low | Unknown
    release_recommendation: str = "Unknown"  # see RECOMMENDATION_VALUES
    evidence_notes: str = ""                # short text (always non-empty)

    # Provenance (appended after the 12 spec fields for traceability).
    region: str = ""
    source: str = ""
    country: str = ""

    # Error captured by the orchestrator if the domain failed catastrophically.
    error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #
# 3.7 Summary (spec Section 6.3)
# --------------------------------------------------------------------------- #
@dataclass
class Summary:
    total: int = 0
    keep: int = 0
    review: int = 0
    candidate_release: int = 0
    do_not_release: int = 0
    unknown: int = 0
    email_dependency: int = 0
    defensive_high: int = 0
    patterns: dict[str, list[str]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)
