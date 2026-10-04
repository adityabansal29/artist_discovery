#!/usr/bin/env python3
"""Run collection, Web/X research, and final findings synthesis."""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from collectors import collect_sources
from config import DEFAULT_SOURCES, LOCATION_SCOPES, OPTIONAL_SOURCES, OUTPUTS, REFRESH_MODES, RESEARCH_WINDOW_DAYS
from entity_profiles import persist as persist_entity_profiles
from prompts.findings_prompt import build as build_findings_prompt
from source_collectors.claude import run_phase
from source_collectors.web_x import run_research as run_web_x_research

DIRECT_SOURCES = {"instagram", "youtube", "reddit"}
DELEGATED_SOURCES = ("web", "x")


def csv_values(value: str) -> list[str]:
    return [item.strip().lower() for item in value.split(",") if item.strip()]


def build_queries(args: argparse.Namespace) -> list[str]:
    """Build deterministic query seeds; the research model expands them."""
    if args.kind == "artist":
        location = args.city or args.state or args.zone
        language = args.language if args.language and args.language.lower() not in {"all", "all languages"} else None
        category = args.category or "artist"
        genre = args.genre
        location_prefix = f'"{location}" "India" ' if location else '"India" '
        language_prefix = f'"{language}" ' if language else ""
        genre_phrase = f'"{genre}" ' if genre else ""
        return [
            f'{location_prefix}{language_prefix}"{category}" {genre_phrase}booking',
            f'{location_prefix}{language_prefix}"{category}" {genre_phrase}live performance events',
            f'{location_prefix}{language_prefix}"{category}" {genre_phrase}Instagram YouTube',
            f'{location_prefix}{language_prefix}"{category}" {genre_phrase}"for bookings"',
        ]
    language = args.language or "all languages"
    market = args.market or "global"
    industry = getattr(args, "industry", None) or "all industries"
    subject = args.actor or args.movie or "current movie actors"
    return [
        f'"{subject}" "{language}" "{market}" "{industry}" latest movie',
        f'"{subject}" "{language}" "{market}" "{industry}" interview',
        f'"{subject}" "{language}" "{market}" "{industry}" award OR nomination',
        f'"{subject}" "{language}" "{market}" "{industry}" Instagram YouTube',
    ]


def build_profile_queries(args: argparse.Namespace) -> list[str]:
    """Return Web-only identity queries for focused actor research."""
    if args.kind != "actor":
        return []
    language = args.language or "all languages"
    market = args.market or "global"
    industry = getattr(args, "industry", None) or "all industries"
    if not (args.actor or args.movie):
        year = datetime.now(timezone.utc).year
        return [
            f'"top 30" "{language}" actors "{market}" "{industry}" current popular actors',
            f'"{language} actors" "{industry}" "{year}" rising stars upcoming films',
            f'"{language} actors" "{industry}" upcoming movies {year} cast announcement',
            f'"{language} actors" "{industry}" box office {year} leading actors',
            f'"{language} actors" "{industry}" debut actors newcomers {year}',
            f'site:filmcompanion.in "{language}" "{industry}" actors latest',
            f'site:thehindu.com "{language}" "{industry}" actor film announcement',
            f'site:indianexpress.com "{language}" "{industry}" cinema actor',
            f'site:imdb.com/name/ "{language}" actors "{market}" "{industry}" filmography',
            f'site:themoviedb.org/person "{language}" actors "{market}" "{industry}" filmography',
        ]
    subject = args.actor or args.movie
    return [
        f'site:imdb.com/name/ "{subject}" biography filmography',
        f'site:themoviedb.org/person "{subject}" biography filmography',
    ]


def validate(args: argparse.Namespace) -> None:
    unknown = set(args.sources) - (set(DEFAULT_SOURCES) | set(OPTIONAL_SOURCES))
    if unknown:
        raise SystemExit(f"Unknown source(s): {', '.join(sorted(unknown))}")
    if args.location_scope not in LOCATION_SCOPES:
        raise SystemExit(f"location-scope must be one of: {', '.join(LOCATION_SCOPES)}")
    if args.kind == "artist" and not args.category:
        raise SystemExit("Artist research requires an L1 category")
    if args.kind == "artist" and not args.genre:
        raise SystemExit("Artist research requires an L2 tag")
    if args.kind == "actor" and not (args.language or args.market or args.industry or args.actor or args.movie):
        raise SystemExit("Actor research needs --language, --market, --industry, --actor, or --movie")


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def make_run(args: argparse.Namespace) -> tuple[Path, dict]:
    base_id = datetime.now(ZoneInfo("Asia/Kolkata")).strftime("%Y%m%d_%H%M%S")
    run_id = base_id
    run_dir = OUTPUTS / run_id
    suffix = 1
    while True:
        try:
            run_dir.mkdir(parents=True, exist_ok=False)
            break
        except FileExistsError:
            run_id = f"{base_id}_{suffix:02d}"
            run_dir = OUTPUTS / run_id
            suffix += 1
    metadata = {
        "run_id": run_id, 
        "pid": os.getpid(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "brief": vars(args).copy(),
        "queries": build_queries(args),
        "profile_queries": build_profile_queries(args),
        "status": "started"
    }
    write_json(run_dir / "run_metadata.json", metadata)
    return run_dir, metadata


def build_claude_input(apify_data: dict) -> dict:
    """Keep raw collector data intact while creating compact batch evidence."""
    keep = {
        "id", "url", "shortCode", "caption", "hashtags", "mentions", "timestamp",
        "ownerUsername", "ownerFullName", "likesCount", "commentsCount", "firstComment",
        "title", "description", "channelName", "channelUrl", "viewCount", "publishedAt",
    }
    profile_keep = {
        "username", "fullName", "biography", "externalUrl", "businessEmail",
        "businessPhoneNumber", "followersCount", "followsCount", "postsCount",
        "isVerified", "url", "businessCategoryName", "isBusinessAccount",
        "activity_summary",
    }
    channel_keep = {
        "channelId", "channelName", "channelHandle", "channelUrl", "description",
        "channelDescription", "channelLinks", "channelLinksText", "subscriberCount",
        "totalVideos", "totalViews", "country", "location", "isVerified",
        "videos", "latestVideos", "videoData", "links", "joinedDate", "keywords",
        "activity_summary", "profile_source", "enrichment_missing", "lead_type",
    }
    compact = {}
    for source, data in apify_data.items():
        compact[source] = {
            key: value for key, value in data.items()
            if key not in {"items", "batch_items"}
        }
        evidence_items = data.get("batch_items", data.get("items"))
        if evidence_items:
            compact[source]["items"] = [
                {key: item.get(key) for key in keep if key in item}
                for item in evidence_items
            ]
        if data.get("profiles"):
            compact[source]["profiles"] = [
                {key: profile.get(key) for key in profile_keep if key in profile}
                for profile in data["profiles"]
            ]
        if data.get("channel_profiles"):
            compact[source]["channel_profiles"] = [
                {key: profile.get(key) for key in channel_keep if key in profile}
                for profile in data["channel_profiles"]
            ]
    return compact


def run_findings_research(args, run_dir: Path, metadata: dict, logger=None) -> int:
    """Run only the final synthesis phase using saved evidence files."""
    prompt = build_findings_prompt(args, run_dir, metadata)
    (run_dir / "research_prompt.md").write_text(prompt, encoding="utf-8")
    if logger:
        logger("Claude: starting findings synthesis phase", "researching")
    code = run_phase(prompt, run_dir, logger, "findings")
    metadata["status"] = "completed" if code == 0 and (run_dir / "findings.json").exists() else "incomplete"
    metadata["returncode"] = code
    if logger:
        logger("Claude: findings synthesis completed" if code == 0 else "Claude: findings synthesis failed",
               "completed" if code == 0 else "failed")
    write_json(run_dir / "run_metadata.json", metadata)
    return code


def make_logger(run_dir: Path, metadata: dict):
    """Create the shared progress logger used by collectors and Claude phases."""
    progress_path = run_dir / "progress.log"

    def log(message: str, phase: str = "collecting") -> None:
        stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
        with progress_path.open("a", encoding="utf-8") as progress:
            progress.write(f"[{stamp}] {message}\n")
        print(f"[{stamp}] {message}", flush=True)
        metadata["phase"] = phase
        metadata["last_message"] = message
        write_json(run_dir / "run_metadata.json", metadata)

    return log


def save_collector_outputs(run_dir: Path, args, metadata: dict, apify_data: dict) -> None:
    """Persist raw data, compact evidence, placeholders, and source status."""
    write_json(run_dir / "apify_data.json", apify_data)
    write_json(run_dir / "claude_input.json", build_claude_input(apify_data))
    for source in DELEGATED_SOURCES:
        if source not in args.sources:
            continue
        write_json(run_dir / f"{source}_data.json", {
            "source": source,
            "queries": apify_data[source].get("queries", []),
            "results": [],
            "warnings": ["Claude source extraction pending"],
        })
    metadata["platform_status"] = {
        source: {key: value for key, value in data.items() if key != "items"}
        for source, data in apify_data.items()
    }
    write_json(run_dir / "run_metadata.json", metadata)


def blocked_collectors(apify_data: dict, args: argparse.Namespace) -> dict:
    return {
        source: data.get("reason", data.get("status", "unknown"))
        for source, data in apify_data.items()
        if source in DIRECT_SOURCES and data.get("status") in {"skipped", "failed"}
        and not (args.kind == "actor" and source == "instagram" and data.get("reason") == "no Instagram hashtags available")
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run V0 artist/actor research")
    parser.add_argument("--kind", choices=("artist", "actor"), required=True)
    parser.add_argument("--language")
    parser.add_argument("--market")
    parser.add_argument("--industry")
    parser.add_argument("--city")
    parser.add_argument("--state")
    parser.add_argument("--zone")
    parser.add_argument("--location-scope", choices=LOCATION_SCOPES, default="All India")
    parser.add_argument("--category")
    parser.add_argument("--genre")
    parser.add_argument("--actor")
    parser.add_argument("--movie")
    parser.add_argument("--refresh-mode", choices=REFRESH_MODES, default="discovery")
    parser.add_argument("--sources", default=",".join(DEFAULT_SOURCES), help="Comma-separated: instagram,youtube,web,reddit,x")
    args = parser.parse_args(argv)
    args.window_days = RESEARCH_WINDOW_DAYS
    args.sources = csv_values(args.sources)
    validate(args)
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    run_dir, metadata = make_run(args)
    log = make_logger(run_dir, metadata)

    log("Run started")
    apify_data = collect_sources(args, metadata["queries"], log)
    save_collector_outputs(run_dir, args, metadata, apify_data)
    blocked = blocked_collectors(apify_data, args)
    if blocked:
        log("Run blocked: selected direct collectors are unavailable", "blocked")
        metadata["status"] = "blocked"
        metadata["blocked_sources"] = blocked
        write_json(run_dir / "run_metadata.json", metadata)
        return 2
    log("Direct source collection finished", "researching")
    print(f"Run directory: {run_dir}")
    print(f"Queries: {len(metadata['queries'])}; sources: {', '.join(args.sources)}")
    web_code = run_web_x_research(args, run_dir, metadata, log)
    findings_code = run_findings_research(args, run_dir, metadata, log)
    if findings_code == 0:
        saved_entities = persist_entity_profiles(run_dir, args.kind, metadata["brief"])
        log(f"Entity profiles: persisted {saved_entities} {args.kind} profiles", "completed")
    return findings_code if findings_code else web_code


if __name__ == "__main__":
    sys.exit(main())
