#!/usr/bin/env python3
"""Minimal V0 dashboard for launching and reviewing research runs."""

import html
import json
import os
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from config import (
    ACTOR_LANGUAGES,
    ACTOR_MARKETS,
    ACTOR_INDUSTRIES,
    ACTOR_INDUSTRIES_BY_LANGUAGE,
    ACTOR_MARKETS_BY_INDUSTRY,
    ARTIST_L2_TAGS,
    DEFAULT_SOURCES,
    ENTITIES,
    ARTIST_CATEGORIES,
    ARTIST_GENRES,
    ARTIST_LANGUAGES,
    INDIAN_CITIES,
    INDIAN_STATES,
    INDIAN_ZONES,
    LOCATION_SCOPES,
    OUTPUTS,
    REFRESH_MODES,
    ROOT,
)
from source_collectors.youtube import profile_lead_type


_submission_lock = threading.Lock()
_recent_submissions: dict[str, float] = {}


def duplicate_submission(form: dict[str, list[str]]) -> bool:
    """Reject the same form submission repeated within 30 seconds."""
    key = json.dumps(form, sort_keys=True)
    now = time.monotonic()
    with _submission_lock:
        for old_key, timestamp in list(_recent_submissions.items()):
            if now - timestamp > 30:
                del _recent_submissions[old_key]
        if key in _recent_submissions:
            return True
        _recent_submissions[key] = now
        return False


def runs() -> list[Path]:
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    return sorted((p for p in OUTPUTS.iterdir() if p.is_dir()), reverse=True)


def options(values: tuple[str, ...], selected: str = "") -> str:
    return "".join(
        f'<option value="{html.escape(value)}"'
        f'{" selected" if value == selected else ""}>{html.escape(value)}</option>'
        for value in values
    )


def select(name: str, values: tuple[str, ...], selected: str = "", element_id: str = "", required: bool = False) -> str:
    id_attr = f' id="{html.escape(element_id)}"' if element_id else ""
    required_attr = " required" if required else ""
    return f'<select name="{name}"{id_attr}{required_attr}>{options(values, selected)}</select>'


def custom_input(name: str, placeholder: str) -> str:
    return (f'<input class="custom-input" data-for="{name}" '
            f'name="{name}_custom" placeholder="{html.escape(placeholder)}" '
            "hidden disabled>")


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except (OSError, json.JSONDecodeError):
        return default


def contact_has_value(contact: dict) -> bool:
    nested = contact.get("contacts")
    return bool(contact.get("phone") or contact.get("email") or contact.get("website") or
                (any(nested.values()) if isinstance(nested, dict) else False))


def run_summary(run: Path) -> dict:
    meta = read_json(run / "run_metadata.json", {}) or {}
    findings = read_json(run / "findings.json", {}) or {}
    apify = read_json(run / "apify_data.json", {}) or {}
    brief = meta.get("brief", {})
    source_yield = findings.get("source_yield", {})
    normalized_yield = {}
    for source in ("instagram", "youtube", "reddit", "web", "x"):
        raw = source_yield.get(source, {})
        data = dict(raw) if isinstance(raw, dict) else {}
        collector = apify.get(source, {}) if isinstance(apify.get(source, {}), dict) else {}
        if collector:
            data.setdefault("status", collector.get("status", "collected"))
            data.setdefault("count", collector.get("count", 0))
            data.setdefault("batch_count", collector.get("batch_count", 0))
        if source == "youtube":
            data.setdefault("youtube_channels_discovered", data.get("total_candidates", collector.get("count", 0)))
            data.setdefault("youtube_channels_profiled", data.get("channels_analyzed", data.get("channels_selected", collector.get("batch_count", 0))))
            data.setdefault("channels_with_activity_in_30d_window", 0)
        if source == "instagram":
            data.setdefault("count", data.get("posts_collected", collector.get("count", 0)))
            data.setdefault("profiles", data.get("profiles_enriched", 0))
        normalized_yield[source] = data
    artist_findings = findings.get("findings", []) or []
    raw_contacts = findings.get("contacts", []) or []
    contacts = [raw_contacts] if isinstance(raw_contacts, dict) else raw_contacts
    trending = sum(
        (status := str(item.get("trend_status") or item.get("status") or "").lower()) in {"trending", "rising", "active"}
        or status.startswith("confirmed")
        for item in artist_findings if isinstance(item, dict)
    )
    india_terms = {"india", "indian", "ncr", "bangalore", "bollywood"}
    india_terms.update(value.lower() for value in (*INDIAN_CITIES, *INDIAN_STATES, *INDIAN_ZONES) if value.lower() != "other")
    indian = sum(any(term in str(item.get("country") or item.get("origin") or item.get("location") or "").lower()
                     for term in india_terms)
                 for item in artist_findings if isinstance(item, dict))
    candidates = 0
    for source in source_yield.values():
        if isinstance(source, dict):
            candidates += int(source.get("total_candidates", source.get("youtube_channels_discovered", 0)) or 0)
    if not candidates:
        candidates = sum(int(data.get("count", 0) or 0) for data in apify.values() if isinstance(data, dict))
    return {
        "run": run,
        "meta": meta,
        "brief": brief,
        "findings": artist_findings,
        "contacts": contacts,
        "warnings": findings.get("warnings", []) or [],
        "source_yield": normalized_yield,
        "apify": apify,
        "candidates": candidates,
        "profiles": len(artist_findings),
        "contacts_count": sum(1 for contact in contacts if isinstance(contact, dict) and contact_has_value(contact)),
        "trending": trending,
        "indian": indian,
    }


def stat_card(label: str, value, note: str = "", tone: str = "") -> str:
    return (f'<div class="stat {html.escape(tone)}"><div class="stat-value">{html.escape(str(value))}</div>'
            f'<div class="stat-label">{html.escape(label)}</div><div class="stat-note">{html.escape(note)}</div></div>')


def source_card(source: str, data: dict) -> str:
    status = data.get("status", "not selected")
    if source == "youtube":
        headline = data.get("youtube_channels_profiled", data.get("channels_selected", data.get("batch_count", 0)))
        note = f"{data.get('youtube_channels_discovered', data.get('total_candidates', data.get('count', 0)))} candidates · {data.get('channels_with_activity_in_30d_window', 0)} active in 30d"
    elif source == "instagram":
        enrichment = data.get("profile_enrichment", {})
        if not isinstance(enrichment, dict):
            enrichment = {}
        headline = enrichment.get("profiles") or data.get("profiles") or data.get("profiles_returned", 0)
        note = f"{data.get('count', 0)} posts · {enrichment.get('selected_geography', {}).get('india', 0)} India-signalled"
    elif source == "reddit":
        headline = data.get("count", 0)
        note = "supporting discussion evidence"
    else:
        headline = data.get("results_returned", data.get("count", 0))
        note = f"{data.get('queries_run', 0)} queries · delegated research evidence"
    return (f'<div class="source-card"><div class="source-top"><span class="source-name">{html.escape(source.upper())}</span>'
            f'<span class="pill {html.escape(status)}">{html.escape(status)}</span></div>'
            f'<div class="source-number">{html.escape(str(headline))}</div><div class="muted">{html.escape(note)}</div></div>')


def entity_slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value).lower()).strip("-")[:100] or "unknown"


def finding_card(item: dict, fallback_scope: str = "", kind: str = "artist", brief: dict | None = None) -> str:
    name = item.get("stage_name") or item.get("stageName") or item.get("name") or item.get("actor") or item.get("topic") or "Unnamed finding"
    status = item.get("trend_status") or item.get("status") or "discovered"
    location = item.get("location") or item.get("origin") or item.get("country")
    location_label = str(location) if location else (f"Research scope: {fallback_scope}" if fallback_scope else "Location not specified")
    source = item.get("source") or "research"
    platforms = item.get("platforms") or []
    links = []
    for platform in platforms:
        if not isinstance(platform, dict) or not platform.get("url"):
            continue
        label = {"youtube": "YouTube", "instagram": "Instagram", "reddit": "Reddit", "web": "Web", "x": "X"}.get(
            str(platform.get("platform", "source")).lower(), str(platform.get("platform", "Source")).title())
        handle = platform.get("handle")
        links.append(f'<a class="link-chip" href="{html.escape(str(platform["url"]))}" target="_blank">{html.escape(label)}{f" · {html.escape(str(handle))}" if handle else ""} ↗</a>')
    for key, label in (("instagram_url", "Instagram"), ("youtube_channel_url", "YouTube"), ("website", "Website")):
        url = item.get(key)
        if url and not any(str(url) in link for link in links):
            links.append(f'<a class="link-chip" href="{html.escape(str(url))}" target="_blank">{label} ↗</a>')
    link = f'<div class="link-row">{"".join(links)}</div>' if links else '<span class="muted">No profile link available</span>'
    detail = (item.get("performance_context") or item.get("profile") or item.get("credentials") or
              item.get("trend_note") or item.get("summary") or item.get("notes") or item.get("management") or "No additional finding summary available.")
    entity_type = "actors" if kind == "actor" else "artists"
    entity_link = f'<p><a href="/entity/{entity_type}/{entity_slug(str(name))}">Open cumulative profile ↗</a></p>'
    evidence = item.get("trend_evidence") or item.get("supporting_history") or item.get("evidence") or []
    if isinstance(evidence, dict):
        evidence = [evidence]
    elif not isinstance(evidence, list):
        evidence = []
    evidence = [row for row in evidence if isinstance(row, dict) and
                (row.get("title") or row.get("note") or row.get("account") or row.get("channel")) and
                (row.get("url") or row.get("publishedAt") or row.get("date") or row.get("latest_activity_date"))]
    evidence_html = "".join(
        f'<div class="content-item"><strong>{html.escape(str(row.get("title") or row.get("note") or row.get("account") or row.get("channel")))}</strong>'
        f'<br><span class="muted">{html.escape(format_timestamp(row.get("publishedAt") or row.get("date") or row.get("latest_activity_date") or row.get("date_range")))}</span>'
        f'{f"<br><a href=\"{html.escape(str(row["url"]))}\" target=\"_blank\">Open evidence ↗</a>" if row.get("url") else ""}</div>'
        for row in evidence[:3] if isinstance(row, dict)
    )
    return (f'<article class="finding"><div class="finding-head"><h3>{html.escape(str(name))}</h3>'
            f'<span class="pill {html.escape(str(status).lower().replace(" ", "-"))}">{html.escape(str(status))}</span></div>'
            f'<div class="muted">{html.escape(location_label)} · {html.escape(str(source))}</div>'
            f'<p>{html.escape(str(detail))[:500]}</p>{link}{entity_link}'
            f'{f"<div class=\"evidence-line\"><strong>Recent evidence:</strong>{evidence_html}</div>" if evidence_html else ""}</article>')


def contact_card(item: dict) -> str:
    if "official_personal_accounts_found" in item:
        notes = item.get("notes") or []
        details = " ".join(str(note) for note in notes) if isinstance(notes, list) else str(notes)
        state = "Found" if item.get("official_personal_accounts_found") else "Not confirmed"
        return (f'<article class="contact"><div class="finding-head"><h3>Contact availability</h3>'
                f'<span class="pill">{html.escape(state)}</span></div>'
                f'<p>{html.escape(details or "No public contact assessment available.")}</p></article>')
    name = item.get("artist_name") or item.get("artist") or item.get("name") or "Unnamed contact"
    nested = item.get("contacts") if isinstance(item.get("contacts"), dict) else {}
    values = [item.get("phone"), item.get("email"), item.get("value"), item.get("website"), *nested.values()]
    details = " · ".join(dict.fromkeys(str(value) for value in values if value))
    verified = "Verified" if item.get("verified") else "Unverified / review"
    source_url = item.get("source_url") or item.get("website")
    source_link = f'<a href="{html.escape(str(source_url))}" target="_blank">Open source ↗</a>' if source_url else ""
    return (f'<article class="contact"><div class="finding-head"><h3>{html.escape(str(name))}</h3>'
            f'<span class="pill">{html.escape(verified)}</span></div><p>{html.escape(details or "No direct value")}</p>'
            f'<div class="muted">{html.escape(str(item.get("contact_source") or item.get("source") or "Public source"))} {source_link}</div></article>')


def evidence_text(value, limit: int = 420) -> str:
    return html.escape(str(value or "")).replace("\n", " ")[:limit]


def format_timestamp(value) -> str:
    if not value:
        return "Not dated"
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(ZoneInfo("Asia/Kolkata")).strftime("%d %b %Y, %I:%M %p IST")
    except (TypeError, ValueError):
        return str(value)


def link_chips(value) -> str:
    values = value if isinstance(value, list) else [value]
    chips = []
    for item in values:
        if isinstance(item, dict):
            url = item.get("url")
            label = item.get("text") or url
        else:
            url, label = str(item or ""), str(item or "")
        if not url or not str(url).startswith(("http://", "https://")):
            continue
        label = re.sub(r"^https?://", "", str(label)).rstrip("/")
        chips.append(f'<a class="link-chip" href="{html.escape(str(url))}" target="_blank">{html.escape(label)} ↗</a>')
    return f'<div class="link-row">{"".join(chips)}</div>' if chips else "—"


def metadata_chips(values: list[tuple[str, object]]) -> str:
    chips = [f'<span class="meta-chip">{html.escape(label)}: {html.escape(str(value))}</span>'
             for label, value in values if value not in (None, "", [], {})]
    return f'<div class="profile-meta">{"".join(chips)}</div>'


def platform_profile_matches(profile: dict, sources: list) -> dict[str, list[dict]]:
    """Find source records linked by a saved URL/handle or exact profile name."""
    name = re.sub(r"[^a-z0-9]+", "", str(profile.get("name", "")).lower())
    source_urls = {str(item.get("url", "")).rstrip("/").lower() for item in sources if isinstance(item, dict) and item.get("url")}
    matches = {"instagram": [], "youtube": []}
    for platform in matches:
        for path in sorted((ENTITIES / platform).glob("*.json")) if (ENTITIES / platform).is_dir() else []:
            record = read_json(path, {}) or {}
            raw = record.get("profile") if platform == "instagram" else record.get("channel")
            raw = raw if isinstance(raw, dict) else {}
            urls = {str(raw.get(key, "")).rstrip("/").lower() for key in ("url", "inputUrl", "channelUrl", "channelHandle") if raw.get(key)}
            urls.update(str(video.get("url", "")).rstrip("/").lower() for video in record.get("videos", []) if isinstance(video, dict) and video.get("url"))
            urls.update(str(post.get("url", "")).rstrip("/").lower() for post in record.get("posts", []) if isinstance(post, dict) and post.get("url"))
            labels = [raw.get(key) for key in ("username", "fullName", "channelName", "channelHandle") if raw.get(key)]
            exact_name = name and any(re.sub(r"[^a-z0-9]+", "", str(label).lower()) == name for label in labels)
            if source_urls.intersection(urls) or exact_name:
                record["_path"] = str(path)
                matches[platform].append(record)
    return matches


def format_count(value) -> str:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return "—"
    if not number:
        return "—"
    if number >= 1_000_000_000:
        return f"{number / 1_000_000_000:.1f}B".replace(".0B", "B")
    if number >= 1_000_000:
        return f"{number / 1_000_000:.1f}M".replace(".0M", "M")
    if number >= 1_000:
        return f"{number / 1_000:.1f}K".replace(".0K", "K")
    return str(int(number))


def platform_section(title: str, records: list[dict], platform: str) -> str:
    if not records:
        return f'<section class="panel"><h2>{html.escape(title)}</h2><div class="muted">No matched {html.escape(platform)} source record.</div></section>'
    cards = []
    for record in records[:10]:
        raw = record.get("profile") if platform == "instagram" else record.get("channel")
        raw = raw if isinstance(raw, dict) else {}
        activity = record.get("activity_summary") if isinstance(record.get("activity_summary"), dict) else {}
        items = record.get("posts") if platform == "instagram" else record.get("videos")
        items = items if isinstance(items, list) else []
        label = ((raw.get("fullName") or raw.get("username")) if platform == "instagram"
                 else (raw.get("channelName") or raw.get("channelHandle")))
        source_url = raw.get("url") or raw.get("channelUrl")
        items = sorted(items, key=lambda item: int(item.get("viewCount") or item.get("likesCount") or 0) if isinstance(item, dict) else 0, reverse=True)
        item_rows = []
        for item in items[:8]:
            if not isinstance(item, dict):
                continue
            engagement = item.get("likesCount") or item.get("viewCount") or item.get("views")
            engagement_text = f' · {format_count(engagement)} engagement' if engagement else ""
            item_url = item.get("url")
            item_link = f'<br><a href="{html.escape(str(item_url))}" target="_blank">Open item ↗</a>' if item_url else ""
            item_rows.append(
                f'<div class="content-item"><strong>{html.escape(str(item.get("title") or item.get("caption") or item_url or "Recent item"))}</strong>'
                f'<br><span class="muted">{html.escape(format_timestamp(item.get("timestamp") or item.get("publishedAt") or item.get("uploadDate")))}</span>'
                f'{engagement_text}{item_link}</div>'
            )
        profile_link = f' · <a href="{html.escape(str(source_url))}" target="_blank">Open profile ↗</a>' if source_url else ""
        description = raw.get("biography") or raw.get("description") or ""
        description_html = f'<br>{html.escape(str(description))}' if description else ""
        cards.append(
            f'<article class="platform-card"><div class="platform-card-head"><div><h3>{html.escape(str(label or "Source record"))}</h3><div class="muted">{html.escape(platform.title())}{profile_link}</div></div><span class="pill">{len(items)} items</span></div>'
            f'<div class="metric-row"><span class="metric-chip"><strong>{format_count(raw.get("followersCount") or raw.get("subscriberCount"))}</strong> {"followers" if platform == "instagram" else "subscribers"}</span>'
            f'<span class="metric-chip"><strong>{format_count(activity.get("items_in_30d") or activity.get("recent_items"))}</strong> in 30d</span>'
            f'<span class="metric-chip"><strong>{html.escape(format_timestamp(activity.get("latest_activity_date")))}</strong> latest</span></div>'
            f'{description_html}<div class="platform-content">{"".join(item_rows) or "<div class=\"muted\">No recent content returned.</div>"}</div></article>'
        )
    return f'<section class="panel"><div class="panel-head"><div><h2>{html.escape(title)}</h2><div class="muted">Source accounts and activity associated with this entity</div></div><span class="pill">{len(records)} matched</span></div><div class="platform-grid">{"".join(cards)}</div></section>'


def activity_line(summary: dict) -> str:
    return (f'Latest: {format_timestamp(summary.get("latest_activity_date"))} · '
            f'7d: {summary.get("items_in_7d", 0)} items · '
            f'30d: {summary.get("items_in_30d", 0)} items')


def profile_card(source: str, profile: dict) -> str:
    if source == "instagram":
        name = profile.get("fullName") or profile.get("username") or "Instagram profile"
        handle = f'@{profile.get("username")}' if profile.get("username") else ""
        followers = profile.get("followersCount")
        subtitle = metadata_chips([("Handle", handle), ("Followers", f"{followers:,}" if isinstance(followers, int) else None),
                                  ("Verified", "Yes" if profile.get("verified") else None), ("Type", "Business" if profile.get("isBusinessAccount") else None)])
        posts = (profile.get("latestPosts") or []) + (profile.get("latestIgtvVideos") or [])
        evidence = [
            ("Bio", profile.get("biography")),
            ("Contact", " · ".join(str(v) for v in (profile.get("businessEmail"), profile.get("businessPhoneNumber")) if v)),
            ("Activity", activity_line(profile.get("activity_summary", {}))),
        ]
        items = "".join(f'<div class="content-item"><strong>{html.escape(format_timestamp(post.get("timestamp") or post.get("takenAt")))}</strong><br>{evidence_text(post.get("caption"), 260)}<br><span class="muted">{post.get("likesCount", 0)} likes · {post.get("commentsCount", 0)} comments</span></div>' for post in posts[:4])
        link = profile.get("url")
        links = link_chips(profile.get("externalUrls") or profile.get("externalUrl"))
    else:
        name = profile.get("channelName") or "YouTube channel"
        handle = profile.get("channelHandle") or ""
        subscribers = profile.get("subscriberCount")
        subtitle = metadata_chips([("Handle", handle), ("Subscribers", f"{subscribers:,}" if isinstance(subscribers, int) else None),
                                  ("Location", profile.get("country") or profile.get("location")),
                                  ("Verified", "Yes" if profile.get("isVerified") else None),
                                  ("Lead", profile.get("lead_type"))])
        videos = profile.get("videos") or profile.get("latestVideos") or profile.get("videoData") or []
        evidence = [
            ("Description", profile.get("description") or profile.get("channelDescription")),
            ("Activity", activity_line(profile.get("activity_summary", {}))),
            ("Profile source", profile.get("profile_source") or "channel actor"),
        ]
        items = "".join(f'<div class="content-item"><strong>{html.escape(format_timestamp(video.get("publishedAt") or video.get("uploadDate") or video.get("date")))}</strong><br>{evidence_text(video.get("title"), 260)}<br><span class="muted">{video.get("viewCount", 0)} views · {video.get("likesCount", video.get("likes", 0))} likes · {video.get("commentsCount", 0)} comments</span></div>' for video in videos[:4])
        link = profile.get("channelUrl")
        links = link_chips(profile.get("links") or profile.get("channelLinks"))
    body = "".join(f'<div class="evidence-line"><strong>{html.escape(label)}:</strong> {evidence_text(value) or "—"}</div>' for label, value in evidence)
    body += f'<div class="evidence-line"><strong>Links:</strong> {links}</div>'
    body += f'<div class="evidence-line"><strong>Recent {"posts" if source == "instagram" else "videos"}:</strong></div>{items or "<div class=\"muted\">No recent content returned in this run.</div>"}'
    return (f'<details class="profile-card"><summary><h3>{html.escape(str(name))}</h3>{subtitle}<div class="muted" style="margin-top:7px">{source.title()}</div></summary>'
            f'<div class="profile-body">{body}{f"<p><a href=\"{html.escape(str(link))}\" target=\"_blank\">Open profile ↗</a></p>" if link else ""}</div></details>')


def collected_profiles(run: Path, kind: str = "artist") -> str:
    data = read_json(run / "apify_data.json", {}) or {}
    cards = []
    instagram = data.get("instagram", {}) or {}
    if kind != "actor":
        for profile in instagram.get("profiles", [])[:50]:
            if isinstance(profile, dict):
                cards.append(profile_card("instagram", profile))
    youtube = data.get("youtube", {}) or {}
    videos_by_channel = {}
    for video in youtube.get("items", []):
        if isinstance(video, dict) and video.get("channelId"):
            videos_by_channel.setdefault(video["channelId"], []).append(video)
    unique = {}
    for profile in youtube.get("channel_profiles", []):
        if not isinstance(profile, dict):
            continue
        key = profile.get("channelId") or profile.get("channelUrl") or profile.get("channelName")
        if key and key not in unique:
            profile = dict(profile)
            profile["lead_type"] = profile.get("lead_type") or profile_lead_type(profile, "artist")
            if not profile.get("videos") and profile.get("channelId") in videos_by_channel:
                profile["videos"] = videos_by_channel[profile["channelId"]]
                profile["profile_source"] = f'{profile.get("profile_source") or "channel actor"} + search videos'
            unique[key] = profile
    cards.extend(profile_card("youtube", profile) for profile in list(unique.values())[:50])
    return "".join(cards)


def research_inputs(run: Path) -> str:
    metadata = read_json(run / "run_metadata.json", {}) or {}
    apify = read_json(run / "apify_data.json", {}) or {}
    brief = metadata.get("brief", {})
    queries = metadata.get("queries", []) or []
    instagram = apify.get("instagram", {}) or {}
    tags = instagram.get("hashtags", []) or []
    metrics = instagram.get("hashtag_metrics", {}) or {}
    scores = instagram.get("hashtag_performance", {}) or {}
    performance = read_json(ROOT / "hashtags" / "performance.json", {}) or {}
    language = brief.get("language") or "all"
    location = brief.get("city") or brief.get("state") or brief.get("zone") or brief.get("location_scope") or "all"
    context_key = "|".join(str(value or "all").strip().lower() for value in (
        brief.get("kind"), brief.get("category") or brief.get("actor") or "all",
        brief.get("genre") or brief.get("movie") or "all", language, location))
    history = performance.get(context_key, {}) if isinstance(performance, dict) else {}
    query_html = "".join(f'<div class="query-item">{html.escape(str(query))}</div>' for query in queries)
    tag_cards = []
    for tag in tags:
        metric = metrics.get(tag, {})
        record = history.get(tag, {}) if isinstance(history, dict) else {}
        score = scores.get(tag, record.get("score"))
        score_text = f"{float(score):.3f}" if isinstance(score, (int, float)) else "—"
        tag_cards.append(f'<div class="tag-card"><h3>#{html.escape(str(tag))}</h3><div class="tag-score">{score_text}</div><div class="muted">{metric.get("matching_posts", 0)} posts · {metric.get("likes", 0)} likes · {metric.get("comments", 0)} comments</div><div class="muted">{record.get("runs", 0)} historical runs · {record.get("recent_posts", 0)} recent posts · {record.get("india_signal_posts", 0)} India signals</div></div>')
    if not query_html and not tag_cards:
        return ""
    return (f'<section class="panel" style="margin-top:18px"><div class="panel-head"><div><h2>Research inputs &amp; hashtag performance</h2><div class="muted">Exact inputs used for this run and the resulting signal quality</div></div></div>'
            f'<div><h3>Queries executed</h3><div class="query-list">{query_html or "<div class=\"muted\">No saved queries</div>"}</div></div>'
            f'{f"<h3 style=\"margin-top:22px\">Instagram hashtags</h3><div class=\"tag-grid\">{"".join(tag_cards)}</div>" if tag_cards else ""}</section>')


def style() -> str:
    return """<style>
    :root{--ink:#162033;--muted:#718096;--line:#e7eaf0;--paper:#f7f8fb;--card:#fff;--purple:#6d5dfc;--mint:#dff8ed;--gold:#fff1c7;--rose:#ffe4e8}
    *{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink);font:14px Inter,ui-sans-serif,system-ui,-apple-system,sans-serif}a{color:#5547e8;text-decoration:none}a:hover{text-decoration:underline}
    .shell{max-width:1240px;margin:auto;padding:28px 28px 64px}.topbar{display:flex;justify-content:space-between;align-items:center;margin-bottom:28px}.brand{font-weight:800;font-size:20px;letter-spacing:-.04em}.brand span{color:var(--purple)}.toplink{color:var(--muted)}
    .hero{background:linear-gradient(120deg,#171d38,#40358d 58%,#7d6bff);border-radius:26px;padding:34px;color:#fff;box-shadow:0 18px 50px #5c50c52b}.hero h1{font-size:38px;line-height:1.05;margin:0 0 12px;letter-spacing:-.06em}.hero p{max-width:700px;color:#e8e7ff;font-size:16px;margin:0}.eyebrow{font-size:11px;text-transform:uppercase;letter-spacing:.16em;color:#bdb7ff;font-weight:800;margin-bottom:12px}
    .stats{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin:18px 0}.stat,.source-card,.panel,.finding,.contact,.run-row{background:var(--card);border:1px solid var(--line);border-radius:17px}.stat{padding:18px;min-height:120px}.stat-value{font-size:30px;font-weight:800;letter-spacing:-.06em}.stat-label{font-weight:700;margin-top:7px}.stat-note,.muted{font-size:12px;color:var(--muted);margin-top:4px}.stat.purple{background:#eeecff}.stat.mint{background:var(--mint)}.stat.gold{background:var(--gold)}.stat.rose{background:var(--rose)}
    .grid{display:grid;grid-template-columns:1.4fr 1fr;gap:18px;margin-top:18px}.panel{padding:22px}.panel h2{font-size:17px;margin:0 0 14px;letter-spacing:-.03em}.panel h3{margin:0}.panel-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}.source-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.source-card{padding:15px}.source-top,.finding-head{display:flex;justify-content:space-between;gap:10px;align-items:center}.source-name{font-size:11px;font-weight:800;letter-spacing:.12em;color:var(--muted)}.source-number{font-size:25px;font-weight:800;margin-top:12px}.pill{display:inline-block;padding:4px 8px;border-radius:999px;background:#eef0f5;color:#566174;font-size:11px;font-weight:700}.pill.collected,.pill.completed,.pill.trending,.pill.rising,.pill.active{background:var(--mint);color:#16724c}.pill.failed,.pill.incomplete{background:var(--rose);color:#ad3046}.pill.discovered,.pill.discovery{background:var(--gold);color:#8b6500}
    .run-list{display:grid;gap:9px}.run-row{padding:14px 16px;display:flex;justify-content:space-between;align-items:flex-start;gap:16px}.run-title{font-weight:750}.run-meta{color:var(--muted);font-size:12px;margin-top:4px}.run-timeline{margin-top:9px;padding-left:10px;border-left:2px solid #dcd9ff;color:#667085;font:11px ui-monospace,monospace;line-height:1.6;max-width:760px}.run-right{text-align:right;white-space:nowrap}.run-right strong{font-size:17px}.form-panel{margin-top:18px}.form-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:10px 18px}label{display:block;margin:8px 0;color:var(--muted);font-weight:650}input,select{width:100%;padding:10px 11px;border:1px solid var(--line);border-radius:10px;background:#fff;color:var(--ink);margin-top:5px}button{border:0;border-radius:11px;background:var(--purple);color:white;padding:11px 16px;font-weight:750;cursor:pointer}.source-checks{display:flex;gap:12px;flex-wrap:wrap}.source-checks label{display:flex;align-items:center;gap:5px}.source-checks input{width:auto;margin:0}.actions{display:flex;justify-content:space-between;align-items:end;margin-top:16px}.actions a{color:var(--muted)}details summary{cursor:pointer;font-weight:800;list-style:none}details summary::-webkit-details-marker{display:none}
    .detail-hero{display:flex;justify-content:space-between;gap:20px;align-items:end;margin:12px 0 22px}.detail-hero h1{font-size:32px;letter-spacing:-.05em;margin:4px 0}.entity-heading{display:flex;align-items:center;gap:16px}.entity-avatar{width:76px;height:76px;border-radius:50%;object-fit:cover;background:#eeecff;box-shadow:0 8px 24px #6d5dfc25}.entity-avatar-empty{display:grid;place-items:center;color:#5145d2;font-size:30px;font-weight:800}.detail-actions{display:flex;gap:10px}.button-link{padding:10px 14px;border-radius:10px;background:#fff;border:1px solid var(--line)}.findings,.profile-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px;align-items:start}.finding,.contact,.profile-card{padding:17px}.finding h3,.contact h3,.profile-card h3{font-size:15px;margin:0}.finding p,.contact p,.profile-card p{line-height:1.5;color:#4f5c70;margin:12px 0}.profile-card{background:#fbfcfe;border:1px solid var(--line);border-radius:14px;align-self:start;min-width:0}.profile-card[open]{grid-column:1/-1}.profile-card summary{cursor:pointer;list-style:none}.profile-card summary::-webkit-details-marker{display:none}.profile-card summary:after{content:'＋';float:right;color:var(--purple);font-size:18px}.profile-card[open] summary:after{content:'−'}.profile-body{border-top:1px solid var(--line);margin-top:13px;padding-top:13px}.profile-meta{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}.meta-chip,.link-chip{display:inline-flex;align-items:center;max-width:100%;padding:5px 8px;border-radius:7px;background:#eef0f5;color:#566174;font-size:11px;font-weight:650}.link-chip{background:#eeecff;color:#5145d2;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.link-row{display:flex;flex-wrap:wrap;gap:7px;margin-top:5px}.content-item{padding:9px 10px;margin:6px 0;background:#fff;border:1px solid var(--line);border-radius:9px;font-size:12px;line-height:1.45}.content-item strong{color:var(--ink)}.platform-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.platform-card{padding:15px;border:1px solid var(--line);border-radius:14px;background:#fbfcfe}.platform-card-head{display:flex;justify-content:space-between;gap:10px;align-items:start}.platform-card h3{margin:0;font-size:15px}.metric-row{display:flex;flex-wrap:wrap;gap:6px;margin:12px 0}.metric-chip{padding:6px 8px;border-radius:8px;background:#fff;border:1px solid var(--line);font-size:11px;color:var(--muted)}.metric-chip strong{color:var(--ink);font-size:12px}.platform-content{margin-top:10px}.media-preview{display:block;width:100%;max-height:260px;object-fit:cover;border-radius:8px;margin-bottom:9px;background:#111}.content-item iframe.media-preview{height:220px;border:0}.media-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.media-card{padding:10px;border:1px solid var(--line);border-radius:12px;background:#fbfcfe;min-width:0}.media-card .media-preview{height:150px}.detail-table{margin-top:8px}.detail-row{display:flex;justify-content:space-between;gap:15px;padding:7px 0;border-bottom:1px solid var(--line)}.detail-row span{color:var(--muted);text-transform:capitalize}.detail-row strong{text-align:right}.film-tags{display:flex;flex-wrap:wrap;gap:8px}.film-tag{padding:7px 10px;border-radius:999px;background:#eeecff;color:#5145d2;font-size:12px;font-weight:650}.award-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}.award-card{padding:11px;border:1px solid var(--line);border-radius:10px;background:#fbfcfe}.award-card span{display:block;color:var(--muted);font-size:12px;margin-top:4px}.source-details{margin-top:13px;border-top:1px solid var(--line);padding-top:11px}.source-details summary{cursor:pointer;font-weight:700;color:#5145d2}.activity-details summary{cursor:pointer;font-weight:750}.activity-details[open] summary{margin-bottom:14px}.activity-timeline{display:grid;gap:10px}.activity-card{padding:13px;border:1px solid var(--line);border-radius:12px;background:#fbfcfe}.activity-top{display:flex;justify-content:space-between;gap:10px;align-items:center}.activity-card p{color:#4f5c70;font-size:13px}.evidence-line{padding:9px 0;border-bottom:1px solid var(--line);font-size:12px;line-height:1.45}.evidence-line:last-child{border-bottom:0}.evidence-line strong{color:var(--ink)}.query-list{display:grid;gap:7px}.query-item{padding:10px 12px;background:#f5f4ff;border-radius:10px;color:#4339a5;font-family:ui-monospace,monospace;font-size:12px}.tag-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:9px}.tag-card{padding:12px;border:1px solid var(--line);border-radius:12px;background:#fff}.tag-card h3{font-size:13px;margin:0 0 8px}.tag-score{font-size:21px;font-weight:800}.warning{padding:11px 13px;background:var(--gold);border-radius:10px;margin:7px 0;color:#715600;font-size:13px}.file-list{display:flex;flex-wrap:wrap;gap:8px}.file-list a{padding:8px 10px;border:1px solid var(--line);border-radius:9px;background:#fff}.back{display:inline-block;margin-bottom:20px;color:var(--muted)}
    @media(max-width:850px){.stats{grid-template-columns:repeat(2,1fr)}.grid,.findings,.profile-grid,.platform-grid{grid-template-columns:1fr}.source-grid{grid-template-columns:repeat(2,1fr)}.media-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.award-grid{grid-template-columns:1fr}.form-grid{grid-template-columns:1fr}.detail-hero{display:block}.shell{padding:18px}.hero h1{font-size:30px}}
    </style>"""


def live_status() -> dict:
    active_statuses = {"started", "running", "synthesizing", "delegated", "claude_pending"}
    terminal_statuses = {"completed", "incomplete", "blocked", "failed"}
    statuses = []
    for run in runs():
        metadata = read_json(run / "run_metadata.json", {}) or {}
        status = metadata.get("status", "unknown")
        progress_path = run / "progress.log"
        progress = progress_path.read_text(encoding="utf-8", errors="replace") if progress_path.exists() else ""
        terminal = status in terminal_statuses
        pid = metadata.get("pid")
        process_alive = False
        if pid:
            try:
                os.kill(int(pid), 0)
                process_alive = True
            except (OSError, TypeError, ValueError):
                process_alive = False
        else:
            # Legacy runs have no PID; only treat a recently updated run as active.
            try:
                process_alive = time.time() - progress_path.stat().st_mtime < 15 * 60
            except OSError:
                process_alive = False
        statuses.append({
            "run_id": run.name,
            "active": not terminal and status in active_statuses and process_alive,
            "status": status,
            "phase": metadata.get("phase", "starting"),
            "message": metadata.get("last_message") or (progress.splitlines()[-1] if progress else "Starting collector..."),
            "progress": progress.splitlines()[-1] if progress else "",
            "timeline": progress.splitlines()[-8:],
        })
    active = [item for item in statuses if item["active"]]
    latest = statuses[0] if statuses else None
    return {"active": bool(active), "run_id": latest["run_id"] if latest else "", "runs": statuses,
            "message": "No runs yet." if not statuses else f"{len(active)} run(s) in progress."}


def inline_markdown(value: str) -> str:
    value = html.escape(value, quote=False)
    value = re.sub(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", r'<a href="\2" target="_blank">\1 ↗</a>', value)
    value = re.sub(r'(?<!["=])(https?://[^\s<]+)', r'<a href="\1" target="_blank">\1 ↗</a>', value)
    value = re.sub(r"`([^`]+)`", r"<code>\1</code>", value)
    value = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", value)
    value = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<em>\1</em>", value)
    return value


def markdown_page(markdown: str, title: str) -> str:
    """Render the findings report for browser reading without a dependency."""
    body, paragraph, list_kind = [], [], None

    def flush_paragraph() -> None:
        nonlocal paragraph
        if paragraph:
            body.append(f'<p>{" ".join(paragraph)}</p>')
            paragraph = []

    def close_list() -> None:
        nonlocal list_kind
        if list_kind:
            body.append(f'</{list_kind}>')
            list_kind = None

    for raw in markdown.splitlines():
        line = raw.strip()
        heading = re.match(r"^(#{1,6})\s+(.*)$", line)
        bullet = re.match(r"^[-*]\s+(.*)$", line)
        numbered = re.match(r"^\d+[.]\s+(.*)$", line)
        if not line:
            flush_paragraph()
            close_list()
        elif heading:
            flush_paragraph(); close_list()
            level = len(heading.group(1))
            body.append(f'<h{level}>{inline_markdown(heading.group(2))}</h{level}>')
        elif bullet or numbered:
            flush_paragraph()
            kind = "ul" if bullet else "ol"
            if list_kind != kind:
                close_list(); body.append(f'<{kind}>')
                list_kind = kind
            body.append(f'<li>{inline_markdown((bullet or numbered).group(1))}</li>')
        elif line.startswith(">"):
            flush_paragraph(); close_list()
            body.append(f'<blockquote>{inline_markdown(line[1:].strip())}</blockquote>')
        elif re.match(r"^[-*_]{3,}$", line):
            flush_paragraph(); close_list(); body.append("<hr>")
        else:
            close_list(); paragraph.append(inline_markdown(line))
    flush_paragraph(); close_list()
    css = style() + '<style>.markdown-page{max-width:960px}.markdown-body{background:#fff;border:1px solid var(--line);border-radius:18px;padding:28px 34px;line-height:1.65}.markdown-body h1{font-size:30px;letter-spacing:-.04em}.markdown-body h2{margin-top:30px;border-bottom:1px solid var(--line);padding-bottom:8px}.markdown-body h3{margin-top:22px}.markdown-body p{color:#4f5c70}.markdown-body li{margin:5px 0;color:#4f5c70}.markdown-body blockquote{border-left:4px solid var(--purple);padding-left:15px;color:var(--muted)}.markdown-body code{background:#f1f0ff;padding:2px 5px;border-radius:4px}</style>'
    return f'<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title>{css}</head><body><main class="shell markdown-page"><header class="topbar"><div class="brand">artist<span>intel</span></div><a class="toplink" href="/">← Research workspace</a></header><article class="markdown-body">{"".join(body)}</article></main></body></html>'


def run_row(item: dict) -> str:
    brief = item["brief"]
    subject = brief.get("category") or brief.get("actor") or brief.get("kind", "Research")
    subsubject = brief.get("genre") or brief.get("movie") or brief.get("industry") or "All signals"
    status = item["meta"].get("status", "unknown")
    return (f'<a class="run-row" href="/run/{html.escape(item["run"].name)}">'
            f'<div><div class="run-title">{html.escape(item["run"].name)}</div>'
            f'<div class="run-meta">{html.escape(str(subject))} · {html.escape(str(subsubject))} · {html.escape(str(brief.get("kind", "").title()))} · '
            f'{html.escape(", ".join(brief.get("sources", [])))} · {html.escape(str(status))}</div></div>'
            f'<div class="run-right"><strong>{item["profiles"]}</strong><div class="run-meta">findings · {item["contacts_count"]} contacts</div></div></a>')


def runs_page() -> str:
    summaries = [run_summary(run) for run in runs()]
    rows = "".join(run_row(item) for item in summaries)
    return f'''<!doctype html><html><head><meta charset="utf-8"><title>All research runs</title>{style()}</head><body><main class="shell">
    <header class="topbar"><div class="brand">artist<span>intel</span></div><a class="toplink" href="/">← Research workspace</a></header>
    <section class="panel"><div class="panel-head"><div><div class="eyebrow">Research archive</div><h1>All runs</h1><div class="muted">Every saved research run, including older runs outside the dashboard preview.</div></div><span class="pill">{len(summaries)} runs</span></div>
    <div class="run-list">{rows or '<div class="muted">No runs yet.</div>'}</div></section>
    </main></body></html>'''


def media_html(item: dict, platform: str) -> str:
    """Render playable/preview media when the source supplies media URLs."""
    if platform == "instagram":
        image = item.get("displayUrl")
        video = item.get("videoUrl")
        if video:
            poster = f' poster="{html.escape(str(image), quote=True)}"' if image else ""
            return f'<video class="media-preview" controls preload="metadata"{poster}><source src="{html.escape(str(video), quote=True)}"></video>'
        if image:
            return f'<img class="media-preview" loading="lazy" src="{html.escape(str(image), quote=True)}" alt="Instagram post preview">'
        return ""
    thumbnail = item.get("thumbnailUrl")
    url = str(item.get("url") or "")
    match = re.search(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{6,})", url)
    if match:
        return f'<iframe class="media-preview" loading="lazy" src="https://www.youtube.com/embed/{html.escape(match.group(1), quote=True)}" title="YouTube video" allowfullscreen></iframe>'
    if thumbnail:
        return f'<img class="media-preview" loading="lazy" src="{html.escape(str(thumbnail), quote=True)}" alt="YouTube video thumbnail">'
    return ""


def entity_page(entity_type: str, entity_id: str) -> str:
    folder = ENTITIES / entity_type / Path(entity_id).name
    if not folder.is_dir() or entity_slug(entity_id) != entity_id:
        return "Not found"
    profile = read_json(folder / "profile.json", {}) or {}
    activity = read_json(folder / "activity.json", {}) or {}
    sources = read_json(folder / "sources.json", []) or []
    name = profile.get("name") or entity_id
    kind = "Actor" if entity_type == "actors" else "Artist"

    def value_text(value) -> str:
        if isinstance(value, dict):
            return " · ".join(f"{key}: {value}" for key, value in value.items() if value not in (None, "", [], {}))
        return str(value or "")

    def list_section(title: str, values) -> str:
        if not values:
            return ""
        if title == "Videos" and isinstance(values, list):
            values = sorted(values, key=lambda value: int(value.get("viewCount") or value.get("views") or 0) if isinstance(value, dict) else 0, reverse=True)
        rows = []
        for value in values[:30] if isinstance(values, list) else [values]:
            if isinstance(value, dict):
                label = value.get("title") or value.get("name") or value.get("url") or value.get("note") or value_text(value)
                url = value.get("url")
                media = media_html(value, "instagram" if title == "Instagram posts" else "youtube" if title == "Videos" else "")
                rows.append(f'<div class="content-item">{media}<strong>{html.escape(str(label))}</strong>{f"<br><a href=\"{html.escape(str(url))}\" target=\"_blank\">Open source ↗</a>" if url else ""}</div>')
            else:
                rows.append(f'<div class="content-item">{html.escape(str(value))}</div>')
        return f'<section class="panel"><h2>{html.escape(title)}</h2>{"".join(rows)}</section>'

    def personal_details_section(value) -> str:
        if not isinstance(value, dict) or not value:
            return '<div class="muted">No public personal details captured.</div>'
        rows = "".join(f'<div class="detail-row"><span>{html.escape(str(key).replace("_", " ").title())}</span><strong>{html.escape(value_text(item))}</strong></div>'
                       for key, item in value.items() if item not in (None, "", [], {}))
        return rows or '<div class="muted">No public personal details captured.</div>'

    def filmography_section(values) -> str:
        tags = []
        for value in values if isinstance(values, list) else []:
            if not isinstance(value, dict):
                tags.append(f'<span class="film-tag">{html.escape(str(value))}</span>')
                continue
            known_for = value.get("known_for") if isinstance(value.get("known_for"), list) else []
            for title in known_for:
                tags.append(f'<span class="film-tag">{html.escape(str(title))}</span>')
            if value.get("title"):
                year = f' · {value["year"]}' if value.get("year") else ""
                tags.append(f'<span class="film-tag">{html.escape(str(value["title"]))}{html.escape(year)}</span>')
        return f'<section class="panel"><h2>Filmography</h2><div class="film-tags">{"".join(tags) or "<span class=\"muted\">No filmography captured.</span>"}</div></section>'

    def awards_section(values) -> str:
        cards = []
        for value in values if isinstance(values, list) else []:
            if not isinstance(value, dict):
                cards.append(f'<div class="content-item">{html.escape(str(value))}</div>')
                continue
            for group in ("wins", "recent_nominations"):
                for award in value.get(group, []) if isinstance(value.get(group), list) else []:
                    if isinstance(award, dict):
                        title = award.get("award") or group.replace("_", " ").title()
                        detail = " · ".join(str(award[key]) for key in ("film", "year") if award.get(key))
                        cards.append(f'<div class="award-card"><strong>{html.escape(str(title))}</strong><span>{html.escape(detail or group.replace("_", " ").title())}</span></div>')
            if value.get("note"):
                cards.append(f'<div class="content-item">{html.escape(str(value["note"]))}</div>')
        return f'<section class="panel"><h2>Awards</h2><div class="award-grid">{"".join(cards) or "<span class=\"muted\">No awards captured.</span>"}</div></section>'

    def media_section(title: str, values: list, platform: str) -> str:
        values = values if isinstance(values, list) else []
        if title == "Videos":
            values = sorted(values, key=lambda value: int(value.get("viewCount") or value.get("views") or 0) if isinstance(value, dict) else 0, reverse=True)
        cards = []
        for value in values[:24]:
            if not isinstance(value, dict):
                continue
            media = media_html(value, platform)
            label = value.get("title") or value.get("caption") or value.get("url") or "Media item"
            metrics = " · ".join(f'{label}: {format_count(value[key])}' for label, key in (("Views", "viewCount"), ("Likes", "likesCount"), ("Comments", "commentsCount")) if value.get(key) is not None)
            link = f'<a href="{html.escape(str(value["url"]), quote=True)}" target="_blank">Open source ↗</a>' if value.get("url") else ""
            cards.append(f'<article class="media-card">{media}<strong>{html.escape(str(label))}</strong><div class="muted">{html.escape(metrics or format_timestamp(value.get("timestamp") or value.get("publishedAt")))}</div>{link}</article>')
        return f'<section class="panel"><div class="panel-head"><h2>{html.escape(title)}</h2><span class="pill">{len(values)} items</span></div><div class="media-grid">{"".join(cards) or "<span class=\"muted\">No media captured.</span>"}</div></section>'

    metadata = metadata_chips([
        ("Type", kind), ("Language", profile.get("language")), ("Market", profile.get("market")),
        ("Industry", profile.get("industry")), ("Confidence", profile.get("identity_confidence")),
    ])
    focused_link = ""
    if entity_type == "actors":
        focused_query = urlencode({key: value for key, value in {
            "kind": "actor", "actor": name, "language": profile.get("language"),
            "industry": profile.get("industry"), "market": profile.get("market"),
        }.items() if value})
        focused_link = f'<a class="button-link" href="/focus?{focused_query}">Run focused research →</a>'
    trend = profile.get("trend_snapshot") or {}
    source_links = link_chips(sources)
    platform_matches = platform_profile_matches(profile, sources)
    avatar = ""
    for record in platform_matches["instagram"] + platform_matches["youtube"]:
        raw = record.get("profile") or record.get("channel") or {}
        avatar = raw.get("profilePicUrlHD") or raw.get("profilePicUrl") or raw.get("avatarUrl") or ""
        if avatar:
            break
    avatar_html = (f'<img class="entity-avatar" src="{html.escape(str(avatar), quote=True)}" alt="{html.escape(str(name))} profile picture">'
                   if avatar else f'<div class="entity-avatar entity-avatar-empty">{html.escape(str(name)[:1].upper())}</div>')
    snapshots = activity.get("snapshots", []) if isinstance(activity, dict) else []
    snapshot_html = "".join(
        f'<article class="activity-card"><div class="activity-top"><strong>{html.escape(str(snapshot.get("run_id", "Run snapshot")))}</strong><span class="pill">{html.escape(str(snapshot.get("trend_status") or "discovered"))}</span></div><div class="muted">Captured {format_timestamp(snapshot.get("captured_at"))}</div><p>{evidence_text(snapshot.get("summary"), 500) or "No summary captured."}</p>{list_section("Evidence", snapshot.get("evidence"))}</article>'
        for snapshot in snapshots[-10:] if isinstance(snapshot, dict)
    )
    return f'''<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(str(name))}</title>{style()}</head><body><main class="shell">
    <header class="topbar"><div class="brand">artist<span>intel</span></div><a class="toplink" href="/">← Research workspace</a></header>
    <div class="detail-hero"><div class="entity-heading">{avatar_html}<div><div class="eyebrow">Cumulative {kind.lower()} profile</div><h1>{html.escape(str(name))}</h1>{metadata}</div></div><div class="detail-actions">{focused_link}<a class="button-link" href="/runs">All runs ↗</a></div></div>
    <section class="panel"><h2>Profile</h2><div class="evidence-line"><strong>Biography:</strong> {evidence_text(profile.get("biography")) or "No biography captured."}</div><div class="evidence-line"><strong>Personal details:</strong><div class="detail-table">{personal_details_section(profile.get("personal_details"))}</div></div><div class="evidence-line"><strong>Services:</strong> {evidence_text(profile.get("services")) or "—"}</div><div class="evidence-line"><strong>Genres:</strong> {evidence_text(profile.get("genres")) or "—"}</div><details class="source-details"><summary>Official and evidence links · {len(sources)} saved</summary><p class="muted">Use these links when ops needs to verify identity, awards, filmography, or activity evidence.</p>{source_links}</details></section>
    {filmography_section(profile.get("filmography"))}
    {list_section("Upcoming projects", profile.get("upcoming_projects"))}
    {awards_section(profile.get("awards"))}
    {list_section("News", profile.get("news"))}
    {media_section("YouTube videos", profile.get("videos"), "youtube")}
    {media_section("Instagram images", [post for post in profile.get("posts", []) if isinstance(post, dict) and post.get("displayUrl") and not post.get("videoUrl")], "instagram")}
    {media_section("Instagram posts", [post for post in profile.get("posts", []) if not (isinstance(post, dict) and post.get("displayUrl") and not post.get("videoUrl"))], "instagram")}
    {list_section("Contacts", profile.get("contacts"))}
    {platform_section("Instagram profile and activity", platform_matches["instagram"], "Instagram")}
    {platform_section("YouTube channel and activity", platform_matches["youtube"], "YouTube")}
    <section class="panel"><div class="panel-head"><div><h2>Trend snapshot · latest run</h2><div class="muted">A run-level assessment of recent evidence, not a permanent popularity score.</div></div><span class="pill">{html.escape(str(trend.get("run_id") or "run unavailable"))}</span></div><div class="evidence-line"><strong>Assessment:</strong> {html.escape(str(trend.get("status") or "No trend status"))}</div><div class="evidence-line"><strong>What it means:</strong> {evidence_text(trend.get("summary")) or "The sources did not provide a clear trend explanation."}</div>{list_section("Evidence used for this assessment", trend.get("evidence"))}</section>
    {f'<details class="panel activity-details"><summary>Activity history · {len(snapshots)} snapshots</summary><div class="activity-timeline">{snapshot_html}</div></details>' if snapshot_html else ''}
    </main></body></html>'''


def focus_page(query: dict[str, list[str]]) -> str:
    values = {key: query.get(key, [""])[0] for key in ("kind", "actor", "language", "industry", "market")}
    subject = values.get("actor") or "Actor"
    hidden = "".join(f'<input type="hidden" name="{html.escape(key)}" value="{html.escape(value)}">' for key, value in values.items() if value)
    hidden += '<input type="hidden" name="refresh_mode" value="discovery"><input type="hidden" name="sources" value="instagram,web,x,youtube,reddit">'
    return f'''<!doctype html><html><head><meta charset="utf-8"><title>Focused research</title>{style()}</head><body><main class="shell">
    <header class="topbar"><div class="brand">artist<span>intel</span></div><a class="toplink" href="/">← Research workspace</a></header>
    <section class="panel"><div class="eyebrow">Focused enrichment</div><h1>{html.escape(subject)}</h1>
    <p class="muted">This run will research the named actor using profile, activity, trend, news, and source-specific queries.</p>
    {metadata_chips([("Language", values.get("language")), ("Industry", values.get("industry")), ("Market", values.get("market")), ("Sources", "Instagram · Web · X · YouTube · Reddit")])}
    <form method="post" action="/run"><input type="hidden" name="kind" value="actor">{hidden}<div class="actions"><a href="/">Cancel</a><button type="submit">Start focused research →</button></div></form></section>
    </main></body></html>'''


def page(message: str = "") -> str:
    l2_tags_json = json.dumps(ARTIST_L2_TAGS)
    actor_industries_json = json.dumps(ACTOR_INDUSTRIES_BY_LANGUAGE)
    actor_markets_json = json.dumps(ACTOR_MARKETS_BY_INDUSTRY)
    summaries = [run_summary(run) for run in runs()[:8]]
    latest = summaries[0] if summaries else None
    latest_title = "No completed research yet"
    latest_context = "Start a focused run to populate the workspace."
    if latest:
        brief = latest["brief"]
        latest_title = f'{brief.get("category") or brief.get("actor") or brief.get("kind", "Research")} / {brief.get("genre") or brief.get("movie") or brief.get("industry") or "All signals"}'
        latest_context = f'{latest["run"].name} · {brief.get("kind", "research").title()} · {brief.get("refresh_mode", "discovery").title()} · {", ".join(brief.get("sources", []))}'
    cards = "".join((stat_card("Candidates", latest["candidates"], "Across selected sources", "purple"),
                      stat_card("Profiles", latest["profiles"], "Synthesized findings", "mint"),
                      stat_card("India profiles", latest["indian"], "Location-confirmed / signalled", "gold"),
                      stat_card("Contacts", latest["contacts_count"], "Public contact leads", "rose"),
                      stat_card("Trending", latest["trending"], "Inside the 30-day window", ""))) if latest else ""
    source_cards = "".join(source_card(source, latest["source_yield"].get(source, {})) for source in ("instagram", "youtube", "reddit", "web", "x")) if latest else ""
    run_rows = [run_row(item) for item in summaries]
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Artist Intelligence</title>{style()}</head><body><main class="shell">
    <header class="topbar"><div class="brand">artist<span>intel</span></div><div><a class="toplink" href="/">Research workspace</a> · <a class="button-link" href="/runs">All runs ↗</a></div></header>
    <section class="hero"><div class="eyebrow">Operations research workspace</div><h1>Know who is gaining attention.<br>Know who to book.</h1><p>Discover artists and actors across public platform signals, preserve their evidence, and turn research runs into actionable profiles for ops.</p></section>
    {f'<div class="stats">{cards}</div>' if latest else ''}
    <section id="live-status" class="panel" style="margin-top:18px"><div class="panel-head"><div><h2>Run status</h2><div class="muted">Checking for active research...</div></div><span class="pill">connecting</span></div></section>
    <div class="grid"><section class="panel"><div class="panel-head"><div><h2>Latest research snapshot</h2><div class="muted">{html.escape(latest_context)}</div></div><a href="/run/{html.escape(latest['run'].name) if latest else ''}">{'Open full run ↗' if latest else ''}</a></div><h3>{html.escape(latest_title)}</h3><p class="muted">{html.escape((latest['findings'][0].get('trend_note') if latest and latest['findings'] and isinstance(latest['findings'][0], dict) else '') or 'Evidence-backed profiles, contacts, activity and source yield appear here.')}</p><div class="source-grid">{source_cards}</div></section>
    <section class="panel"><div class="panel-head"><div><h2>Recent runs</h2><div class="muted">Compare discovery coverage over time</div></div><a href="/runs">View all runs ↗</a></div><div class="run-list">{''.join(run_rows) or '<div class="muted">No runs yet.</div>'}</div></section></div>
    <details class="panel form-panel"><summary>＋ Start a new research run</summary><p class="muted">Use focused language + L2 genre filters. The 30-day trend window is fixed.</p><p class="muted">{html.escape(message)}</p>
    <form method="post" action="/run" onsubmit="return prepareForm()"><div class="form-grid"><label>Research type<select name="kind" id="kind" onchange="toggleFields()"><option value="artist">Artist</option><option value="actor">Actor</option></select></label>
      <div id="artist-fields"><label>Language {select("language", ARTIST_LANGUAGES)}</label><label>Location scope {select("location_scope", LOCATION_SCOPES, "India")}</label><div data-location-scope="Zone" hidden><label>Zone {select("zone", INDIAN_ZONES)}</label></div><div data-location-scope="State" hidden><label>State {select("state", INDIAN_STATES)}</label></div><div data-location-scope="City" hidden><label>City {select("city", INDIAN_CITIES)}</label></div><label>L1 category {select("category", ARTIST_CATEGORIES, element_id="artist-category", required=True)}</label><label>L2 tag {select("genre", (), element_id="artist-genre", required=True)}</label></div>
      <div id="actor-fields" hidden><label>Language {select("language", ACTOR_LANGUAGES, element_id="actor-language")}</label><label>Market / location {select("market", (), element_id="actor-market")}</label><label>Industry {select("industry", (), element_id="actor-industry")}</label><label>Actor<input name="actor" placeholder="Optional actor name"></label><label>Movie<input name="movie" placeholder="Optional movie title"></label></div></div>
      <div class="form-grid"><label>Refresh mode {select("refresh_mode", REFRESH_MODES, "discovery")}</label><div><label>Sources</label><div class="source-checks"><label><input type="checkbox" name="source" value="instagram" checked> Instagram</label><label><input type="checkbox" name="source" value="youtube" checked> YouTube</label><label><input type="checkbox" name="source" value="web" checked> Web</label><label><input type="checkbox" name="source" value="reddit" checked> Reddit</label><label><input type="checkbox" name="source" value="x" checked> X</label></div></div></div><div class="actions"><a href="/">Read research guidance</a><button type="submit">Start research →</button></div></form></details>
    <script>
      function toggleFields() {{ const artist=document.getElementById('kind').value==='artist'; document.getElementById('artist-fields').hidden=!artist; document.getElementById('actor-fields').hidden=artist; document.querySelectorAll('#artist-fields select,#artist-fields input').forEach(e=>e.disabled=!artist); document.querySelectorAll('#actor-fields select,#actor-fields input').forEach(e=>e.disabled=artist); const scope=document.querySelector('select[name="location_scope"]').value; document.querySelectorAll('[data-location-scope]').forEach(s=>{{const active=artist&&s.dataset.locationScope===scope;s.hidden=!active;s.querySelectorAll('select,input').forEach(e=>e.disabled=!active)}}); }}
      const artistL2Tags={l2_tags_json}; const actorIndustries={actor_industries_json}; const actorMarkets={actor_markets_json}; function updateArtistL2() {{ const c=document.getElementById('artist-category').value,g=document.getElementById('artist-genre'),current=g.value,values=['',...(artistL2Tags[c]||[]),'Other'];g.innerHTML=values.map(v=>'<option value="'+v+'">'+(v||'All L2 tags')+'</option>').join('');g.value=values.includes(current)?current:''; }} function updateActorMarkets() {{ const industry=document.getElementById('actor-industry').value,g=document.getElementById('actor-market'),current=g.value,values=actorMarkets[industry]||['Global','Other'];g.innerHTML=values.map(v=>'<option value="'+v+'">'+v+'</option>').join('');g.value=values.includes(current)?current:values[0]; }} function updateActorIndustries() {{ const language=document.getElementById('actor-language').value,g=document.getElementById('actor-industry'),current=g.value,values=actorIndustries[language]||['Other'];g.innerHTML=values.map(v=>'<option value="'+v+'">'+v+'</option>').join('');g.value=values.includes(current)?current:values[0];updateActorMarkets(); }}
      function prepareForm() {{ const artist=document.getElementById('kind').value==='artist';if(artist && (!document.getElementById('artist-category').value || !document.getElementById('artist-genre').value)){{alert('Select both an L1 category and an L2 tag.');return false}}const checked=[...document.querySelectorAll('input[name="source"]:checked')];if(!checked.length){{alert('Select at least one source.');return false}}const input=document.createElement('input');input.type='hidden';input.name='sources';input.value=checked.map(e=>e.value).join(',');document.querySelector('form').appendChild(input);const button=document.querySelector('button[type="submit"]');button.disabled=true;button.textContent='Research starting...';return true }}
      document.addEventListener('change',e=>{{if(e.target.id==='artist-category')updateArtistL2();if(e.target.id==='actor-language')updateActorIndustries();if(e.target.id==='actor-industry')updateActorMarkets();if(e.target.matches('select'))toggleFields()}});updateArtistL2();updateActorIndustries();toggleFields();
      let lastActiveRuns=[]; const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c])); async function refreshLiveStatus() {{ try {{ const response=await fetch('/status'); const data=await response.json(); const box=document.getElementById('live-status'); const liveRuns=(data.runs||[]).filter(r=>r.active); if(!liveRuns.length) {{ box.innerHTML='<div class="panel-head"><div><h2>Run status</h2><div class="muted">No active research runs.</div></div><span class="pill">idle</span></div>'; if(lastActiveRuns.length) setTimeout(()=>window.location.reload(),1000); lastActiveRuns=[]; return; }} box.innerHTML='<div class="panel-head"><div><h2>Research running</h2><div class="muted">'+liveRuns.length+' active run(s) · refreshed every 20 seconds</div></div><span class="pill discovery">'+liveRuns.length+' active</span></div><div class="run-list">'+liveRuns.map(r=>'<a class="run-row" href="/run/'+encodeURIComponent(r.run_id)+'"><div><div class="run-title">'+esc(r.run_id)+' · '+esc(r.phase)+'</div><div class="run-meta">'+esc(r.message||r.progress||'')+'</div><div class="run-timeline">'+(r.timeline||[]).map(line=>'<div>'+esc(line)+'</div>').join('')+'</div></div><span class="pill discovery">'+esc(r.status)+'</span></a>').join('')+'</div>'; lastActiveRuns=liveRuns.map(r=>r.run_id); }} catch(error) {{}} }} refreshLiveStatus(); setInterval(refreshLiveStatus,20000);
    </script></main></body></html>"""


def run_detail_page(run: Path) -> str:
    item = run_summary(run)
    brief = item["brief"]
    title = f'{brief.get("category") or brief.get("actor") or brief.get("kind", "Research")} · {brief.get("genre") or brief.get("movie") or brief.get("industry") or "All signals"}'
    warnings = "".join(f'<div class="warning">{html.escape(str(w.get("message", w) if isinstance(w, dict) else w))}</div>' for w in item["warnings"])
    finding_items = [value for value in item["findings"] if isinstance(value, dict)]
    finding_items.sort(key=lambda value: not (
        (status := str(value.get("status") or value.get("trend_status") or "").lower()) == "trending"
        or status.startswith("confirmed")
    ))
    findings = "".join(finding_card(value, brief.get("market") or brief.get("location_scope", ""), brief.get("kind", "artist"), brief) for value in finding_items)
    contacts = "".join(contact_card(value) for value in item["contacts"] if isinstance(value, dict))
    source_cards = "".join(source_card(source, item["source_yield"].get(source, {})) for source in ("instagram", "youtube", "reddit", "web", "x"))
    profiles = collected_profiles(run, brief.get("kind", "artist"))
    inputs = research_inputs(run)
    is_actor = brief.get("kind") == "actor"
    contact_title = "Contact findings" if is_actor else "Contact leads"
    contact_note = "Official or management contact availability; no personal details inferred" if is_actor else "Public details only; verify before outreach"
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{html.escape(title)}</title>{style()}</head><body><main class="shell">
    <header class="topbar"><div class="brand">artist<span>intel</span></div><a class="toplink" href="/">← Research workspace</a></header>
    <div class="detail-hero"><div><div class="eyebrow">Research run</div><h1>{html.escape(title)}</h1><div class="muted">{html.escape(run.name)} · {html.escape(str(brief.get("kind", "")).title())} · {html.escape(str(brief.get("refresh_mode", "discovery")).title())} · {html.escape(", ".join(brief.get("sources", [])))}</div></div><div class="detail-actions"><a class="button-link" href="/file/{html.escape(run.name)}/findings.md">Read findings ↗</a><a class="button-link" href="/">New run</a></div></div>
    <div class="stats">{stat_card("Candidates", item["candidates"], "Collected evidence", "purple")}{stat_card("Profiles", item["profiles"], "Synthesized findings", "mint")}{stat_card("India profiles", item["indian"], "India-confirmed / signalled", "gold")}{stat_card("Contacts", item["contacts_count"], "Public contact leads", "rose")}{stat_card("Trending", item["trending"], "Inside 30-day window", "")}</div>
    <section class="panel"><div class="panel-head"><div><h2>Platform yield</h2><div class="muted">What each selected source contributed to this run</div></div></div><div class="source-grid">{source_cards}</div></section>
    {inputs}
    {f'<section class="panel" style="margin-top:18px"><div class="panel-head"><div><h2>{"Findings to review" if is_actor else "Profiles to review"}</h2><div class="muted">{item["trending"]} marked trending; trending findings are shown first. Total synthesized findings: {item["profiles"]}.</div></div><div class="pill trending">{item["trending"]} trending</div></div><div class="findings">{findings}</div></section>' if findings else '<section class="panel" style="margin-top:18px"><h2>No synthesized findings</h2><div class="muted">Review the source yield and warnings below.</div></section>'}
    {f'<section class="panel" style="margin-top:18px"><div class="panel-head"><div><h2>{contact_title}</h2><div class="muted">{contact_note}</div></div></div><div class="findings">{contacts}</div></section>' if contacts else ''}
    {f'<section class="panel" style="margin-top:18px"><div class="panel-head"><div><h2>{"Collected source accounts &amp; activity" if is_actor else "Collected profiles &amp; activity"}</h2><div class="muted">{("These are source accounts/channels used as evidence, not confirmed " + str(brief.get("actor") or "actor") + " profiles.") if is_actor else (str(profiles.count("profile-card")) + " raw profiles from Instagram/YouTube; synthesized findings above may also include Web/X evidence.")}</div></div><div class="pill">{profiles.count("profile-card")} raw sources</div></div><div class="profile-grid">{profiles}</div></section>' if profiles else ''}
    {f'<section class="panel" style="margin-top:18px"><h2>Review notes</h2>{warnings}</section>' if warnings else ''}
    <p class="muted" style="margin-top:20px">Research window: {html.escape(str(brief.get("window_days", 30)))} days · Location scope: {html.escape(str(brief.get("location_scope", "")))}</p>
    </main></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def send_html(self, body: str, code: int = 200) -> None:
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_text(self, body: str, code: int = 200) -> None:
        data = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, value: dict, code: int = 200) -> None:
        data = json.dumps(value).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def redirect(self, location: str) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.end_headers()

    def do_GET(self) -> None:
        request = urlparse(self.path)
        path = request.path
        if path == "/":
            message = parse_qs(request.query).get("message", [""])[0]
            self.send_html(page(message))
            return
        if path == "/status":
            self.send_json(live_status())
            return
        if path == "/runs":
            self.send_html(runs_page())
            return
        if path == "/focus":
            self.send_html(focus_page(parse_qs(request.query)))
            return
        if path.startswith("/entity/"):
            parts = path.split("/")
            if len(parts) != 4 or parts[2] not in {"actors", "artists"}:
                self.send_html("Not found", 404)
                return
            self.send_html(entity_page(parts[2], Path(parts[3]).name))
            return
        if path.startswith("/run/"):
            run = OUTPUTS / Path(path.removeprefix("/run/")).name
            if not run.is_dir():
                self.send_html("Not found", 404)
                return
            self.send_html(run_detail_page(run))
            return
        if path.startswith("/progress/"):
            run = OUTPUTS / Path(path.removeprefix("/progress/")).name
            progress = run / "progress.log"
            if not progress.is_file():
                self.send_text("No progress yet.", 404)
                return
            self.send_text(progress.read_text(encoding="utf-8"))
            return
        if path.startswith("/file/"):
            parts = path.split("/")
            if len(parts) != 4:
                self.send_html("Not found", 404)
                return
            target = OUTPUTS / Path(parts[2]).name / Path(parts[3]).name
            if not target.is_file():
                self.send_html("Not found", 404)
                return
            if target.suffix.lower() == ".md":
                self.send_html(markdown_page(target.read_text(encoding="utf-8"), target.name))
                return
            self.send_html(target.read_text(encoding="utf-8"))
            return
        self.send_html("Not found", 404)

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/run":
            self.send_html("Not found", 404)
            return
        size = int(self.headers.get("Content-Length", "0"))
        form = parse_qs(self.rfile.read(size).decode())
        if duplicate_submission(form):
            self.redirect("/?message=This+research+request+was+already+submitted+recently.")
            return
        get = lambda key: form.get(key, [""])[0]
        sources = get("sources") or ",".join(DEFAULT_SOURCES)
        command = [
            sys.executable, str(ROOT / "main.py"), "--kind", get("kind"),
            "--refresh-mode", get("refresh_mode") or "discovery",
            "--sources", sources,
        ]
        kind = get("kind")
        if kind == "artist" and (not get("category") or not get("genre")):
            self.send_html(page("Artist research requires both an L1 category and an L2 tag."))
            return
        keys = ("language", "category", "genre") if kind == "artist" else ("language", "market", "industry", "actor", "movie")
        def value(key: str) -> str:
            selected = get(key)
            if key == "language" and selected == "All languages":
                return ""
            return get(f"{key}_custom") if selected == "Other" else selected
        if kind == "artist":
            scope = get("location_scope") or "All India"
            command.extend(["--location-scope", scope])
            location_key = {"Zone": "zone", "State": "state", "City": "city"}.get(scope)
            if location_key and value(location_key):
                command.extend([f"--{location_key}", value(location_key)])
        for key in keys:
            if value(key):
                command.extend([f"--{key}", value(key)])
        print(f"Research started: {' '.join(command)}", flush=True)
        subprocess.Popen(command, cwd=ROOT)
        self.redirect("/?message=Research+started.")


if __name__ == "__main__":
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8780"))
    print(f"Research dashboard: http://{host}:{port}")
    ThreadingHTTPServer((host, port), Handler).serve_forever()
