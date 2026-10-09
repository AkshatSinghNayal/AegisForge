"""Pure execution-time IP policy; deny overrides allow."""

from ipaddress import ip_address, ip_network


def network_allowed(address: str, allow: list[str], deny: list[str]) -> bool:
    ip = ip_address(address)
    return not any(ip in ip_network(n) for n in deny) and (
        not allow or any(ip in ip_network(n) for n in allow)
    )
