#!/usr/bin/env python3
"""Local Linux runner entry point; production CLI stays HTTPS-only."""

import sys

import aegisforge_ci as ci

_https_origin = ci.origin


def local_origin(value):
    # Exact literals: no DNS, arbitrary ports, URL credentials or redirects.
    if value in {"http://127.0.0.1:8000", "http://127.0.0.1:5173"}:
        return value
    return _https_origin(value)


def main():
    ci.origin = local_origin
    try:
        return ci.main()
    finally:
        ci.origin = _https_origin


if __name__ == "__main__":
    sys.exit(main())
