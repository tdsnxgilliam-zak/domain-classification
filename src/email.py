"""Email-dependency assessment (spec FR-6 / 5.4, task T8).

Combines DNS mail records (MX / SPF / DMARC / DKIM) with on-page mail forms into
a single ``email_functionality`` signal.

Note: this module lives inside the ``src`` package; absolute ``import email``
elsewhere still resolves to the standard library.
"""

from __future__ import annotations

from .models import ContentResult, DnsResult, EmailResult


def assess(dns_result: DnsResult, content_result: ContentResult | None = None) -> EmailResult:
    """Produce an EmailResult and the ``email_functionality`` value (spec 5.4).

    - ``Yes`` if has_mx OR (has_spf AND has_dmarc) OR a mail form is present.
    - ``No`` if the domain resolves and none of the above.
    - ``Unknown`` if DNS checks failed.
    """
    result = EmailResult()

    if dns_result is None:
        result.email_functionality = "Unknown"
        return result

    result.has_mx = bool(dns_result.mx)
    result.has_spf = bool(dns_result.spf)
    result.has_dmarc = bool(dns_result.dmarc)
    result.has_dkim = bool(dns_result.dkim_selectors)
    result.has_mail_form = bool(content_result and content_result.has_mail_form)

    # DNS could not be completed at all -> Unknown. Only a true timeout is
    # treated as a failed check; NXDOMAIN / NoNameservers / NoAnswer are
    # definitive answers meaning "no working mail here".
    dns_failed = (not dns_result.resolves) and dns_result.error == "Timeout" \
        and not dns_result.mx

    has_mail_signal = (
        result.has_mx
        or (result.has_spf and result.has_dmarc)
        or result.has_mail_form
    )

    if has_mail_signal:
        result.email_functionality = "Yes"
    elif dns_result.resolves or dns_result.error == "NXDOMAIN":
        result.email_functionality = "No"
    elif dns_failed:
        result.email_functionality = "Unknown"
    else:
        result.email_functionality = "No"

    return result
