#!/usr/bin/env python3
"""Create an A2A task and print its first non-working status."""

from __future__ import annotations

import argparse
import os
import time
import uuid

from a2a_test_client import (
    A2AClient,
    A2ARequestError,
    DEFAULT_POLL_INTERVAL,
    print_json,
    task_from_response,
    task_phase,
    task_state,
)

WORKING_STATES = {"TASK_STATE_SUBMITTED", "TASK_STATE_WORKING"}
FAILED_STATES = {
    "TASK_STATE_FAILED",
    "TASK_STATE_REJECTED",
    "TASK_STATE_CANCELED",
}


def wait_for_status(
    client: A2AClient, task_id: str, timeout: float, interval: float
) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        time.sleep(interval)
        response = client.get_task(task_id)
        print_json(response)
        task = task_from_response(response)
        state, phase = task_state(task), task_phase(task)
        print(f"STATUS: {state}/{phase}")
        if state not in WORKING_STATES:
            return task
    raise TimeoutError(f"timeout waiting for task {task_id}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("A2A_ROUTER_PUBLIC_URL", "http://127.0.0.1:19000/"),
    )
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--timeout", type=float, default=300)
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=DEFAULT_POLL_INTERVAL,
        help=f"seconds between status requests (default: {DEFAULT_POLL_INTERVAL:g})",
    )
    parser.add_argument(
        "--approve",
        action="store_true",
        help="approve a ready plan and wait for task completion",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="with --approve, skip the interactive RUN confirmation",
    )
    args = parser.parse_args()
    if args.poll_interval <= 0:
        parser.error("--poll-interval must be greater than zero")

    suffix = uuid.uuid4().hex
    experiment_id = f"smoke-{suffix}"
    context_id = f"ctx-{experiment_id}"
    client = A2AClient(args.base_url)
    try:
        response = client.send_message(
            text=args.prompt,
            experiment_id=experiment_id,
            context_id=context_id,
            message_id=f"message-{suffix}",
        )
        print_json(response)
        task = task_from_response(response)
        task_id = str(task["id"])
        task = wait_for_status(client, task_id, args.timeout, args.poll_interval)
        state, phase = task_state(task), task_phase(task)
        print(f"Task ID: {task_id}")
        if not args.approve:
            return 0
        if state != "TASK_STATE_INPUT_REQUIRED" or phase != "approval":
            print(f"STOP: task is not ready for approval: {state}/{phase}")
            return 1 if state in FAILED_STATES else 2
        if not args.yes and input("Type RUN to approve this task: ").strip() != "RUN":
            print("Approval canceled by operator")
            return 0
        try:
            response = client.send_message(
                text="Approve",
                experiment_id=experiment_id,
                context_id=context_id,
                message_id=f"approve-{uuid.uuid4().hex}",
                task_id=task_id,
            )
            print_json(response)
        except A2ARequestError as exc:
            print(f"WARNING: approval request returned {exc}; polling task status")
        task = wait_for_status(client, task_id, args.timeout, args.poll_interval)
        state, phase = task_state(task), task_phase(task)
        if state == "TASK_STATE_COMPLETED":
            print("PASS: task completed")
            return 0
        print(f"STOP: task ended or paused at {state}/{phase}")
        return 1 if state in FAILED_STATES else 2
    except (A2ARequestError, KeyError, TimeoutError) as exc:
        print(f"FAIL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
