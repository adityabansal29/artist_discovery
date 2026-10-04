"""Persistent hashtag performance rules for future research runs."""

import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PERFORMANCE_FILE = ROOT / "hashtags" / "performance.json"
SCORE_THRESHOLD = 0.25
MIN_RUNS_BEFORE_SUPPRESS = 2
MIN_EXPLORATION_TAGS = 2


def context_key(args) -> str:
    language = args.language or "all"
    if language.lower() == "all languages":
        language = "all"
    location = args.city or args.state or args.zone or args.location_scope or "all"
    return "|".join(str(value or "all").strip().lower() for value in (
        args.kind, args.category or args.actor or "all", args.genre or args.movie or "all", language, location
    ))


def load() -> dict:
    if not PERFORMANCE_FILE.exists():
        return {}
    try:
        value = json.loads(PERFORMANCE_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save(value: dict) -> None:
    PERFORMANCE_FILE.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def select(args, tags: list[str]) -> list[str]:
    """Keep new tags and tags above threshold; retain a small exploration set."""
    performance = load().get(context_key(args), {})
    eligible, suppressed = [], []
    for tag in tags:
        record = performance.get(tag)
        if not record or record.get("runs", 0) < MIN_RUNS_BEFORE_SUPPRESS or record.get("score", 0) >= SCORE_THRESHOLD:
            eligible.append(tag)
        else:
            suppressed.append(tag)
    if len(eligible) < MIN_EXPLORATION_TAGS:
        suppressed.sort(key=lambda tag: performance.get(tag, {}).get("score", 0), reverse=True)
        eligible.extend(suppressed[:MIN_EXPLORATION_TAGS - len(eligible)])
    return eligible


def _number(item: dict, key: str) -> int:
    try:
        return int(item.get(key, 0) or 0)
    except (TypeError, ValueError):
        return 0


def _tagged(item: dict, tag: str) -> bool:
    return tag in {str(value).lower().replace(" ", "") for value in item.get("hashtags", [])}


def _india_signal(item: dict) -> bool:
    text = " ".join(str(item.get(key) or "") for key in ("caption", "locationName", "ownerFullName")).lower()
    tags = " ".join(str(value) for value in item.get("hashtags", [])).lower()
    markers = ("india", "indian", "mumbai", "delhi", "bengaluru", "bangalore", "chennai", "hyderabad",
               "kolkata", "pune", "ahmedabad", "rajkot", "gujarat", "punjab", "maharashtra", "bollywood")
    return any(marker in text or marker in tags for marker in markers)


def update(args, tags: list[str], items: list[dict]) -> dict:
    """Accumulate source metrics and return the current score per hashtag."""
    performance = load()
    context = performance.setdefault(context_key(args), {})
    cutoff = datetime.now(timezone.utc) - timedelta(days=args.window_days)
    result = {}
    for tag in tags:
        matching = [item for item in items if _tagged(item, tag)]
        recent = []
        for item in matching:
            raw_date = item.get("timestamp") or item.get("publishedAt")
            try:
                date = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
                if date >= cutoff:
                    recent.append(item)
            except (TypeError, ValueError):
                continue
        owners = {str(item.get("ownerUsername") or "").lower() for item in matching if item.get("ownerUsername")}
        india_posts = sum(_india_signal(item) for item in matching)
        engagement = sum(_number(item, "likesCount") + _number(item, "commentsCount") for item in matching)
        record = context.setdefault(tag, {"runs": 0, "matching_posts": 0, "recent_posts": 0,
                                          "unique_profiles": 0, "india_signal_posts": 0, "engagement": 0})
        record["runs"] += 1
        record["matching_posts"] += len(matching)
        record["recent_posts"] += len(recent)
        record["unique_profiles"] += len(owners)
        record["india_signal_posts"] += india_posts
        record["engagement"] += engagement
        posts = max(record["matching_posts"], 1)
        profile_score = min(record["unique_profiles"] / max(record["runs"] * 20, 1), 1)
        india_score = record["india_signal_posts"] / posts if args.kind == "artist" else 1.0
        recent_score = record["recent_posts"] / posts
        engagement_score = min(math.log1p(record["engagement"]) / math.log1p(5000), 1)
        volume_score = min(posts / max(record["runs"] * 30, 1), 1)
        record["score"] = round(0.35 * india_score + 0.25 * profile_score + 0.20 * recent_score +
                                 0.10 * engagement_score + 0.10 * volume_score, 4)
        record["last_run_posts"] = len(matching)
        record["last_run_recent_posts"] = len(recent)
        result[tag] = record["score"]
    save(performance)
    return result
