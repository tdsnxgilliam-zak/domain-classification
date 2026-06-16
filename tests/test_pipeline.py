"""Offline test/validation framework for the domain-inventory pipeline.

These tests exercise the deterministic logic (no network required): models,
brand maps, ingestion counts/dedup, content analysis, email assessment, redirect
classification, the classification decision engine (every branch), summary
reconciliation, the output contract, and end-to-end allowed-value enforcement.

Run with:  py -m pytest -q
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from src import brands
from src.classify import classify
from src.content import analyze
from src.email import assess
from src.ingest import load_domains, registrable_domain
from src.models import (
    CONTENT_STATUS_VALUES,
    DEFENSIVE_VALUES,
    RECOMMENDATION_VALUES,
    RENDER_VALUES,
    YES_NO_UNKNOWN,
    ClassifiedDomain,
    ContentResult,
    DnsResult,
    EmailResult,
    HttpResult,
    InputDomain,
    Summary,
)
from src.output import ALL_HEADERS, SPEC_HEADERS, write_csv, write_xlsx
from src.redirect import classify_target
from src.summary import summarize

SOURCE = Path(__file__).resolve().parents[1] / "url-regional-class.xlsx"


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
def test_models_instantiate_with_defaults():
    for cls in (InputDomain, DnsResult, HttpResult, ContentResult, EmailResult,
                ClassifiedDomain, Summary):
        obj = cls()
        assert obj.to_dict() is not None


def test_result_roundtrip():
    d = DnsResult(resolves=True, a=["1.2.3.4"], mx=["mx1"])
    assert DnsResult.from_dict(d.to_dict()).a == ["1.2.3.4"]


# --------------------------------------------------------------------------- #
# Brands (T3)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("domain,expected", [
    ("tdsynnex.com", brands.CORPORATE),
    ("tdsynnex.fr", brands.CORPORATE),
    ("techdata.com", brands.LEGACY),
    ("synnex.com", brands.LEGACY),
    ("hyve.com", brands.SUBSIDIARY),
    ("hyvesolutions.de", brands.SUBSIDIARY),
    ("activate-here.ca", brands.CAMPAIGN),
    ("randomshop.xyz", brands.THIRD_PARTY),
])
def test_categorize_domain(domain, expected):
    assert brands.categorize_domain(domain) == expected


def test_error_host_detection():
    assert brands.categorize_domain("foo.com", "foo.sedoparking.com") == brands.ERROR_PAGE


def test_official_property():
    assert brands.is_official_property("tdsynnex.com")
    assert not brands.is_official_property("randomshop.xyz")


# --------------------------------------------------------------------------- #
# Ingestion (T4)
# --------------------------------------------------------------------------- #
def test_registrable_domain_normalization():
    assert registrable_domain("https://WWW.Example.com/path?x=1") == "example.com"
    assert registrable_domain("  www.foo.co.uk  ") == "foo.co.uk"
    assert registrable_domain("synnex.br.com") == "synnex.br.com"  # private suffix


@pytest.mark.skipif(not SOURCE.exists(), reason="source workbook not present")
def test_ingest_yields_945_unique():
    domains = load_domains(SOURCE)
    assert len(domains) == 945
    assert len({d.domain for d in domains}) == 945  # all unique


@pytest.mark.skipif(not SOURCE.exists(), reason="source workbook not present")
def test_eu_seed_merge():
    domains = load_domains(SOURCE)
    assert any(d.seed_site_status for d in domains)


# --------------------------------------------------------------------------- #
# Content (T7)
# --------------------------------------------------------------------------- #
def _wrap(html, status=200):
    return HttpResult(reachable=True, status_code=status, html=html, scheme_used="https")


def test_content_active():
    html = ("<html><head><title>Acme</title></head><body><h1>Hi</h1>"
            + "We sell products and have news blog events. Contact us. " * 20
            + "<footer>Copyright 2025 Acme</footer></body></html>")
    c = analyze(_wrap(html))
    assert c.render_status == "Yes"
    assert c.copyright_year == 2025
    assert not c.parked and not c.placeholder


def test_content_parked():
    c = analyze(_wrap("<html><body>This domain is for sale. Buy this domain at sedo.com</body></html>"))
    assert c.parked


def test_content_placeholder():
    c = analyze(_wrap("<html><body>Welcome to nginx</body></html>"))
    assert c.placeholder


def test_content_legacy_branding():
    html = "<html><body>" + "Tech Data and Avnet legacy. " * 20 + "</body></html>"
    c = analyze(_wrap(html))
    assert "tech data" in c.obsolete_branding


# --------------------------------------------------------------------------- #
# Email (T8)
# --------------------------------------------------------------------------- #
def test_email_yes_mx():
    assert assess(DnsResult(resolves=True, mx=["m"]), ContentResult()).email_functionality == "Yes"


def test_email_no():
    assert assess(DnsResult(resolves=True), ContentResult()).email_functionality == "No"


def test_email_unknown_on_dns_timeout():
    assert assess(DnsResult(resolves=False, error="Timeout"), ContentResult()).email_functionality == "Unknown"


# --------------------------------------------------------------------------- #
# Redirect (T9)
# --------------------------------------------------------------------------- #
def test_redirect_to_corporate():
    http = HttpResult(reachable=True, status_code=200,
                      final_url="https://www.tdsynnex.com/",
                      redirect_chain=["http://activate-here.ca/", "https://www.tdsynnex.com/"],
                      redirected_offdomain=True)
    flag, target = classify_target(http, "activate-here.ca")
    assert flag == "Yes" and brands.CORPORATE in target


def test_redirect_none():
    http = HttpResult(reachable=True, status_code=200, final_url="https://foo.com/",
                      redirect_chain=["https://foo.com/"], redirected_offdomain=False)
    flag, target = classify_target(http, "foo.com")
    assert flag == "No"


def test_redirect_unknown_when_unreachable():
    assert classify_target(HttpResult(reachable=False), "foo.com") == ("Unknown", "Unknown")


# --------------------------------------------------------------------------- #
# Classification engine - every branch (T10)
# --------------------------------------------------------------------------- #
def _classify(inp, dns, http, content, redir):
    return classify(inp, dns, http, content, assess(dns, content), redir)


def test_classify_active_keep():
    r = _classify(
        InputDomain(domain="shop.com", region="EMEA"),
        DnsResult(resolves=True, a=["1.2.3.4"]),
        _wrap("x" * 500),
        ContentResult(render_status="Yes", copyright_year=2025,
                      maintenance_signals=["news", "blog", "products"]),
        ("No", "https://shop.com"),
    )
    assert r.release_recommendation == "Keep"
    assert r.content_status == "Active"


def test_classify_brand_inactive_do_not_release():
    r = _classify(
        InputDomain(domain="tdsynnex.io", region="Non-Classified"),
        DnsResult(resolves=False, error="NXDOMAIN"),
        HttpResult(reachable=False, http_error="ConnectionError"),
        ContentResult(render_status="No"),
        ("Unknown", "Unknown"),
    )
    assert r.defensive_likelihood == "High"
    assert r.release_recommendation == "Do not release"


def test_classify_nonbrand_dead_candidate():
    r = _classify(
        InputDomain(domain="randomthing.xyz", region="Non-Classified"),
        DnsResult(resolves=False, error="NXDOMAIN"),
        HttpResult(reachable=False, http_error="ConnectionError"),
        ContentResult(render_status="No"),
        ("Unknown", "Unknown"),
    )
    assert r.release_recommendation == "Candidate for release"


def test_classify_mail_blocks_release():
    r = _classify(
        InputDomain(domain="maildead.xyz", region="Non-Classified"),
        DnsResult(resolves=True, mx=["m"]),
        HttpResult(reachable=False, http_error="ConnectionError"),
        ContentResult(render_status="No"),
        ("Unknown", "Unknown"),
    )
    assert r.release_recommendation != "Candidate for release"
    assert r.email_functionality == "Yes"


def test_classify_transient_unknown():
    r = _classify(
        InputDomain(domain="timeout.xyz", region="Non-Classified"),
        DnsResult(resolves=False, error="Timeout"),
        HttpResult(reachable=False, http_error="Timeout:read"),
        ContentResult(),
        ("Unknown", "Unknown"),
    )
    assert r.release_recommendation == "Unknown"


def test_fr11_mail_guard_never_releases_with_mail():
    """No Candidate-for-release row may have email Yes/Unknown."""
    # Force a scenario that would otherwise be a candidate but with mail unknown.
    r = classify(
        InputDomain(domain="x.xyz"),
        DnsResult(resolves=False, error="Timeout"),  # email -> Unknown
        HttpResult(reachable=False, http_error="ConnectionError"),
        ContentResult(render_status="No"),
        EmailResult(email_functionality="Unknown"),
        ("Unknown", "Unknown"),
    )
    assert not (r.release_recommendation == "Candidate for release")


# --------------------------------------------------------------------------- #
# Allowed-value enforcement across all fields
# --------------------------------------------------------------------------- #
def test_all_fields_use_allowed_values():
    r = _classify(
        InputDomain(domain="shop.com", region="EMEA"),
        DnsResult(resolves=True, a=["1.2.3.4"]),
        _wrap("x" * 500),
        ContentResult(render_status="Yes", copyright_year=2025,
                      maintenance_signals=["news", "blog"]),
        ("No", "https://shop.com"),
    )
    assert r.website_behind_url in YES_NO_UNKNOWN
    assert r.redirect in YES_NO_UNKNOWN
    assert r.email_functionality in YES_NO_UNKNOWN
    assert r.page_opens_renders in RENDER_VALUES
    assert r.content_status in CONTENT_STATUS_VALUES
    assert r.defensive_likelihood in DEFENSIVE_VALUES
    assert r.release_recommendation in RECOMMENDATION_VALUES
    assert r.evidence_notes  # non-empty


# --------------------------------------------------------------------------- #
# Summary (T13)
# --------------------------------------------------------------------------- #
def _sample_rows():
    return [
        ClassifiedDomain(domain="activate-here.ca", release_recommendation="Keep",
                         email_functionality="Yes", region="North America"),
        ClassifiedDomain(domain="activate-here.us", release_recommendation="Review",
                         email_functionality="No", region="North America"),
        ClassifiedDomain(domain="techdata.de", release_recommendation="Do not release",
                         defensive_likelihood="High", content_status="Legacy",
                         email_functionality="No", region="EMEA"),
        ClassifiedDomain(domain="dead.xyz", release_recommendation="Candidate for release",
                         email_functionality="No", region="Non-Classified"),
    ]


def test_summary_reconciles():
    rows = _sample_rows()
    s = summarize(rows)
    assert s.total == 4
    assert s.keep + s.review + s.candidate_release + s.do_not_release + s.unknown == s.total
    assert s.email_dependency == 1
    assert s.defensive_high == 1
    # Multi-TLD bundle: activate-here.ca + .us.
    assert any("activate-here" in e for e in s.patterns["Multi-TLD bundles"])
    assert s.patterns["Regional clusters"]


# --------------------------------------------------------------------------- #
# Output contract (T12)
# --------------------------------------------------------------------------- #
def test_output_headers_match_spec_order():
    assert SPEC_HEADERS[0] == "Domain"
    assert SPEC_HEADERS[-1] == "Evidence / notes"
    assert ALL_HEADERS[-3:] == ["Region", "Source", "Country"]


def test_write_csv_and_xlsx(tmp_path):
    rows = _sample_rows()
    s = summarize(rows)
    csv_path = write_csv(rows, tmp_path / "inv.csv")
    xlsx_path = write_xlsx(rows, s, tmp_path / "inv.xlsx")
    assert csv_path.exists() and xlsx_path.exists()
    with csv_path.open(encoding="utf-8-sig") as fh:
        reader = list(csv.reader(fh))
    assert reader[0] == ALL_HEADERS
    assert len(reader) == len(rows) + 1
