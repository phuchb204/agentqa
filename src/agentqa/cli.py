import argparse
import asyncio
import os
import sys
from pathlib import Path

from agentqa.agent.loop import run_case
from agentqa.agent.policy import (
    DEFAULT_CONF_MIN,
    DEFAULT_GOAL_DONE_MIN,
    DEFAULT_MAX_OPTIONS,
    DEFAULT_STUCK_MIN,
    JevCascadePolicy,
    LLMPolicy,
    Policy,
)
from agentqa.contracts import TestCase, load_case
from agentqa.llm.jev import JevClient
from agentqa.llm.openai_adapter import OpenAICompatAdapter
from agentqa.platform.trace_store import write_trace
from agentqa.verify.checker import check_all


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name, "")
    return float(raw) if raw else default


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    return int(raw) if raw else default


def build_policy() -> Policy:
    llm = OpenAICompatAdapter.from_env()
    mode = os.environ.get("AGENTQA_POLICY", "llm")
    if mode == "llm":
        return LLMPolicy(llm)
    if mode == "jev":
        return JevCascadePolicy(
            jev=JevClient.from_env(),
            llm=llm,
            goal_done_min=_env_float("AGENTQA_JEV_GOAL_DONE_MIN", DEFAULT_GOAL_DONE_MIN),
            stuck_min=_env_float("AGENTQA_JEV_STUCK_MIN", DEFAULT_STUCK_MIN),
            conf_min=_env_float("AGENTQA_JEV_CONF_MIN", DEFAULT_CONF_MIN),
            max_options=_env_int("AGENTQA_JEV_MAX_OPTIONS", DEFAULT_MAX_OPTIONS),
        )
    raise ValueError(f"unsupported AGENTQA_POLICY: {mode!r} (expected 'llm' or 'jev')")


async def _run_case(case: TestCase, *, base_url: str, headless: bool):
    policy = build_policy()
    try:
        return await run_case(case, policy, base_url=base_url, headless=headless, checker=check_all)
    finally:
        await policy.aclose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="agentqa")
    sub = parser.add_subparsers(dest="command", required=True)

    run_parser = sub.add_parser("run", help="run one test case")
    run_parser.add_argument("--case", required=True)
    run_parser.add_argument("--base-url", required=True, dest="base_url")
    run_parser.add_argument("--out", default="experiments/runs")
    run_parser.add_argument("--headed", action="store_true")

    args = parser.parse_args(argv)

    case = load_case(Path(args.case))
    trace = asyncio.run(_run_case(case, base_url=args.base_url, headless=not args.headed))
    path = write_trace(trace, Path(args.out))
    print(f"{trace.status.upper()} {trace.case_name} -> {path}")
    return 0 if trace.status == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
