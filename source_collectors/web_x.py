"""Web/X query setup and the isolated Claude evidence phase."""

import json

from .apify import log
from .claude import run_phase
from prompts.web_prompt import build as build_web_prompt


def queue(selected: set[str], query_seeds: list[str], logger=None) -> dict:
    data = {}
    if "web" in selected:
        log(logger, "Web: queued for Claude WebSearch")
        data["web"] = {"status": "claude_pending", "queries": query_seeds}
    if "x" in selected:
        log(logger, "X: queued for Claude WebSearch")
        data["x"] = {"status": "claude_pending", "queries": [f"site:x.com {query}" for query in query_seeds]}
    return data


def run_research(args, run_dir, metadata, logger=None) -> int:
    """Run only Web/X collection; findings synthesis happens in main.py."""
    if not any(source in args.sources for source in ("web", "x")):
        return 0
    prompt = build_web_prompt(args, run_dir, metadata)
    (run_dir / "web_research_prompt.md").write_text(prompt, encoding="utf-8")
    for source in ("web", "x"):
        if metadata.get("platform_status", {}).get(source, {}).get("status") == "claude_pending":
            metadata["platform_status"][source]["status"] = "claude_running"
    (run_dir / "run_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    code = run_phase(prompt, run_dir, logger, "web")
    for source in ("web", "x"):
        if source in args.sources:
            metadata["platform_status"][source]["status"] = "completed_by_claude" if code == 0 else "failed"
            if code:
                metadata["platform_status"][source]["reason"] = f"Web/X phase return code {code}"
    (run_dir / "run_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return code
