"""
agent.py
Constructs the DummyAgent using the OpenAI Agents SDK.
This agent is only for SDK validation — not part of the deliverable.
"""

from agents import Agent
from dummy_agent.tools import search, calculator

dummy_agent = Agent(
    name="DummyAgent",
    instructions=(
        "You are a helpful assistant. "
        "Use the search tool to look up information and the calculator tool for maths. "
        "Always use at least one tool before answering."
    ),
    tools=[search, calculator],
)


"""
run.py
Runs the DummyAgent through the SDK so telemetry is captured end-to-end.
"""

import asyncio
import logging

from agents import Runner

from sdk.instrument import instrument
from sdk.telemetry import run_with_telemetry
from dummy_agent.agent import dummy_agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PROMPT = "What is 42 multiplied by 7? Also search for the capital of France."


async def main():
    instrument()  # bootstrap observability once

    logger.info(f"Running DummyAgent with prompt: {PROMPT!r}")

    result = await run_with_telemetry(
        runner_coro=Runner.run(dummy_agent, PROMPT),
        agent_name="DummyAgent",
    )

    logger.info(f"Agent output: {result.final_output}")


if __name__ == "__main__":
    asyncio.run(main())
"""
tools.py
Dummy tools used by the test agent to generate tool-call telemetry.
"""

from agents import function_tool


@function_tool
def search(query: str) -> str:
    """Simulate a web search. Returns a dummy result."""
    return f"[Search result for '{query}']: This is a simulated result."


@function_tool
def calculator(expression: str) -> str:
    """Evaluate a simple math expression safely."""
    try:
        # Restrict to safe characters only
        allowed = set("0123456789+-*/(). ")
        if not all(c in allowed for c in expression):
            return "Error: invalid characters in expression."
        result = eval(expression, {"__builtins__": {}})  # noqa: S307
        return str(result)
    except Exception as exc:
        return f"Error: {exc}"
