"""Persist normalized actor and artist profiles from synthesized run findings."""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from config import ENTITIES


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:100] or "unknown"


def _merge(items: list, additions: list) -> list:
    seen = {json.dumps(item, sort_keys=True, ensure_ascii=False) for item in items if isinstance(item, (dict, list, str, int, float))}
    for item in additions:
        marker = json.dumps(item, sort_keys=True, ensure_ascii=False)
        if marker not in seen:
            items.append(item)
            seen.add(marker)
    return items


def _as_list(value) -> list:
    """Normalize Claude's list-like fields before cumulative merging."""
    if value in (None, ""):
        return []
    return value if isinstance(value, list) else [value]


def _evidence(item: dict) -> list[dict]:
    values = item.get("trend_evidence") or item.get("evidence") or item.get("supporting_history") or []
    if isinstance(values, dict):
        values = [values]
    return [value for value in values if isinstance(value, dict)]


def _sources(item: dict) -> list[dict]:
    values = []
    for platform in item.get("platforms", []) or []:
        if isinstance(platform, dict) and platform.get("url"):
            values.append({"source": platform.get("platform"), "url": platform["url"], "handle": platform.get("handle")})
    for evidence in _evidence(item):
        if evidence.get("url"):
            values.append({"source": evidence.get("source") or evidence.get("type"), "url": evidence["url"]})
    return values


def _youtube_videos(run_dir: Path, name: str) -> list[dict]:
    """Attach focused-run videos mentioning this entity to its profile."""
    try:
        report = json.loads((run_dir / "apify_data.json").read_text(encoding="utf-8"))
        items = report.get("youtube", {}).get("items", [])
    except (OSError, json.JSONDecodeError):
        return []
    pattern = re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)
    videos = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = " ".join(str(item.get(key) or "") for key in ("title", "description", "channelName", "caption"))
        if not pattern.search(text) or not item.get("url"):
            continue
        videos.append({key: item.get(key) for key in
                       ("title", "url", "thumbnailUrl", "viewCount", "likes", "comments", "publishedAt", "channelName", "channelUrl")
                       if item.get(key) is not None})
    return sorted(videos, key=lambda value: int(value.get("viewCount") or 0), reverse=True)


def _instagram_posts(run_dir: Path, name: str) -> list[dict]:
    """Attach focused-run Instagram posts mentioning this entity to its profile."""
    try:
        report = json.loads((run_dir / "apify_data.json").read_text(encoding="utf-8"))
        items = report.get("instagram", {}).get("items", [])
    except (OSError, json.JSONDecodeError):
        return []
    pattern = re.compile(rf"\b{re.escape(name)}\b", re.IGNORECASE)
    posts = []
    for item in items:
        if not isinstance(item, dict) or not item.get("url"):
            continue
        text = " ".join(str(item.get(key) or "") for key in ("caption", "ownerUsername", "ownerFullName"))
        text += " " + " ".join(str(tag) for tag in item.get("hashtags", []))
        if not pattern.search(text):
            continue
        posts.append({key: item.get(key) for key in
                      ("id", "url", "displayUrl", "videoUrl", "images", "caption", "ownerUsername", "ownerFullName", "hashtags", "likesCount", "commentsCount", "timestamp")
                      if item.get(key) is not None})
    return sorted(posts, key=lambda value: int(value.get("likesCount") or 0), reverse=True)


def persist(run_dir: Path, kind: str, brief: dict) -> int:
    findings_path = run_dir / "findings.json"
    if not findings_path.exists():
        return 0
    try:
        report = json.loads(findings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 0
    findings = report.get("findings", []) or []
    contacts = report.get("contacts", []) or []
    if isinstance(contacts, dict):
        contacts = []
    entity_type = "actors" if kind == "actor" else "artists"
    run_id = run_dir.name
    saved = 0
    for item in findings:
        if not isinstance(item, dict):
            continue
        name = item.get("actor") if kind == "actor" else None
        name = name or item.get("stage_name") or item.get("stageName") or item.get("name") or item.get("topic")
        if not name:
            continue
        entity_dir = ENTITIES / entity_type / _slug(str(name))
        entity_dir.mkdir(parents=True, exist_ok=True)
        collected_videos = _youtube_videos(run_dir, str(name))
        collected_posts = _instagram_posts(run_dir, str(name))
        profile_path = entity_dir / "profile.json"
        try:
            profile = json.loads(profile_path.read_text(encoding="utf-8")) if profile_path.exists() else {}
        except (OSError, json.JSONDecodeError):
            profile = {}
        profile.update({
            "entity_type": kind,
            "entity_id": _slug(str(name)),
            "name": name,
            "identity_confidence": item.get("identity_confidence", profile.get("identity_confidence")),
            "language": brief.get("language") or profile.get("language"),
            "market": brief.get("market") or profile.get("market"),
            "industry": brief.get("industry") or profile.get("industry"),
            "location": item.get("location") or item.get("origin") or profile.get("location"),
            "personal_details": item.get("personal_details") or profile.get("personal_details", {}),
            "biography": item.get("biography") or item.get("profile") or profile.get("biography"),
            "services": _as_list(item.get("services") or profile.get("services", [])),
            "genres": _as_list(item.get("genres") or profile.get("genres", [])),
            "filmography": _as_list(profile.get("filmography", [])) + _as_list(item.get("filmography")),
            "upcoming_projects": _as_list(profile.get("upcoming_projects", [])) + _as_list(item.get("upcoming_projects")),
            "awards": _as_list(profile.get("awards", [])) + _as_list(item.get("awards")),
            "news": _as_list(profile.get("news", [])) + _as_list(item.get("news")),
            "videos": _as_list(profile.get("videos", [])) + _as_list(item.get("videos")) + collected_videos,
            "posts": _as_list(profile.get("posts", [])) + collected_posts,
            "official_profiles": _as_list(profile.get("official_profiles", [])) + _as_list(item.get("official_profiles") or item.get("platforms")),
            "social_activity": item.get("social_activity") or profile.get("social_activity", {}),
            "trend_snapshot": {
                "run_id": run_id,
                "status": item.get("trend_status") or item.get("status"),
                "summary": item.get("summary") or item.get("trend_note") or item.get("notes"),
                "evidence": _evidence(item),
            },
            "last_seen_run": run_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        for field in ("filmography", "upcoming_projects", "awards", "news", "videos", "official_profiles"):
            profile[field] = _merge([], _as_list(profile.get(field, [])))
        matched_contacts = [contact for contact in contacts if isinstance(contact, dict) and
                            str(contact.get("artist") or contact.get("name") or "").lower() == str(name).lower()]
        if matched_contacts:
            profile["contacts"] = _merge(_as_list(profile.get("contacts", [])), matched_contacts)
        profile_path.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")

        activity_path = entity_dir / "activity.json"
        try:
            activity = json.loads(activity_path.read_text(encoding="utf-8")) if activity_path.exists() else {"snapshots": []}
        except (OSError, json.JSONDecodeError):
            activity = {"snapshots": []}
        snapshots = activity.setdefault("snapshots", [])
        if not any(isinstance(snapshot, dict) and snapshot.get("run_id") == run_id for snapshot in snapshots):
            snapshots.append({
                "run_id": run_id,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "trend_status": item.get("trend_status") or item.get("status"),
                "summary": item.get("summary") or item.get("notes") or item.get("trend_note"),
                "evidence": _evidence(item),
            })
        activity_path.write_text(json.dumps(activity, indent=2, ensure_ascii=False), encoding="utf-8")
        sources_path = entity_dir / "sources.json"
        try:
            previous_sources = json.loads(sources_path.read_text(encoding="utf-8")) if sources_path.exists() else []
        except (OSError, json.JSONDecodeError):
            previous_sources = []
        video_sources = [{"source": "youtube", "url": video["url"]} for video in collected_videos]
        post_sources = [{"source": "instagram", "url": post["url"]} for post in collected_posts]
        sources_path.write_text(json.dumps(_merge(previous_sources if isinstance(previous_sources, list) else [], _sources(item) + video_sources + post_sources), indent=2, ensure_ascii=False), encoding="utf-8")
        saved += 1
    return saved
