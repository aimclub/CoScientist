"""HITL handlers — abstract interface and implementations."""

import asyncio
from abc import ABC, abstractmethod

from CoScientist.hitl.models import HITLRequest, HITLResponse, HITLAction


class AbstractHITLHandler(ABC):
    """Abstract interface for handling HITL requests.

    Implement this for different UIs: console, web chat, Telegram, etc.
    """

    @abstractmethod
    async def handle_request(self, request: HITLRequest) -> HITLResponse:
        """Process a HITL request and return the human's response."""
        ...


class DelegatingHITLHandler(AbstractHITLHandler):
    """A handler that delegates to another handler, allowing runtime swapping."""

    def __init__(self, delegate: AbstractHITLHandler):
        self.delegate = delegate

    def set_delegate(self, delegate: AbstractHITLHandler):
        self.delegate = delegate

    async def handle_request(self, request: HITLRequest) -> HITLResponse:
        return await self.delegate.handle_request(request)

    def __deepcopy__(self, memo):
        # Return self so that workflow deepcopies share the same handler instance
        return self



class ConsoleHITLHandler(AbstractHITLHandler):
    """Simple console-based HITL handler (for local development/testing)."""

    async def handle_request(self, request: HITLRequest) -> HITLResponse:
        print(f"\n{'=' * 60}")
        print(f"[HITL] Agent '{request.agent_name}' requests: {request.action_type.value}. Invoked_via: {request.invoked_via}")
        print(f"Message: {request.message}")

        if request.context and "output" in request.context:
            print(f"\nPROPOSED PLAN/OUTPUT:")
            print(f"{'-' * 30}")
            print(f"{request.context['output']}")
            print(f"{'-' * 30}")

        if request.options:
            print("\nOptions:")
            for i, opt in enumerate(request.options, 1):
                print(f"  {i}. {opt}")

        if request.form:
            return await self._prompt_form(request)
        if request.action_type == HITLAction.SELECT and request.options:
            return await self._prompt_select(request)

        is_simple_toggle = (request.invoked_via == "callback" and request.action_type == HITLAction.APPROVE)
        
        print("\nAction Menu:")
        if is_simple_toggle:
            print("  1. Approve (Proceed with agent execution)")
            print("  2. Reject (Skip this agent's execution)")
        else:
            print("  1. Approve (Accept and proceed)")
            print("  2. Edit (Provide feedback / request changes to agent)")
            print("  3. Stop program (Exit completely)")
        
        while True:
            choice = await asyncio.to_thread(input, f"\nSelect action (1-{2 if is_simple_toggle else 3}): ")
            choice = choice.strip()

            if choice == "1":
                return HITLResponse(
                    action=HITLAction.APPROVE,
                    approved=True
                )
            elif choice == "2":
                if is_simple_toggle:
                    return HITLResponse(
                        action=HITLAction.REJECT,
                        approved=False,
                        instructions="Human rejected execution."
                    )
                else:
                    feedback = await asyncio.to_thread(input, "Enter your feedback/changes: ")
                    return HITLResponse(
                        action=HITLAction.EDIT,
                        approved=False,
                        instructions=feedback
                    )
            elif choice == "3" and not is_simple_toggle:
                print("\nStopping program execution based on user request...")
                import sys
                sys.exit(0)
            else:
                print(f"Invalid choice. Please enter a valid option.")

    async def _prompt_select(self, request: HITLRequest) -> HITLResponse:
        n = len(request.options)
        while True:
            raw = await asyncio.to_thread(input, f"\nSelect option (1-{n}): ")
            raw = raw.strip()
            if raw.isdigit():
                idx = int(raw) - 1
                if 0 <= idx < n:
                    return HITLResponse(
                        action=HITLAction.SELECT,
                        approved=True,
                        selected_option=request.options[idx],
                    )
            print(f"Invalid choice. Please enter 1-{n}.")

    async def _prompt_form(self, request: HITLRequest) -> HITLResponse:
        form_values: dict = {}
        intro = (request.form or {}).get("intro")
        if intro:
            print(f"\n{intro}")
        for block in (request.form or {}).get("blocks") or []:
            title = block.get("title") or ""
            if title:
                print(f"\n{title}")
            answers: dict = {}
            for field in block.get("fields") or []:
                name = field.get("name") or ""
                if not name:
                    continue
                raw = await asyncio.to_thread(input, f"  {name}: ")
                value = raw.strip()
                if value:
                    answers[name] = value
            if answers:
                form_values[title] = answers
        return HITLResponse(
            action=HITLAction.APPROVE,
            approved=True,
            form_values=form_values or None,
        )