#!/usr/bin/env python3
"""Production smoke check for Skillvaya's public, customer, owner and WorkFinder shells.

This is intentionally read-only: it sends GET requests only and never signs in,
creates accounts, writes data, or calls payment endpoints.
"""
from __future__ import annotations

import os
import sys
import time
import urllib.error
import urllib.request

BASE_URL = os.environ.get("SKILLVAYA_SMOKE_BASE_URL", "https://skillvaya.onrender.com").rstrip("/")
ATTEMPTS = int(os.environ.get("SKILLVAYA_SMOKE_ATTEMPTS", "1"))
RETRY_SECONDS = float(os.environ.get("SKILLVAYA_SMOKE_RETRY_SECONDS", "10"))

ROUTES = {
    "/": ("Good people.",),
    "/customer-app": ("Find the perfect service", "nav-customer"),
    "/owner-app": ('id="loginScreen"', 'id="appShell"', "ownerLoginForm"),
    "/workfinder": ("SkillVaya WorkFinder", 'id="content"', "function render()"),
}


def check_route(path: str, markers: tuple[str, ...]) -> list[str]:
    url = BASE_URL + path
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Skillvaya-Production-Smoke/1.0", "Cache-Control": "no-cache"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            status = response.status
            content_type = response.headers.get("Content-Type", "")
            body = response.read(5_000_001)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return [f"{path}: request failed: {exc}"]

    errors: list[str] = []
    if status != 200:
        errors.append(f"{path}: expected HTTP 200, received {status}")
    if "text/html" not in content_type.lower():
        errors.append(f"{path}: expected HTML, received Content-Type {content_type!r}")
    if len(body) < 1_000:
        errors.append(f"{path}: response is suspiciously small ({len(body)} bytes), possible blank/error page")
    if len(body) > 5_000_000:
        errors.append(f"{path}: response exceeded the 5 MB safety limit")

    text = body.decode("utf-8", errors="replace")
    for marker in markers:
        if marker.casefold() not in text.casefold():
            errors.append(f"{path}: expected screen marker not found: {marker!r}")
    for bad in ("Application error", "Internal Server Error"):
        if bad.casefold() in text.casefold():
            errors.append(f"{path}: error-page text detected: {bad!r}")
    if not errors:
        print(f"PASS {path}: HTTP {status}, {len(body)} bytes, expected screen markers present")
    return errors


def run_once() -> list[str]:
    errors: list[str] = []
    for path, markers in ROUTES.items():
        errors.extend(check_route(path, markers))
    return errors


def main() -> int:
    if ATTEMPTS < 1 or ATTEMPTS > 20:
        print("SKILLVAYA_SMOKE_ATTEMPTS must be between 1 and 20", file=sys.stderr)
        return 2
    for attempt in range(1, ATTEMPTS + 1):
        print(f"Skillvaya production screen smoke check: {BASE_URL} (attempt {attempt}/{ATTEMPTS})")
        errors = run_once()
        if not errors:
            print("All production screen routes passed.")
            return 0
        for error in errors:
            print(f"FAIL {error}", file=sys.stderr)
        if attempt < ATTEMPTS:
            print(f"Retrying in {RETRY_SECONDS:g} seconds...")
            time.sleep(RETRY_SECONDS)
    print("Production smoke check failed. Investigate before treating the release as healthy.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())


