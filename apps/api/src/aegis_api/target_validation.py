"""Bounded validation. Revalidate at execution; saved DNS is not authority."""

import asyncio
import ipaddress
import json
import re
import socket
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import aiohttp
import yaml
from aiohttp.abc import AbstractResolver, ResolveResult
from openapi_spec_validator import validate
from yaml.tokens import AliasToken, AnchorToken, TagToken

from aegis_api.conventions import APIError

MAX_SPEC = 1024 * 1024
PRIVATE = tuple(
    ipaddress.ip_network(x)
    for x in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "fc00::/7")
)


def invalid(message: str) -> APIError:
    return APIError(422, "invalid_target", message)


def canonical_url(value: str) -> str:
    try:
        if len(value) > 2048 or re.search(r"[\s\\\x00-\x1f\x7f]", value):
            raise ValueError
        parts = urlsplit(value)
        host = parts.hostname
        if (
            parts.scheme not in {"http", "https"}
            or not host
            or parts.username is not None
            or parts.password is not None
            or parts.query
            or parts.fragment
            or "%" in host
        ):
            raise ValueError
        host = host.encode("idna").decode("ascii").lower().rstrip(".")
        try:
            address = ipaddress.ip_address(host)
            host = f"[{address}]" if address.version == 6 else str(address)
        except ValueError:
            if not re.fullmatch(r"(?=.{1,253}$)[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", host):
                raise ValueError from None
            if any(
                not part or len(part) > 63 or part.startswith("-") or part.endswith("-")
                for part in host.split(".")
            ):
                raise ValueError from None
        port = parts.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError
        authority = host + (
            f":{port}"
            if port and port != (443 if parts.scheme == "https" else 80)
            else ""
        )
        return urlunsplit((parts.scheme, authority, parts.path or "/", "", ""))
    except (ValueError, UnicodeError):
        raise invalid(
            "Use an HTTP(S) URL without credentials, query strings or fragments."
        ) from None


def permitted_ip(value: str, allow_private: bool = False) -> bool:
    address = ipaddress.ip_address(value)
    # Mapped/transition addresses must not tunnel around the IPv4 policy.
    if isinstance(address, ipaddress.IPv6Address) and (
        address.is_site_local
        or address.ipv4_mapped
        or address.sixtofour
        or address.teredo
        or address in ipaddress.ip_network("64:ff9b::/96")
        or address in ipaddress.ip_network("64:ff9b:1::/48")
    ):
        return False
    if (
        address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_unspecified
        or address.is_reserved
    ):
        return False
    # Azure platform virtual IP is globally classified but is infrastructure.
    if str(address) in {"168.63.129.16", "fd00:ec2::254"}:
        return False
    return address.is_global or (
        allow_private and any(address in block for block in PRIVATE)
    )


async def resolve(host: str, port: int, allow_private: bool) -> list[str]:
    try:
        rows = await asyncio.get_running_loop().getaddrinfo(
            host, port, type=socket.SOCK_STREAM
        )
        addresses = sorted({str(row[4][0]) for row in rows})
        if not addresses or not all(
            permitted_ip(ip, allow_private) for ip in addresses
        ):
            raise invalid("The target resolves to a blocked network address.")
        return addresses
    except (OSError, ValueError):
        raise invalid("Target DNS resolution failed.") from None


class PinnedResolver(AbstractResolver):
    def __init__(self, host: str, addresses: list[str]):
        self.host, self.addresses = host, addresses

    async def resolve(
        self, host: str, port: int = 0, family: int = socket.AF_INET
    ) -> list[ResolveResult]:
        if host != self.host:
            raise invalid("Unexpected destination host.")
        return [
            ResolveResult(
                hostname=host,
                host=ip,
                port=port,
                family=socket.AF_INET6 if ":" in ip else socket.AF_INET,
                proto=socket.IPPROTO_TCP,
                flags=socket.AI_NUMERICHOST,
            )
            for ip in self.addresses
        ]

    async def close(self) -> None:
        pass


async def probe_url(
    url: str, allow_private: bool = False, fetch_spec: bool = False
) -> tuple[str, int, bytes]:
    """Every hop gets fresh DNS checks, a pinned connection and TLS verification."""
    try:
        async with asyncio.timeout(15):
            for _ in range(6):
                url = canonical_url(url)
                parts = urlsplit(url)
                assert parts.hostname
                addresses = await resolve(
                    parts.hostname,
                    parts.port or (443 if parts.scheme == "https" else 80),
                    allow_private,
                )
                connector = aiohttp.TCPConnector(
                    resolver=PinnedResolver(parts.hostname, addresses),
                    use_dns_cache=False,
                    force_close=True,
                )
                async with aiohttp.ClientSession(
                    connector=connector,
                    trust_env=False,
                    cookie_jar=aiohttp.DummyCookieJar(),
                    auto_decompress=False,
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as client:
                    async with client.get(
                        url,
                        allow_redirects=False,
                        headers={"Accept-Encoding": "identity"},
                    ) as response:
                        if response.status in {301, 302, 303, 307, 308}:
                            location = response.headers.get("Location")
                            if not location:
                                raise invalid("Redirect has no destination.")
                            next_url = canonical_url(urljoin(url, location))
                            if (
                                parts.scheme == "https"
                                and urlsplit(next_url).scheme != "https"
                            ):
                                raise invalid("HTTPS downgrade redirects are blocked.")
                            url = next_url
                            continue
                        if response.status >= 500:
                            raise invalid("The target returned a server error.")
                        data = b""
                        if fetch_spec:
                            if (
                                response.status != 200
                                or response.headers.get("Content-Encoding", "identity")
                                != "identity"
                            ):
                                raise invalid(
                                    "OpenAPI URL must return an uncompressed "
                                    "document with HTTP 200."
                                )
                            if response.content_type not in {
                                "application/json",
                                "application/yaml",
                                "application/x-yaml",
                                "text/yaml",
                                "text/x-yaml",
                                "text/plain",
                                "application/vnd.oai.openapi+json",
                                "application/vnd.oai.openapi",
                            }:
                                raise invalid(
                                    "OpenAPI URL returned an unsupported content type."
                                )
                            async for chunk in response.content.iter_chunked(16384):
                                data += chunk
                                if len(data) > MAX_SPEC:
                                    raise invalid(
                                        "OpenAPI documents must be at most 1 MiB."
                                    )
                        return url, response.status, data
            raise invalid("Too many redirects.")
    except (TimeoutError, aiohttp.ClientError, OSError):
        raise invalid("Target is unreachable or TLS validation failed.") from None


def sanitize_openapi(content: bytes, filename: str) -> dict[str, Any]:
    if len(content) > MAX_SPEC:
        raise invalid("OpenAPI documents must be at most 1 MiB.")
    if not filename.lower().endswith((".json", ".yaml", ".yml")):
        raise invalid("Upload a JSON or YAML OpenAPI document.")
    try:
        text = content.decode("utf-8")
        # Reject aliases/tags and bound depth before parser recursion.
        depth = 0
        for token in yaml.scan(text):
            if isinstance(token, (AliasToken, AnchorToken, TagToken)):
                raise ValueError
            if token.__class__.__name__ in {
                "FlowMappingStartToken",
                "FlowSequenceStartToken",
                "BlockMappingStartToken",
                "BlockSequenceStartToken",
            }:
                depth += 1
                if depth > 40:
                    raise ValueError
            if token.__class__.__name__ in {
                "FlowMappingEndToken",
                "FlowSequenceEndToken",
                "BlockEndToken",
            }:
                depth -= 1
        doc = (
            json.loads(text)
            if filename.lower().endswith(".json")
            else yaml.safe_load(text)
        )
        if not isinstance(doc, dict) or not (
            doc.get("swagger") == "2.0"
            or re.fullmatch(r"3\.(0|1)\.\d+", str(doc.get("openapi", "")))
        ):
            raise ValueError
        named_maps = {
            "properties",
            "patternProperties",
            "$defs",
            "definitions",
            "schemas",
            "paths",
            "webhooks",
            "responses",
            "headers",
            "securitySchemes",
            "securityDefinitions",
            "content",
            "encoding",
            "links",
            "callbacks",
            "mapping",
            "scopes",
        }
        remove = {
            "example",
            "examples",
            "default",
            "enum",
            "const",
            "summary",
            "externalDocs",
            "contact",
            "license",
            "servers",
            "host",
            "basePath",
            "schemes",
        }
        nodes = 0

        def walk(
            value: Any,
            level: int = 0,
            named: bool = False,
            sanitize: bool = False,
            parent: str = "",
        ) -> Any:
            nonlocal nodes
            nodes += 1
            if nodes > 30000 or level > 40:
                raise ValueError
            if isinstance(value, dict):
                if any(not isinstance(k, str) for k in value):
                    raise ValueError
                if not named:
                    if any(
                        k in value
                        for k in ("$id", "$schema", "$dynamicRef", "$recursiveRef")
                    ):
                        raise ValueError
                    if "$ref" in value and (
                        not isinstance(value["$ref"], str)
                        or not value["$ref"].startswith("#/")
                    ):
                        raise ValueError
                result = {}
                for k, v in value.items():
                    if sanitize and not named:
                        if k in remove or k.lower().startswith("x-"):
                            continue
                        if k == "description":
                            result[k] = "Sanitized description"
                            continue
                    # Map keys are API names, not OpenAPI keywords. Components
                    # parameters/requestBodies are maps; operation parameters are lists.
                    child_named = not named and (
                        k in named_maps
                        or (k == "parameters" and isinstance(v, dict))
                        or (
                            parent == "components"
                            and level == 1
                            and isinstance(v, dict)
                        )
                    )
                    result[k] = walk(v, level + 1, child_named, sanitize, k)
                return result
            if isinstance(value, list):
                return [
                    walk(v, level + 1, parent == "security", sanitize) for v in value
                ]
            if value is not None and not isinstance(value, (str, int, float, bool)):
                raise ValueError
            return value

        # Check all original content before handing anything to a validator that
        # could resolve references. Invalid input cannot become valid by redaction.
        walk(doc)
        validate(doc)
        nodes = 0
        sanitized: dict[str, Any] = walk(doc, sanitize=True)
        validate(sanitized)
        # The target URL is the only authority. Spec servers are removed, not fetched.
        return sanitized
    except Exception:
        raise invalid(
            "Invalid OpenAPI 2.0/3.0/3.1 document; external references, "
            "aliases and excessive nesting are not accepted."
        ) from None
