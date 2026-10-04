"""YouTube video discovery and channel-description/activity enrichment."""

from datetime import datetime, timezone
import re

from .apify import activity_summary, apify_client, eligible_keys, log, run_actor, save_entity
from config import (INDIAN_CITIES, INDIAN_STATES, INDIAN_ZONES, YOUTUBE_CHANNEL_BATCH_SIZE,
                    YOUTUBE_RECENT_VIDEOS, YOUTUBE_RESULTS_LIMIT)

APIFY_YT_ACTOR = "streamers/youtube-scraper"
APIFY_YT_CHANNEL_ACTOR = "automation-lab/youtube-channel-scraper"
CHANNEL_QUOTAS = {"artist": 15, "agency": 5, "ecosystem": 3, "media": 2}
CONFIGURED_INDIA_MARKERS = tuple(
    value.lower() for value in (*INDIAN_CITIES, *INDIAN_STATES, *INDIAN_ZONES)
    if value.lower() != "other"
)
INDIA_MARKERS = ("india", "indian", "bangalore", "bollywood", *CONFIGURED_INDIA_MARKERS)
FOREIGN_MARKERS = ("usa", "united states", "america", "uk", "united kingdom", "london", "canada",
                   "australia", "germany", "france", "italy", "spain", "europe", "lebanon",
                   "south africa", "tunisia", "taiwan", "dubai", "uae")
# Generic channel-purpose signals only; do not add names observed in one run.
NOISE_MARKERS = ("government", "ministry", "parliament", "pool", "billiards", "snooker", "sports",
                 "news", "television", "tv", "broadcaster", "directory", "marketplace", "records",
                 "academy", "school", "institute", "festival", "club", "studio", "agency", "management",
                 "president of", "talent management", "event management", "decorations", "tent",
                 "wedding planner", "entertainment services", "booking agency", "record label",
                 "production company", "media company")
ARTIST_MARKERS = ("pianist", "piano", "musician", "instrumentalist", "keyboard", "composer", "performer",
                  "singer", "artist", "band", "flute", "guitar", "violin", "drummer", "dj")
BOOKING_MARKERS = ("booking", "wedding", "event", "concert", "live performance", "available for", "hire")


def channel_key(item: dict) -> str:
    return str(item.get("channelId") or item.get("channelUrl") or item.get("url") or "").strip()


def video_record(item: dict) -> dict:
    """Normalize one YouTube search result for channel history and trend analysis."""
    record = {
        "videoId": item.get("id"),
        "title": item.get("title"),
        "url": item.get("url") or (f"https://www.youtube.com/watch?v={item.get('id')}" if item.get("id") else None),
        "channelId": item.get("channelId"),
        "channelName": item.get("channelName"),
        "channelHandle": item.get("channelHandle") or item.get("channelUsername"),
        "channelUrl": item.get("channelUrl"),
        "publishedAt": item.get("date"),
        "viewCount": item.get("viewCount", 0),
        "likesCount": item.get("likes", 0),
        "commentsCount": item.get("commentsCount", 0),
        "description": item.get("text") or item.get("description"),
        "descriptionLinks": item.get("descriptionLinks", []),
        "hashtags": item.get("hashtags", []),
        "thumbnailUrl": item.get("thumbnailUrl"),
        "duration": item.get("duration"),
        "location": item.get("location"),
        "numberOfSubscribers": item.get("numberOfSubscribers"),
        "isMonetized": item.get("isMonetized"),
        "isPaidContent": item.get("isPaidContent"),
        "aiVideoDescription": item.get("aiVideoDescription"),
        "aiVideoSummary": item.get("aiVideoSummary"),
        "transcriptionUrl": item.get("transcriptionUrl"),
        "translatedTitle": item.get("translatedTitle"),
        "translatedText": item.get("translatedText"),
    }
    for source, target in (("isShort", "isShort"), ("type", "type"),
                           ("commentsTurnedOff", "commentsTurnedOff")):
        if item.get(source) is not None:
            record[target] = item[source]
    return record


def deduplicate_profiles(profiles: list[dict]) -> list[dict]:
    """Collapse repeated channel-actor records to one record per channel ID."""
    unique = {}
    for profile in profiles:
        key = channel_key(profile)
        if not key:
            continue
        existing = unique.get(key)
        if existing is None or profile_quality(profile) > profile_quality(existing):
            unique[key] = profile
    return list(unique.values())


def profile_quality(profile: dict) -> int:
    """Prefer the actor record with the most usable channel metadata."""
    fields = ("channelId", "channelName", "channelUrl", "channelHandle", "description",
              "subscriberCount", "totalVideos", "totalViews", "country", "location",
              "isVerified", "links", "channelLinks")
    return sum(profile.get(field) not in (None, "", [], {}) for field in fields)


def profile_lead_type(profile: dict, kind: str) -> str:
    if kind != "artist":
        return "primary_artist"
    text = " ".join(str(profile.get(field) or "") for field in
                     ("channelName", "channelHandle", "description", "keywords", "links")).lower()
    secondary = ("talent management", "artist management", "event management", "decorations", "tent",
                 "wedding planner", "entertainment services", "booking agency", "record label",
                 "production company", "media company", "agency")
    return "secondary_agency_or_vendor" if any(marker in text for marker in secondary) else "primary_artist"


def build_channel_profiles(batch: list[dict], raw_profiles: list[dict], kind: str = "artist") -> tuple[list[dict], dict]:
    """Return one enriched profile per selected channel, including actor fallbacks."""
    selected = {}
    for item in batch:
        key = channel_key(item)
        if key and key not in selected:
            selected[key] = item

    actor_profiles = {channel_key(profile): profile for profile in deduplicate_profiles(raw_profiles)}
    profiles = []
    fallback_count = 0
    for key, item in selected.items():
        profile = actor_profiles.get(key)
        if profile is None:
            profile = {
                "channelId": item.get("channelId"),
                "channelName": item.get("channelName"),
                "channelUrl": item.get("channelUrl"),
                "channelHandle": item.get("channelHandle") or item.get("channelUsername"),
                "description": item.get("channelDescription"),
                "subscriberCount": item.get("subscriberCount") or item.get("numberOfSubscribers"),
                "profile_source": "search_result_fallback",
                "enrichment_missing": True,
            }
            fallback_count += 1
        else:
            profile = dict(profile)
            for field in ("channelName", "channelUrl", "channelHandle"):
                if not profile.get(field) and item.get(field):
                    profile[field] = item[field]
            profile["profile_source"] = "channel_actor"
            profile["enrichment_missing"] = False
        profile["lead_type"] = profile_lead_type(profile, kind)
        profiles.append(profile)

    invalid_profiles = sum(not channel_key(profile) for profile in raw_profiles if isinstance(profile, dict))
    return profiles, {
        "requested": len(selected),
        "raw_profiles": len(raw_profiles),
        "valid_profiles": len(deduplicate_profiles(raw_profiles)),
        "unique_channels": len(profiles),
        "fallback_profiles": fallback_count,
        "invalid_profiles": invalid_profiles,
        "primary_profiles": sum(profile.get("lead_type") == "primary_artist" for profile in profiles),
        "secondary_profiles": sum(profile.get("lead_type") == "secondary_agency_or_vendor" for profile in profiles),
    }


def classify_channel(item: dict) -> str:
    text = " ".join(str(item.get(key) or "") for key in ("channelName", "channelHandle", "title", "description")).lower()
    if any(word in text for word in ("news", "media", "review", "reaction", "fan", "unofficial")):
        return "media"
    if any(word in text for word in ("booking", "management", "talent", "entertainment", "agency", "event")):
        return "agency"
    if any(word in text for word in ("label", "records", "academy", "school", "institute", "music class", "trust")):
        return "ecosystem"
    return "artist"


def geography_rank(item: dict) -> int:
    text = " ".join(str(item.get(field) or "") for field in
                     ("channelName", "channelUrl", "channelUsername", "title", "description")).lower()
    india = any(marker in text for marker in INDIA_MARKERS)
    foreign = any(marker in text for marker in FOREIGN_MARKERS)
    if india and not foreign:
        return 2
    if india:
        return 1
    if foreign:
        return -1
    return 0


def artist_quality(item: dict) -> tuple[int, bool]:
    """Score individual artist fit; unrelated channels become secondary leads."""
    identity = " ".join(str(item.get(field) or "") for field in
                        ("channelName", "channelUsername", "channelUrl", "description", "text")).lower()
    all_text = f"{identity} {str(item.get('title') or '').lower()}"
    noise = any(re.search(rf"\b{re.escape(marker)}\b", identity) for marker in NOISE_MARKERS)
    noise = noise or ("performer" in identity and any(word in identity for word in ("find", "hire", "directory")))
    score = 0
    score += 4 if any(marker in identity for marker in ARTIST_MARKERS) else 0
    score += 2 if any(marker in all_text for marker in BOOKING_MARKERS) else 0
    score += 2 if geography_rank(item) > 0 else 0
    score -= 8 if noise else 0
    return score, noise


def select_channels(items: list[dict], refresh_mode: str, kind: str = "artist",
                    limit: int = YOUTUBE_CHANNEL_BATCH_SIZE) -> tuple[list[dict], int, dict]:
    """Select relevant artist channels, or quota-balanced global actor channels."""
    candidates = {}
    for item in items:
        key = channel_key(item)
        if not key:
            continue
        value = item.get("viewCount", 0)
        try:
            score = int(value or 0)
        except (TypeError, ValueError):
            score = 0
        current = candidates.setdefault(key, {"item": item, "score": 0, "bucket": classify_channel(item),
                                               "geo_rank": geography_rank(item), "artist_score": 0, "noise": False})
        current["geo_rank"] = max(current["geo_rank"], geography_rank(item))
        artist_score, noise = artist_quality(item)
        current["artist_score"] = max(current["artist_score"], artist_score)
        current["noise"] = current["noise"] or noise
        if score > current["score"]:
            current["score"] = score
            current["item"] = item

    eligible = eligible_keys("youtube", list(candidates), refresh_mode)
    unseen = {key: value for key, value in candidates.items() if key.lower() in eligible}
    selected, selected_buckets = [], {}
    if kind == "artist":
        primary = [value for value in unseen.values()
                   if not value["noise"] and value["geo_rank"] == 2 and value["artist_score"] >= 4]
        pool = sorted(primary, key=lambda value: (value["geo_rank"], value["artist_score"], value["score"]), reverse=True)
        for value in pool[:limit]:
            selected.append(value["item"])
            bucket = value["bucket"]
            selected_buckets[bucket] = selected_buckets.get(bucket, 0) + 1
        secondary = sorted((value for value in unseen.values() if value["item"] not in selected),
                           key=lambda value: (value["artist_score"], value["geo_rank"], value["score"]), reverse=True)
    else:
        for bucket, quota in CHANNEL_QUOTAS.items():
            pool = sorted((value for value in unseen.values() if value["bucket"] == bucket),
                          key=lambda value: value["score"], reverse=True)
            for value in pool[:quota]:
                if len(selected) >= limit:
                    break
                selected.append(value["item"])
                selected_buckets[bucket] = selected_buckets.get(bucket, 0) + 1
        secondary = sorted((value for value in unseen.values() if value["item"] not in selected),
                           key=lambda value: value["score"], reverse=True)
        for value in secondary[: max(0, limit - len(selected))]:
            selected.append(value["item"])
            selected_buckets["other"] = selected_buckets.get("other", 0) + 1
        secondary = []
    return selected[:limit], len(candidates) - len(unseen), {
        "candidate_buckets": {bucket: sum(value["bucket"] == bucket for value in candidates.values()) for bucket in CHANNEL_QUOTAS},
        "selected_buckets": selected_buckets,
        "primary_artist_candidates": sum(value["artist_score"] >= 4 and not value["noise"] for value in unseen.values()) if kind == "artist" else None,
        "secondary_candidates": [value["item"] for value in secondary[:20]] if kind == "artist" else [],
        "candidate_geography": {name: sum(value["geo_rank"] == rank for value in candidates.values())
                                for name, rank in (("india", 2), ("mixed", 1), ("unknown", 0), ("foreign", -1))},
        "selected_geography": {name: sum(value["geo_rank"] == rank for value in candidates.values()
                                           if value["item"] in selected)
                               for name, rank in (("india", 2), ("mixed", 1), ("unknown", 0), ("foreign", -1))},
    }


def collect(queries: list[str], logger=None, refresh_mode: str = "discovery", kind: str = "artist") -> dict:
    log(logger, f"YouTube: starting Apify collection ({len(queries)} queries)")
    client, error = apify_client()
    if error:
        log(logger, f"YouTube: skipped ({error})")
        return {"status": "skipped", "reason": error, "items": []}
    try:
        items = run_actor(client, APIFY_YT_ACTOR, {"searchKeywords": ",".join(queries), "maxResults": YOUTUBE_RESULTS_LIMIT,
                                                   "maxResultsShorts": 0, "sortBy": "relevance"}, 1200)
        batch, previously_seen, selection = select_channels(items, refresh_mode, kind)
        channels = list(dict.fromkeys(item.get("channelUrl") for item in batch if item.get("channelUrl")))
        profiles, enrichment = [], {"status": "skipped", "requested": 0}
        if channels:
            try:
                raw_profiles = run_actor(client, APIFY_YT_CHANNEL_ACTOR, {"channels": channels,
                                                                      "maxVideosPerChannel": YOUTUBE_RECENT_VIDEOS,
                                                                      "includeChannelInfo": True, "includeVideos": True}, 900)
                profiles, enrichment_counts = build_channel_profiles(batch, raw_profiles, kind)
                selected_keys = {channel_key(item) for item in batch if channel_key(item)}
                videos_by_channel = {key: [] for key in selected_keys if key}
                for item in items:
                    key = channel_key(item)
                    if key not in videos_by_channel or not item.get("id"):
                        continue
                    videos_by_channel[key].append(video_record(item))
                for key in videos_by_channel:
                    unique_videos = {video.get("videoId"): video for video in videos_by_channel[key] if video.get("videoId")}
                    videos_by_channel[key] = sorted(unique_videos.values(),
                                                    key=lambda video: video.get("publishedAt") or "", reverse=True)[:YOUTUBE_RECENT_VIDEOS]
                enrichment = {"status": "collected", **enrichment_counts}
                refreshed_at = datetime.now(timezone.utc).isoformat()
                for profile in profiles:
                    key = channel_key(profile)
                    if not key:
                        continue
                    videos = videos_by_channel.get(key, [])
                    profile["videos"] = videos
                    profile["activity_summary"] = activity_summary(videos, ("publishedAt", "uploadDate", "publishedTime"))
                    save_entity("youtube", key, {
                        "platform": "youtube",
                        "key": key.lower(),
                        "channel": profile,
                        "videos": videos,
                        "activity_summary": profile["activity_summary"],
                        "last_enriched_at": refreshed_at,
                    })
            except Exception as exc:
                enrichment = {"status": "failed", "requested": len(channels), "reason": str(exc)}
                log(logger, f"YouTube: channel enrichment failed ({exc})")
        log(logger, f"YouTube: collected {len(items)} videos; selected {len(batch)} channels")
        return {"status": "collected", "count": len(items), "batch_count": len(batch), "previously_seen": previously_seen,
                **selection,
                "items": items, "batch_items": batch, "channels": channels, "channel_enrichment": enrichment,
                "channel_profiles": profiles}
    except Exception as exc:
        log(logger, f"YouTube: failed ({exc})")
        return {"status": "failed", "reason": str(exc), "items": []}
