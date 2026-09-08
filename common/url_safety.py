"""Shared SSRF-defense helpers for any code that fetches a URL taken
from data that ultimately traces back to something a remote server or
a user supplied, rather than a URL this project's own code constructed
entirely from a trusted, fixed source.
"""
from __future__ import annotations

import ipaddress
from typing import Iterable, Optional
from urllib.parse import urlparse

_LOCALHOST_NAMES = {"localhost", "localhost.localdomain"}


def is_safe_external_url(url: str, *, allowed_hosts: Optional[Iterable[str]] = None,
                          require_https: bool = False) -> bool:
    """True if `url` is reasonably safe to actually fetch server-side.

    Always blocks non-http(s) schemes and the literal hostnames
    "localhost"/"localhost.localdomain" (a hostname, not a literal IP,
    so an IP-address check alone wouldn't catch it).

    If `allowed_hosts` is given, the hostname must ALSO exactly match
    one of them (case-insensitive, and exact only, never a suffix or
    substring check, "cdn.example.com.evil.com" must never pass an
    allowlist of "cdn.example.com"), for callers proxying or fetching
    on behalf of a public, unauthenticated endpoint, where "any
    external host except obviously-internal ones" isn't a tight enough
    bound and a fixed allowlist of known-good hosts is required
    instead. Without an allowlist, falls back to blocking literal
    private/loopback/link-local/reserved/multicast IP addresses, the
    right default for callers fetching a URL that could legitimately
    point at any external host (e.g. an attachment link from a message
    payload) rather than one of a small known set.

    Does NOT protect against DNS rebinding (the hostname resolving to
    a different, unsafe IP between this check and the actual request
    reaching it) or a redirect from an allowed host to an unsafe one.
    Callers that need those closed too should ALSO disable redirect-
    following at the request level (this is required, not optional,
    when using allowed_hosts: an allowlisted host issuing a redirect
    is exactly the gap a hostname-string check alone can't close) and,
    where the risk profile warrants it, resolve and check the IP at
    connect time rather than trusting the hostname string alone. This
    is a proportionate floor, not a complete SSRF defense, appropriate
    given the realistic alternative was no check at all."""
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    allowed_schemes = ("https",) if require_https else ("http", "https")
    if parsed.scheme not in allowed_schemes:
        return False
    host = parsed.hostname
    if not host:
        return False
    host = host.lower()
    if host in _LOCALHOST_NAMES:
        return False
    if allowed_hosts is not None:
        return host in {h.lower() for h in allowed_hosts}
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True  # a real hostname, not a literal IP, allowed in this (non-allowlisted) mode
    return not (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast)
