#!/usr/bin/env python3
"""
Minimal smoke test for the configured main agent model.

Usage:
  python3 backend/scripts/verify_agent_model_basic.py
  python3 backend/scripts/verify_agent_model_basic.py --prompt "Say hello in 5 words."
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return

    repo_env = Path(__file__).resolve().parents[2] / ".env"
    if repo_env.exists():
        load_dotenv(dotenv_path=repo_env)


def _extract_text(response: object) -> str:
    try:
        choices = getattr(response, "choices", None) or []
        if not choices:
            return ""
        message = getattr(choices[0], "message", None)
        if message is None:
            return ""
        content = getattr(message, "content", "")
        if isinstance(content, str):
            return content.strip()
        return str(content).strip()
    except Exception:
        return ""


def _is_retryable_rate_limit_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return (
        "429" in message
        or "resource_exhausted" in message
        or "ratelimiterror" in message
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify AGENT_MODEL basic response path.")
    parser.add_argument(
        "--prompt",
        default="Reply with exactly: MODEL_OK",
        help="Prompt to send to the model.",
    )
    parser.add_argument(
        "--max-completion-tokens",
        type=int,
        default=128,
        help="Max completion tokens for the test request.",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=3,
        help="Retry attempts for transient rate-limit responses.",
    )
    args = parser.parse_args()

    _load_env()

    from videoagent.config import Config
    from videoagent.agent.service import _configure_litellm_vertex_env, _select_model_name
    import litellm

    config = Config()
    _configure_litellm_vertex_env(config)
    model_name = _select_model_name(config)

    print(f"Model: {model_name}")
    print(f"VERTEXAI_PROJECT: {os.environ.get('VERTEXAI_PROJECT', '<unset>')}")
    print(f"VERTEXAI_LOCATION: {os.environ.get('VERTEXAI_LOCATION', '<unset>')}")

    response = None
    for attempt in range(1, max(args.max_attempts, 1) + 1):
        try:
            response = litellm.completion(
                model=model_name,
                messages=[{"role": "user", "content": args.prompt}],
                temperature=0,
                max_completion_tokens=args.max_completion_tokens,
                thinking={"type": "adaptive"},
                timeout=90,
            )
            break
        except Exception as exc:
            if attempt < args.max_attempts and _is_retryable_rate_limit_error(exc):
                wait_s = min(2 ** attempt, 8)
                print(
                    f"Attempt {attempt}/{args.max_attempts} hit rate limit; retrying in {wait_s}s..."
                )
                time.sleep(wait_s)
                continue
            print(f"\nFAIL: request failed for model '{model_name}'", file=sys.stderr)
            print(str(exc), file=sys.stderr)
            return 1

    text = _extract_text(response)
    if not text:
        print("\nFAIL: request succeeded but no text content was returned.", file=sys.stderr)
        print(response)
        return 2

    usage = getattr(response, "usage", None)
    print("\nSUCCESS: model responded.")
    print(f"Response: {text}")
    if usage is not None:
        print(f"Usage: {usage}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
