"""Bounded public-document reader for research, with pinned public DNS targets."""
from __future__ import annotations

import ipaddress
import socket
import re
from time import monotonic
from urllib.parse import urljoin, urlsplit

import certifi
import urllib3
from bs4 import BeautifulSoup


def public_target(url: str) -> tuple[str, str]:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Only public HTTPS documents are permitted")
    if parsed.port not in (None, 443):
        raise ValueError("Nonstandard document port")
    host = parsed.hostname.encode("idna").decode("ascii")
    addresses = {item[4][0] for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
    if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
        raise ValueError("Document host must resolve only to public addresses")
    return host, sorted(addresses)[0]


def document_excerpt(text: str, query: str, limit: int = 14000) -> str:
    if len(text) <= limit or not query:
        return text[:limit]
    terms = list(dict.fromkeys(re.findall(r"[a-zA-Z]{3,}", query.lower())))[:12]
    chunks = [(index, text[index:index + 1800]) for index in range(0, len(text), 1500)]
    ranked = sorted(chunks, key=lambda item: sum(len(re.findall(r"\b" + re.escape(term) + r"\b", item[1], re.I)) for term in terms), reverse=True)
    chosen = sorted(ranked[:7])
    return "\n[... excerpt ...]\n".join(chunk for _, chunk in chosen)[:limit]


def read_public_document(url: str, *, timeout: float = 8.0, max_bytes: int = 5_000_000, query: str = "") -> dict:
    deadline = monotonic() + timeout
    for _ in range(3):
        host, address = public_target(url)
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("Document deadline exceeded")
        parsed = urlsplit(url)
        pool = urllib3.HTTPSConnectionPool(
            address, port=443, server_hostname=host, assert_hostname=host,
            cert_reqs="CERT_REQUIRED", ca_certs=certifi.where(),
            timeout=urllib3.Timeout(connect=min(3, remaining), read=remaining),
        )
        response = None
        try:
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            response = pool.request("GET", path, headers={"Host": host,
                "User-Agent": "QuantDinger Research support@quantdinger.com"},
                redirect=False, retries=False, preload_content=False)
            if response.status in {301, 302, 303, 307, 308}:
                url = urljoin(url, response.headers.get("Location", ""))
                continue
            if response.status != 200:
                raise ValueError(f"Document HTTP {response.status}")
            content_type = response.headers.get("Content-Type", "").lower()
            if not any(kind in content_type for kind in ("text/", "json", "xml")):
                raise ValueError("Unsupported document content type")
            body = response.read(max_bytes + 1, decode_content=True)
            if len(body) > max_bytes:
                raise ValueError("Document exceeds size limit")
            soup = BeautifulSoup(body, "html.parser")
            title = soup.title.get_text(" ", strip=True) if soup.title else host
            for node in soup.select('[hidden], [aria-hidden="true"], [style]'):
                if node.attrs is not None and (node.has_attr("hidden") or node.get("aria-hidden") == "true"
                        or re.search(r"display\s*:\s*none", node.get("style", ""), re.I)):
                    node.decompose()
            for node in soup.find_all(lambda tag: tag.name in {"ix:header", "ix:hidden", "xbrli:context", "xbrli:unit"}):
                node.decompose()
            for node in soup(["script", "style", "nav", "footer", "header", "noscript"]):
                node.decompose()
            links = []
            for anchor in soup.select("a[href]"):
                target = urljoin(url, anchor.get("href", ""))
                if target.startswith("https://") and not target.startswith(url + "#"):
                    links.append({"title": anchor.get_text(" ", strip=True)[:100], "url": target})
                if len(links) >= 30:
                    break
            text = soup.get_text(" ", strip=True)
            return {"url": url, "title": title[:200], "text": document_excerpt(text, query), "links": links,
                    "truncated": len(text) > 14000, "evidence_kind": "document_excerpt"}
        finally:
            if response is not None:
                response.close()
            pool.close()
    raise ValueError("Document redirect limit exceeded")
