#!/usr/bin/env python3
"""Authorize against LinkedIn OAuth and probe Posts API access.

Usage:
  python3 scripts/linkedin-oauth.py              # open browser, save tokens
  python3 scripts/linkedin-oauth.py --probe      # test Posts API author finder
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from linkedin_api import (  # noqa: E402
    DEFAULT_SCOPES,
    LinkedInApiError,
    authorize_local,
    load_json,
    probe,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="LinkedIn OAuth + API probe for portfolio import")
    parser.add_argument("--probe", action="store_true", help="Test Posts API with saved tokens")
    parser.add_argument(
        "--scopes",
        default=DEFAULT_SCOPES,
        help="OAuth scopes to request (space-separated)",
    )
    args = parser.parse_args()

    config = load_json(ROOT / "scripts" / "linkedin.config.json")
    api_cfg = config.get("api") or {}

    if args.probe:
        return probe(api_cfg)

    try:
        authorize_local(scopes=args.scopes)
    except LinkedInApiError as exc:
        print(f"Auth failed: {exc}", file=sys.stderr)
        return 1
    return probe(api_cfg)


if __name__ == "__main__":
    sys.exit(main())
