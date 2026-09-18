#!/usr/bin/env python3
"""Cross-platform replacement for test-external-a2a.ps1."""

from __future__ import annotations

import argparse
import os

from a2a_test_client import A2AClient, A2ARequestError, print_json


def main() -> int:
    parser = argparse.ArgumentParser(description="Check the public A2A Agent Card")
    parser.add_argument(
        "--base-url",
        default=os.getenv("A2A_ROUTER_PUBLIC_URL", "http://127.0.0.1:19000/"),
    )
    args = parser.parse_args()
    try:
        card = A2AClient(args.base_url, timeout=20).agent_card()
    except A2ARequestError as exc:
        print(f"FAIL: {exc}")
        return 1
    print_json(card)
    interfaces = card.get("supportedInterfaces") or []
    json_rpc = next(
        (
            item
            for item in interfaces
            if isinstance(item, dict) and item.get("protocolBinding") == "JSONRPC"
        ),
        None,
    )
    if not json_rpc or not json_rpc.get("url"):
        print("FAIL: Agent Card does not publish a JSONRPC URL")
        return 1
    print(f"PASS: Agent Card is reachable at {args.base_url}")
    print(f"PASS: Agent Card publishes {json_rpc['url']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
