"""
URL import is the riskiest feature (the server makes requests for users),
so the SSRF protections get thorough tests.
"""

import httpx
import pytest
from fastapi import HTTPException

from services import url_fetch


def dns(mapping):
    """Fake socket.getaddrinfo from {hostname: [ip, ...]}."""

    def fake(host, port, type=0, **kwargs):
        if host not in mapping:
            import socket
            raise socket.gaierror("unknown host")
        return [(2, 1, 6, "", (ip, port)) for ip in mapping[host]]

    return fake


@pytest.fixture
def public_dns(monkeypatch):
    monkeypatch.setattr(
        url_fetch.socket,
        "getaddrinfo",
        dns({"example.com": ["93.184.216.34"], "evil.test": ["10.0.0.5"], "mixed.test": ["93.184.216.34", "127.0.0.1"]}),
    )


# ── IP classification ────────────────────────────────────────────────

@pytest.mark.parametrize("ip", ["93.184.216.34", "8.8.8.8", "2606:4700:4700::1111"])
def test_public_addresses_are_allowed(ip):
    assert url_fetch.is_public_ip(ip)


@pytest.mark.parametrize(
    "ip",
    [
        "127.0.0.1", "10.1.2.3", "172.16.0.1", "192.168.1.1", "169.254.169.254",  # cloud metadata
        "0.0.0.0", "224.0.0.1", "::1", "fe80::1", "fc00::1", "::ffff:127.0.0.1", "not-an-ip",
    ],
)
def test_internal_addresses_are_blocked(ip):
    assert not url_fetch.is_public_ip(ip)


# ── URL validation ───────────────────────────────────────────────────

@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/x",
        "gopher://example.com",
        "javascript:alert(1)",
        "http://user:pass@example.com/",
        "https://example.com:8080/",
        "http://example.com:22/",
        "http:///nohost",
        "",
        "http://" + "a" * 2100 + ".com",
    ],
)
def test_validate_url_rejects_unsafe_urls(url):
    with pytest.raises(HTTPException) as exc:
        url_fetch.validate_url(url)
    assert exc.value.status_code == 400


def test_validate_url_accepts_normal_urls():
    assert url_fetch.validate_url("https://example.com/a/b?x=1") == ("https", "example.com", 443, "/a/b?x=1")
    assert url_fetch.validate_url("http://example.com") == ("http", "example.com", 80, "/")


def test_resolve_blocks_private_hosts(public_dns):
    with pytest.raises(HTTPException) as exc:
        url_fetch.resolve_public_address("evil.test", 80)
    assert "private" in exc.value.detail.lower()


def test_resolve_blocks_hosts_with_any_private_address(public_dns):
    with pytest.raises(HTTPException):
        url_fetch.resolve_public_address("mixed.test", 80)


def test_resolve_reports_unknown_hosts(public_dns):
    with pytest.raises(HTTPException) as exc:
        url_fetch.resolve_public_address("nope.invalid", 80)
    assert "resolve" in exc.value.detail.lower()


# ── fetching ─────────────────────────────────────────────────────────

def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def test_fetch_connects_to_the_validated_ip_with_the_real_host_header(public_dns):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["host"] = request.headers["host"]
        seen["sni"] = request.extensions.get("sni_hostname")
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, content=b"<p>hi</p>")

    page = url_fetch.fetch_url("https://example.com/page", client=client_for(handler))
    assert page.kind == "html" and page.data == b"<p>hi</p>"
    assert seen["url"].startswith("https://93.184.216.34/")   # pinned: no second DNS lookup
    assert seen["host"] == "example.com"
    assert seen["sni"] == "example.com"


def test_fetch_follows_redirects_and_revalidates_each_hop(public_dns):
    def handler(request):
        if request.headers["host"] == "example.com":
            return httpx.Response(302, headers={"location": "http://evil.test/internal"})
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"secret")

    with pytest.raises(HTTPException) as exc:
        url_fetch.fetch_url("http://example.com/", client=client_for(handler))
    assert "private" in exc.value.detail.lower()


def test_fetch_follows_safe_relative_redirects(public_dns):
    def handler(request):
        if request.url.path == "/old":
            return httpx.Response(301, headers={"location": "/new"})
        return httpx.Response(200, headers={"content-type": "text/plain"}, content=b"arrived")

    page = url_fetch.fetch_url("http://example.com/old", client=client_for(handler))
    assert page.data == b"arrived" and page.kind == "text"


def test_fetch_stops_redirect_loops(public_dns):
    def handler(request):
        return httpx.Response(302, headers={"location": "http://example.com/again"})

    with pytest.raises(HTTPException) as exc:
        url_fetch.fetch_url("http://example.com/", client=client_for(handler))
    assert "redirect" in exc.value.detail.lower()


def test_fetch_rejects_unsupported_content_types(public_dns):
    def handler(request):
        return httpx.Response(200, headers={"content-type": "application/zip"}, content=b"PK")

    with pytest.raises(HTTPException):
        url_fetch.fetch_url("http://example.com/x.zip", client=client_for(handler))


def test_fetch_enforces_size_limit_while_streaming(public_dns, monkeypatch):
    monkeypatch.setattr(url_fetch, "MAX_URL_BYTES", 1000)

    def handler(request):
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"x" * 5000)

    with pytest.raises(HTTPException) as exc:
        url_fetch.fetch_url("http://example.com/", client=client_for(handler))
    assert exc.value.status_code == 413


def test_fetch_maps_http_errors(public_dns):
    def handler(request):
        return httpx.Response(404, content=b"nope")

    with pytest.raises(HTTPException) as exc:
        url_fetch.fetch_url("http://example.com/missing", client=client_for(handler))
    assert "404" in exc.value.detail


def test_fetch_detects_pdf_by_content_type(public_dns):
    def handler(request):
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"%PDF-1.4")

    assert url_fetch.fetch_url("http://example.com/doc", client=client_for(handler)).kind == "pdf"


# ── HTML → text ──────────────────────────────────────────────────────

HTML = """
<html><head><title>My  Page</title><style>body{color:red}</style></head>
<body>
  <nav>Home | About | Contact</nav>
  <h1>Main heading</h1>
  <p>First paragraph with <b>bold</b> text &amp; an entity.</p>
  <script>var secret = "do not index";</script>
  <ul><li>Item one</li><li>Item two</li></ul>
  <footer>Copyright junk</footer>
</body></html>
"""


def test_html_to_text_extracts_content_and_skips_boilerplate():
    title, paragraphs = url_fetch.html_to_text(HTML)
    assert title == "My Page"
    joined = " ".join(paragraphs)
    assert "Main heading" in joined
    assert "First paragraph with bold text & an entity." in paragraphs
    assert "Item one" in paragraphs and "Item two" in paragraphs
    for junk in ("do not index", "color:red", "Home | About", "Copyright junk"):
        assert junk not in joined


def test_html_to_text_survives_malformed_markup():
    title, paragraphs = url_fetch.html_to_text("<p>unclosed <b>bold <div>text")
    assert any("text" in p for p in paragraphs)


def test_decode_html_honours_declared_charset():
    data = "café".encode("latin-1")
    assert url_fetch.decode_html(data, "text/html; charset=iso-8859-1") == "café"


def test_decode_html_falls_back_when_charset_is_bogus():
    assert url_fetch.decode_html("café".encode("utf-8"), "text/html; charset=nonsense") == "café"


def test_display_name_uses_title_and_host():
    assert url_fetch.display_name_for_url("https://www.example.com/a/b", "A / Title") == "A Title (example.com)"


def test_display_name_never_contains_slashes():
    name = url_fetch.display_name_for_url("https://example.com/a/b/c", "")
    assert "/" not in name and "\\" not in name and "example.com" in name


def test_fetch_identifies_itself_with_a_descriptive_user_agent(public_dns):
    seen = {}

    def handler(request):
        seen["ua"] = request.headers["user-agent"]
        return httpx.Response(200, headers={"content-type": "text/html"}, content=b"<p>hi</p>")

    url_fetch.fetch_url("http://example.com/", client=client_for(handler))
    assert seen["ua"].startswith("DocuQuery/") and "http" in seen["ua"]  # names the tool and a contact URL


@pytest.mark.parametrize("status", [401, 403, 429])
def test_sites_that_block_bots_get_an_actionable_message(public_dns, status):
    def handler(request):
        return httpx.Response(status, content=b"blocked")

    with pytest.raises(HTTPException) as exc:
        url_fetch.fetch_url("http://example.com/", client=client_for(handler))
    assert exc.value.status_code == 400
    assert str(status) in exc.value.detail and "PDF" in exc.value.detail
