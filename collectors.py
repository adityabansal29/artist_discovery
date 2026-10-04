"""Compatibility orchestrator for the modular source collectors."""

from pathlib import Path

from source_collectors.apify import load_env
from source_collectors.instagram import collect as collect_instagram
from source_collectors.youtube import collect as collect_youtube
from source_collectors.reddit import collect as collect_reddit
from source_collectors.web_x import queue as queue_web_x


def collect_sources(args, query_seeds: list[str], logger=None) -> dict:
    """Run selected collectors in source order and return their raw outputs."""
    load_env(Path(__file__).resolve().parent / ".env")
    selected = set(args.sources)
    data = {}
    if "instagram" in selected:
        data["instagram"] = collect_instagram(args, logger)
    if "youtube" in selected:
        data["youtube"] = collect_youtube(query_seeds, logger, args.refresh_mode, args.kind)
    if "reddit" in selected:
        data["reddit"] = collect_reddit(args, query_seeds, logger)
    data.update(queue_web_x(selected, query_seeds, logger))
    return data
