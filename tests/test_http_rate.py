"""SEC asks for under 10 requests per second across all its hosts, so they must share one limiter."""

from ghost import http


def test_sec_hosts_share_one_rate_limit():
    assert http._rate_key("efts.sec.gov") == http._rate_key("www.sec.gov") == "sec.gov"
    assert http.RATE_LIMITS["sec.gov"] < 10


def test_other_hosts_keep_their_own_limit():
    assert http._rate_key("clinicaltrials.gov") == "clinicaltrials.gov"
    assert http._rate_key("notsec.gov.example.com") == "notsec.gov.example.com"
