"""
Fetch a web page for indexing — safely.

Because the server makes the request on behalf of a user, this module is
careful about SSRF (server-side request forgery):

  * only http(s) on the standard ports, no embedded credentials
  * every hostname is resolved first and ALL addresses must be public
    (no localhost, private ranges, link-local / cloud-metadata, etc.)
  * the connection is pinned to the address that was validated, so DNS
    can't change between the check and the request (DNS rebinding)
  * redirects are followed manually and each hop is re-validated
  * the response is size- and time-limited
"""

import ipaddress
import re
import socket
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import httpx
from fastapi import HTTPException

from config import MAX_URL_BYTES, URL_FETCH_USER_AGENT

MAX_REDIRECTS = 4
REQUEST_TIMEOUT = httpx.Timeout(15.0, connect=8.0)
_ALLOWED_PORTS = {80, 443}


@dataclass
class FetchedPage:
    kind: str            # "html" | "text" | "pdf"
    data: bytes
    final_url: str
    content_type: str


def _reject(detail: str, status: int = 400) -> HTTPException:
    return HTTPException(status_code=status, detail=detail)


def is_public_ip(ip: str) -> bool:
    """True only for globally routable addresses."""
    try:
        addr = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
        addr = addr.ipv4_mapped
    return addr.is_global and not (addr.is_multicast or addr.is_unspecified)


def resolve_public_address(host: str, port: int) -> str:
    """
    Resolve *host* and return one address to connect to. Raises HTTP 400 if
    resolution fails or ANY returned address is not public.
    """
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise _reject("Could not resolve that web address.")
    addresses = [info[4][0] for info in infos]
    if not addresses:
        raise _reject("Could not resolve that web address.")
    if not all(is_public_ip(a) for a in addresses):
        raise _reject("That address points to a private or internal network and can't be fetched.")
    return addresses[0]


def validate_url(url: str) -> tuple[str, str, int, str]:
    """Return (scheme, host, port, path_with_query) for a safe-looking URL, else raise 400."""
    url = (url or "").strip()
    if len(url) > 2000:
        raise _reject("That web address is too long.")
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise _reject("Only http:// and https:// addresses are supported.")
    if not parts.hostname:
        raise _reject("That doesn't look like a valid web address.")
    if parts.username or parts.password:
        raise _reject("Web addresses with embedded credentials are not allowed.")
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        raise _reject("That web address has an invalid port.")
    if port not in _ALLOWED_PORTS:
        raise _reject("Only the standard web ports (80 and 443) are allowed.")
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    return parts.scheme, parts.hostname, port, path


def _classify(content_type: str, url_path: str) -> str | None:
    ctype = content_type.split(";")[0].strip().lower()
    if ctype in ("text/html", "application/xhtml+xml"):
        return "html"
    if ctype == "application/pdf":
        return "pdf"
    if ctype in ("text/plain", "text/markdown"):
        return "text"
    if not ctype and url_path.lower().endswith(".pdf"):
        return "pdf"
    return None


def fetch_url(url: str, *, client: httpx.Client | None = None) -> FetchedPage:
    """Download *url* (following validated redirects) and classify the content."""
    own_client = client is None
    http = client or httpx.Client(timeout=REQUEST_TIMEOUT, follow_redirects=False)
    try:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            scheme, host, port, path = validate_url(current)
            ip = resolve_public_address(host, port)
            netloc_ip = f"[{ip}]" if ":" in ip else ip
            default_port = 443 if scheme == "https" else 80
            target = f"{scheme}://{netloc_ip}" + (f":{port}" if port != default_port else "") + path
            host_header = host if port == default_port else f"{host}:{port}"

            try:
                with http.stream(
                    "GET",
                    target,
                    headers={
                        "Host": host_header,
                        "User-Agent": URL_FETCH_USER_AGENT,
                        "Accept-Language": "en;q=0.9,*;q=0.5",
                        "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain;q=0.9",
                    },
                    # Verify the TLS certificate against the real hostname even
                    # though we connect to the pinned IP address.
                    extensions={"sni_hostname": host},
                ) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("location")
                        if not location:
                            raise _reject("The web page redirected without a destination.")
                        current = urljoin(current, location)
                        continue
                    if response.status_code in (401, 403, 429):
                        raise _reject(
                            f"This site doesn't allow automated access (HTTP {response.status_code}). "
                            "Open the page in your browser and use \"Paste text\" (or the DocuQuery browser button) "
                            "to add what you can see, or save it as a PDF and upload that."
                        )
                    if response.status_code >= 400:
                        raise _reject(f"The web page returned an error (HTTP {response.status_code}).")

                    declared = response.headers.get("content-length")
                    if declared and declared.isdigit() and int(declared) > MAX_URL_BYTES:
                        raise _reject("That web page is too large to import.", 413)

                    content_type = response.headers.get("content-type", "")
                    kind = _classify(content_type, path)
                    if kind is None:
                        raise _reject("Only web pages, PDFs and plain-text links can be imported.")

                    chunks: list[bytes] = []
                    total = 0
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > MAX_URL_BYTES:
                            raise _reject("That web page is too large to import.", 413)
                        chunks.append(chunk)
                    return FetchedPage(kind, b"".join(chunks), current, content_type)
            except httpx.TimeoutException:
                raise _reject("The web page took too long to respond.", 504)
            except httpx.HTTPError:
                raise _reject("Could not download that web page.", 502)
        raise _reject("The web page redirected too many times.")
    finally:
        if own_client:
            http.close()


# ── HTML → text ──────────────────────────────────────────────────────

_SKIP_TAGS = {"script", "style", "noscript", "svg", "template", "iframe", "head", "nav", "footer", "aside", "form"}
_BLOCK_TAGS = {
    "p", "div", "section", "article", "main", "li", "ul", "ol", "tr", "table", "blockquote",
    "h1", "h2", "h3", "h4", "h5", "h6", "pre", "br", "hr", "figcaption", "dd", "dt",
}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.paragraphs: list[str] = []
        self._buf: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def _flush(self) -> None:
        text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
        if text:
            self.paragraphs.append(text)
        self._buf = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "title":
            self._in_title = True
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in _BLOCK_TAGS:
            self._flush()

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
            return
        if self._skip_depth == 0:
            self._buf.append(data)

    def close(self) -> None:
        super().close()
        self._flush()


def html_to_text(html: str) -> tuple[str, list[str]]:
    """Return (title, paragraphs) extracted from an HTML document."""
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:
        pass  # malformed markup: keep whatever was extracted so far
    title = re.sub(r"\s+", " ", parser.title).strip()
    # Drop tiny fragments (menu labels, buttons) that add noise, but keep short headings.
    paragraphs = [p for p in parser.paragraphs if len(p) >= 3]
    return title, paragraphs


def decode_html(data: bytes, content_type: str) -> str:
    match = re.search(r"charset=([\w\-]+)", content_type, re.IGNORECASE)
    candidates = [match.group(1)] if match else []
    head = data[:2048].decode("ascii", errors="ignore")
    meta = re.search(r"<meta[^>]+charset=[\"']?([\w\-]+)", head, re.IGNORECASE)
    if meta:
        candidates.append(meta.group(1))
    candidates.append("utf-8")
    for encoding in candidates:
        try:
            return data.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", errors="replace")


def display_name_for_url(url: str, title: str) -> str:
    """Build a readable, unique-ish document name for a web source."""
    parts = urlsplit(url)
    host = (parts.hostname or "web").removeprefix("www.")
    base = title.strip() or (host + (parts.path.rstrip("/") or ""))
    base = re.sub(r"[\\/\x00-\x1f\x7f]+", " ", base)
    base = re.sub(r"\s+", " ", base).strip()[:90]
    if host.lower() not in base.lower():
        base = f"{base} ({host})"
    return base
