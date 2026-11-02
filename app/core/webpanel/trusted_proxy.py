"""Доверенные адреса прокси веб-панели.

Заголовки ``CF-Connecting-IP`` и ``X-Forwarded-For`` доверяем только если
соединение пришло с диапазона Cloudflare. Иначе порт панели, открытый
напрямую, позволяет подделать IP и обойти бан сканера.

Диапазоны публичные: https://www.cloudflare.com/ips-v4 и ips-v6.
Меняются редко; обновлять вручную.
"""

from __future__ import annotations

import ipaddress
from collections.abc import Iterable

CLOUDFLARE_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = tuple(
    ipaddress.ip_network(net)
    for net in (
        "173.245.48.0/20",
        "103.21.244.0/22",
        "103.22.200.0/22",
        "103.31.4.0/22",
        "141.101.64.0/18",
        "108.162.192.0/18",
        "190.93.240.0/20",
        "188.114.96.0/20",
        "197.234.240.0/22",
        "198.41.128.0/17",
        "162.158.0.0/15",
        "104.16.0.0/13",
        "104.24.0.0/14",
        "172.64.0.0/13",
        "131.0.72.0/22",
        "2400:cb00::/32",
        "2606:4700::/32",
        "2803:f800::/32",
        "2405:b500::/32",
        "2405:8100::/32",
        "2a06:98c0::/29",
        "2c0f:f248::/32",
    )
)


def is_trusted_peer(
    address: str | None,
    networks: Iterable[ipaddress.IPv4Network | ipaddress.IPv6Network],
) -> bool:
    """True, если адрес соединения входит в один из доверенных диапазонов."""
    if not address:
        return False
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return any(ip in network for network in networks)
