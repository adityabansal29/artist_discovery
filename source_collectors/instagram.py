"""Instagram hashtag discovery and public profile enrichment."""

import re
from datetime import datetime, timezone

from config import ARTIST_L1_HASHTAGS, ARTIST_L2_HASHTAGS, INSTAGRAM_PROFILE_BATCH_SIZE, INSTAGRAM_RESULTS_LIMIT
from hashtags.config import select as select_hashtags, update as update_hashtag_performance
from .apify import activity_summary, apify_client, eligible_keys, log, run_actor, save_entity

APIFY_IG_ACTOR = "apify/instagram-hashtag-scraper"
APIFY_IG_PROFILE_ACTOR = "apify/instagram-profile-scraper"
PROFILE_BUCKET_QUOTAS = {"artist": 15, "agency": 5, "promoter": 3, "media": 2}
INDIA_MARKERS = (
    "india", "indian", "mumbai", "delhi", "bengaluru", "bangalore", "hyderabad", "chennai",
    "kolkata", "pune", "ahmedabad", "jaipur", "chandigarh", "lucknow", "indore", "rajkot",
    "gujarat", "punjab", "maharashtra", "karnataka", "tamil nadu", "telangana", "bollywood",
)
FOREIGN_MARKERS = (
    "uk", "united kingdom", "london", "england", "usa", "united states", "america", "canada",
    "australia", "germany", "france", "italy", "spain", "europe", "dubai",
)


def hashtags(args) -> list[str]:
    tags = []

    def add(value: str | None) -> None:
        if value:
            tag = re.sub(r"[^a-zA-Z0-9]", "", value.lower())
            if tag and tag not in tags:
                tags.append(tag)

    if args.genre:
        # A selected L2 tag is the focused research intent. Broad Singer/DJ
        # and standalone location hashtags create noise, so combine location
        # with the selected L2 where possible.
        add(args.genre)
        for tag in ARTIST_L2_HASHTAGS.get((args.category, args.genre), ()):
            add(tag)
        for value in (args.city, args.state, args.zone):
            if value:
                add(f"{value}{args.genre}")
                add(f"{args.genre}{value}")
    else:
        # Keep language in textual queries; generic language hashtags are too broad.
        for value in (args.city, args.state, args.zone):
            add(value)
        add(args.category)
        for tag in ARTIST_L1_HASHTAGS.get(args.category, ()):
            add(tag)
    for value in (args.actor, args.movie):
        add(value)
    return select_hashtags(args, tags)[:20]


def hashtag_metrics(items: list[dict], tags: list[str]) -> dict:
    metrics = {tag: {"matching_posts": 0, "likes": 0, "comments": 0} for tag in tags}
    for item in items:
        item_tags = {re.sub(r"[^a-zA-Z0-9]", "", str(tag).lower()) for tag in item.get("hashtags", [])}
        for tag in tags:
            if tag in item_tags:
                metrics[tag]["matching_posts"] += 1
                metrics[tag]["likes"] += item.get("likesCount", 0) or 0
                metrics[tag]["comments"] += item.get("commentsCount", 0) or 0
    return metrics


def classify_candidate(username: str, full_name: str = "") -> str:
    """Classify an account without dropping it from discovery."""
    text = f"{username} {full_name}".lower()
    if any(word in text for word in ("fan", "fans", "_fc", ".fc", "unofficial")):
        return "media"
    if any(word in text for word in ("news", "media", "daily", "buzz", "magazine", "tv")):
        return "media"
    if any(word in text for word in ("academy", "school", "class", "institute", "lesson")):
        return "promoter"
    if any(word in text for word in ("booking", "management", "talent", "entertainment", "agency")):
        return "agency"
    if any(word in text for word in ("event", "concert", "ticket", "venue", "festival", "lounge", "club")):
        return "promoter"
    return "artist"


def geography_rank(item: dict) -> int:
    """Rank likely India profiles without dropping unknown candidates."""
    text = " ".join(str(item.get(key) or "") for key in ("ownerUsername", "ownerFullName", "caption", "locationName")).lower()
    tags = " ".join(str(tag) for tag in item.get("hashtags", [])).lower()
    india = any(marker in text for marker in INDIA_MARKERS) or any(marker in tags for marker in ("india", "indian"))
    foreign = any(marker in text for marker in FOREIGN_MARKERS)
    if india and not foreign:
        return 2
    if india:
        return 1
    if foreign:
        return -1
    return 0


def select_profiles(items: list[dict], refresh_mode: str, kind: str = "artist", limit: int = INSTAGRAM_PROFILE_BATCH_SIZE) -> tuple[list[str], int, dict]:
    """Cover hashtags within entity quotas, then fill unused batch capacity."""
    candidates = {}
    for item in items:
        username = str(item.get("ownerUsername") or "").strip()
        if not username:
            continue
        score = (item.get("likesCount", 0) or 0) + 2 * (item.get("commentsCount", 0) or 0)
        entry = candidates.setdefault(username, {"score": 0, "tags": set()})
        entry["score"] = max(entry["score"], score)
        entry["bucket"] = classify_candidate(username, str(item.get("ownerFullName") or ""))
        entry["geo_rank"] = max(entry.get("geo_rank", 0), geography_rank(item))
        entry["tags"].update(re.sub(r"[^a-zA-Z0-9]", "", str(tag).lower()) for tag in item.get("hashtags", []))

    eligible = eligible_keys("instagram", list(candidates), refresh_mode)
    unseen = {name: data for name, data in candidates.items() if name.lower() in eligible}
    selected = []
    selected_buckets = {}

    def take(pool: dict, quota: int, bucket: str) -> None:
        if quota <= 0:
            return
        chosen = []
        sort_key = lambda pair: ((pair[1].get("geo_rank", 0) if kind == "artist" else 0), pair[1]["score"])
        for tag in sorted({tag for data in pool.values() for tag in data["tags"]}):
            for username, data in sorted(pool.items(), key=sort_key, reverse=True):
                if tag in data["tags"] and username not in chosen:
                    chosen.append(username)
                    break
                
        for username, _ in sorted(pool.items(), key=sort_key, reverse=True):
            if username not in chosen:
                chosen.append(username)
            if len(chosen) >= quota:
                break
        for username in chosen[:quota]:
            if len(selected) >= limit:
                return
            selected.append(username)
            selected_buckets[bucket] = selected_buckets.get(bucket, 0) + 1

    for bucket, quota in PROFILE_BUCKET_QUOTAS.items():
        take({name: data for name, data in unseen.items() if data["bucket"] == bucket}, quota, bucket)

    # Use any remaining candidates when a bucket has fewer accounts than its quota.
    take({name: data for name, data in unseen.items() if name not in selected}, limit - len(selected), "other")
    return selected[:limit], len(candidates) - len(unseen), {
        "candidate_buckets": {
            bucket: sum(data["bucket"] == bucket for data in candidates.values())
            for bucket in ("artist", "agency", "promoter", "media")
        },
        "selected_buckets": selected_buckets,
        "candidate_geography": {
            "india": sum(data.get("geo_rank", 0) > 0 for data in candidates.values()),
            "unknown": sum(data.get("geo_rank", 0) == 0 for data in candidates.values()),
            "foreign": sum(data.get("geo_rank", 0) < 0 for data in candidates.values()),
        },
        "selected_geography": {
            "india": sum(candidates.get(username, {}).get("geo_rank", 0) > 0 for username in selected),
            "unknown": sum(candidates.get(username, {}).get("geo_rank", 0) == 0 for username in selected),
            "foreign": sum(candidates.get(username, {}).get("geo_rank", 0) < 0 for username in selected),
        },
    }


def collect(args, logger=None) -> dict:
    log(logger, "Instagram: starting Apify collection")
    client, error = apify_client()
    if error:
        log(logger, f"Instagram: skipped ({error})")
        return {"status": "skipped", "reason": error, "items": []}
    tags = hashtags(args)
    if not tags:
        return {"status": "skipped", "reason": "no Instagram hashtags available", "items": []}
    try:
        items = run_actor(client, APIFY_IG_ACTOR, {"hashtags": tags, "resultsLimit": INSTAGRAM_RESULTS_LIMIT}, 900)
        hashtag_performance = update_hashtag_performance(args, tags, items)
        usernames, previously_enriched, selection = select_profiles(items, args.refresh_mode, args.kind)
        profiles = []
        enrichment = {"status": "skipped", "requested": 0}
        if args.kind == "actor":
            enrichment = {"status": "not_requested", "requested": 0, "profiles": 0,
                          "reason": "Actor runs use Instagram posts as evidence; hashtag posting accounts are not actor profiles.",
                          "candidate_usernames": len({item.get("ownerUsername") for item in items if item.get("ownerUsername")} ),
                          **selection}
        elif usernames:
            log(logger, f"Instagram: enriching {len(usernames)} public profiles")
            try:
                profiles = run_actor(client, APIFY_IG_PROFILE_ACTOR, {"usernames": usernames}, 600)
                enrichment = {"status": "collected", "requested": len(usernames), "profiles": len(profiles),
                              "candidate_usernames": len({item.get("ownerUsername") for item in items if item.get("ownerUsername")}),
                              "previously_enriched": previously_enriched,
                              **selection}
                refreshed_at = datetime.now(timezone.utc).isoformat()
                for profile in profiles:
                    username = str(profile.get("username") or "").strip()
                    if not username:
                        continue
                    recent_posts = profile.get("latestPosts", []) + profile.get("latestIgtvVideos", [])
                    profile["activity_summary"] = activity_summary(recent_posts, ("timestamp", "takenAt"))
                    save_entity("instagram", username, {
                        "platform": "instagram",
                        "key": username.lower(),
                        "profile": profile,
                        "posts": recent_posts,
                        "activity_summary": profile["activity_summary"],
                        "last_enriched_at": refreshed_at,
                    })
            except Exception as exc:
                enrichment = {"status": "failed", "requested": len(usernames), "reason": str(exc)}
                log(logger, f"Instagram: profile enrichment failed ({exc})")
        log(logger, f"Instagram: collected {len(items)} posts; selected {len(usernames)} profiles")
        return {"status": "collected", "hashtags": tags, "count": len(items), "hashtag_metrics": hashtag_metrics(items, tags),
                "hashtag_performance": hashtag_performance,
                "metrics_note": "Metrics reflect returned posts, not Instagram search volume.", "profile_enrichment": enrichment,
                "profile_usernames": usernames, "profiles": profiles, "items": items}
    except Exception as exc:
        log(logger, f"Instagram: failed ({exc})")
        return {"status": "failed", "hashtags": tags, "reason": str(exc), "items": []}
