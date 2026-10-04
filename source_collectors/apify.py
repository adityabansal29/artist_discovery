"""Shared Apify, environment, and cross-run uniqueness helpers."""

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from config import ENTITIES, REDDIT_CONTENT_INDEX, REFRESH_WINDOWS_DAYS


def load_env(path: Path) -> None:
    """Load supported credentials without overwriting real environment values."""
    if not path.exists():
        return
    allowed = {"APIFY_API_TOKEN", "REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "CLAUDE_CODE_OAUTH_TOKEN"}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in allowed and not os.environ.get(key):
            os.environ[key] = value.strip()
    if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") and os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("Set either CLAUDE_CODE_OAUTH_TOKEN or ANTHROPIC_API_KEY, not both.")


def apify_client():
    token = os.environ.get("APIFY_API_TOKEN")
    if not token:
        return None, "APIFY_API_TOKEN is not set"
    try:
        from apify_client import ApifyClient
    except ImportError:
        return None, "apify-client is not installed"
    return ApifyClient(token), None


def run_actor(client, actor_id: str, run_input: dict, timeout: int) -> list[dict]:
    """Run an Actor and read every item from its completed dataset."""
    run = client.actor(actor_id).call(run_input=run_input, run_timeout=timedelta(seconds=timeout), wait_duration=timedelta(seconds=timeout))
    return list(client.dataset(run.default_dataset_id).iterate_items())


def log(logger, message: str) -> None:
    if logger:
        logger(message)


def load_content_index() -> dict:
    if not REDDIT_CONTENT_INDEX.exists():
        return {"instagram": {}, "youtube": {}, "reddit": {}}
    try:
        data = json.loads(REDDIT_CONTENT_INDEX.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_content_index(index: dict) -> None:
    REDDIT_CONTENT_INDEX.parent.mkdir(parents=True, exist_ok=True)
    REDDIT_CONTENT_INDEX.write_text(json.dumps(index, indent=2), encoding="utf-8")


def _timestamp(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).timestamp()
        except ValueError:
            return 0.0
    return 0.0


def is_refreshable(source: str, key: str, refresh_mode: str) -> bool:
    """Return true for new entities or entities past the configured refresh window."""
    path = ENTITIES / source / f"{_entity_filename(key)}.json"
    if not path.exists():
        return True
    try:
        entity = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return True
    entry = entity.get("last_enriched_at")
    if not entry:
        return True
    if refresh_mode == "backfill":
        return True
    if not isinstance(entry, dict):
        entry = {"last_enriched_at": entry}
    age_days = (time.time() - _timestamp(entry.get("last_enriched_at"))) / 86400
    return age_days >= REFRESH_WINDOWS_DAYS[refresh_mode]


def eligible_keys(source: str, keys: list[str], refresh_mode: str) -> set[str]:
    return {key.lower() for key in keys if is_refreshable(source, key, refresh_mode)}


def _entity_filename(key: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", key).strip("._")[:100]
    return safe or "unknown"


def save_entity(source: str, key: str, payload: dict) -> None:
    """Merge one refreshed entity snapshot into its persistent record."""
    path = ENTITIES / source / f"{_entity_filename(key)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        current = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        current = {}
    current.update(payload)
    for field in ("posts", "videos"):
        if field not in payload:
            continue
        old = {str(item.get("id") or item.get("shortCode") or item.get("videoId") or item.get("url")): item
               for item in current.get(field, []) if isinstance(item, dict)}
        for item in payload[field]:
            item_key = str(item.get("id") or item.get("shortCode") or item.get("videoId") or item.get("url"))
            old[item_key] = item
        current[field] = list(old.values())
    path.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")


def activity_summary(items: list[dict], date_fields: tuple[str, ...]) -> dict:
    """Create comparable recent-activity metrics for Instagram posts or videos."""
    def number(item: dict, field: str) -> int:
        try:
            return int(item.get(field, 0) or 0)
        except (TypeError, ValueError):
            return 0

    now = datetime.now(timezone.utc)
    dated = []
    for item in items:
        raw_date = next((item.get(field) for field in date_fields if item.get(field)), None)
        if not raw_date:
            continue
        try:
            parsed = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            dated.append((parsed, item))
        except ValueError:
            continue

    summary = {"latest_activity_date": None}
    for days in (7, 15, 30):
        cutoff = now - timedelta(days=days)
        recent = [item for date, item in dated if date >= cutoff]
        summary[f"items_in_{days}d"] = len(recent)
        summary[f"likes_in_{days}d"] = sum(number(item, "likesCount") for item in recent)
        summary[f"comments_in_{days}d"] = sum(number(item, "commentsCount") for item in recent)
        summary[f"views_in_{days}d"] = sum(number(item, "viewCount") for item in recent)
    if dated:
        summary["latest_activity_date"] = max(date for date, _ in dated).isoformat()
    return summary


def select_new(items: list[dict], source: str, key_fn, limit: int) -> tuple[list[dict], int]:
    """Return the first unseen batch without marking it processed yet."""
    index = load_content_index()
    seen = {str(key).lower() for key in index.setdefault(source, {})}
    selected, keys = [], set()
    for item in items:
        key = str(key_fn(item) or "").strip()
        if not key or key.lower() in seen or key.lower() in keys:
            continue
        selected.append(item)
        keys.add(key.lower())
        if len(selected) >= limit:
            break
    return selected, len(seen)


def mark_processed(source: str, items: list[dict], key_fn) -> None:
    """Record content IDs only after the collector successfully processes them."""
    index = load_content_index()
    keys = {
        str(key_fn(item) or "").strip().lower()
        for item in items
        if key_fn(item)
    }
    index.setdefault(source, {}).update({key: time.time() for key in keys})
    save_content_index(index)
