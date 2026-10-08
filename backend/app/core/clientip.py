import ipaddress
from functools import lru_cache

from starlette.requests import Request


@lru_cache(maxsize=16)
def _networks(trusted: tuple[str, ...]) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
    return tuple(ipaddress.ip_network(n, strict=False) for n in trusted)


def client_ip(request: Request, trusted_proxies: list[str]) -> str:
    """Client IP; X-Forwarded-For is honoured only when the direct peer is a trusted proxy."""
    peer = request.client.host if request.client else "unknown"
    try:
        peer_addr = ipaddress.ip_address(peer)
    except ValueError:
        return peer
    if not any(peer_addr in net for net in _networks(tuple(trusted_proxies))):
        return peer
    forwarded = request.headers.get("x-forwarded-for", "")
    # The right-most entry is the one appended by our own (trusted) proxy.
    candidate = forwarded.split(",")[-1].strip() if forwarded else ""
    try:
        return str(ipaddress.ip_address(candidate))
    except ValueError:
        return peer
