#!/usr/bin/env python3
"""Plan and optionally execute the current chemists' reactor experiment."""

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

EXPERIMENT_PROMPT = """Подготовь связь с реактором.

Установи температуру преднагревателя 1: 40 °C.
Установи температуру преднагревателя 2: 50 °C.
Выполни установку температуры реакции термостата реактора: 56 °C.
Выполни настройку термостата смесителя: 34 °C.

Выполни настройку холодильника: температура -5 °C, нужно включить его.

Установи рабочее давление БПР: 13 бар.

Выполни запуск подачи реагентов:
для канала 1 — направление 0, скорость подачи 3 мл/мин, доза 450;
для канала 2 — направление 0, скорость подачи 5 мл/мин, доза 450.

Сначала построй полный план и запроси подтверждение перед запуском."""

TERMINAL_STATES = {
    "TASK_STATE_COMPLETED",
    "TASK_STATE_FAILED",
    "TASK_STATE_REJECTED",
    "TASK_STATE_CANCELED",
}


def wait_for_update(
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
        if state not in {"TASK_STATE_SUBMITTED", "TASK_STATE_WORKING"}:
            return task
    raise TimeoutError(f"timeout waiting for task {task_id}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("A2A_ROUTER_PUBLIC_URL", "https://ailab.se.ifmo.ru/"),
    )
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=DEFAULT_POLL_INTERVAL,
        help=f"seconds between status requests (default: {DEFAULT_POLL_INTERVAL:g})",
    )
    parser.add_argument(
        "--approve",
        action="store_true",
        help="allow execution after an interactive confirmation",
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
    experiment_id = f"chem-reactor-{suffix}"
    context_id = f"ctx-{experiment_id}"
    client = A2AClient(args.base_url, timeout=300)
    try:
        response = client.send_message(
            text=EXPERIMENT_PROMPT,
            experiment_id=experiment_id,
            context_id=context_id,
            message_id=f"create-{suffix}",
        )
        print_json(response)
        task = task_from_response(response)
        task_id = str(task["id"])
        task = wait_for_update(client, task_id, args.timeout, args.poll_interval)
        state, phase = task_state(task), task_phase(task)
        if state != "TASK_STATE_INPUT_REQUIRED" or phase != "approval":
            print(
                "STOP: the plan is not ready for approval. "
                "Review the status message above and answer missing questions manually."
            )
            return 2 if state not in TERMINAL_STATES else 1
        print(f"PLAN READY: task={task_id}, experiment={experiment_id}")
        if not args.approve:
            print("SAFE STOP: use --approve to allow real equipment execution")
            return 0
        if not args.yes and input("Type RUN to execute this real experiment: ").strip() != "RUN":
            print("Execution canceled by operator")
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
            # A long synchronous run can outlive the router HTTP timeout while
            # the agent continues executing. Poll the task before declaring failure.
            print(f"WARNING: approval request returned {exc}; polling task status")
        task = wait_for_update(client, task_id, args.timeout, args.poll_interval)
        state, phase = task_state(task), task_phase(task)
        if state == "TASK_STATE_COMPLETED":
            print("PASS: reactor experiment completed")
            return 0
        print(f"STOP: execution ended or paused at {state}/{phase}")
        return 1 if state in TERMINAL_STATES else 2
    except (A2ARequestError, KeyError, TimeoutError) as exc:
        print(f"FAIL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
