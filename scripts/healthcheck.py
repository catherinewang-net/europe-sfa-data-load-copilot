#!/usr/bin/env python3
"""Container health probe for Azure Container Apps / Docker."""

from __future__ import annotations

import sys

from services.startup_validation import health_check, validate_startup_metadata


def main() -> int:
    ok, detail = validate_startup_metadata()
    if not ok:
        print(f"UNHEALTHY: {detail}")
        return 1

    healthy, message = health_check()
    if not healthy:
        print(f"UNHEALTHY: {message}")
        return 1

    print(f"HEALTHY: {message}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
