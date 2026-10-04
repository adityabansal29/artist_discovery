"""Reddit search, in-run deduplication, and cross-run post batching."""

import os
import time

from config import REDDIT_BATCH_SIZE, REDDIT_RESULTS_PER_QUERY
from .apify import log, mark_processed, select_new

try:
    import requests
except ImportError:
    requests = None

REDDIT_QUERIES = ("booking", "live performance", "event", "artist")


def token() -> str | None:
    if requests is None or not (os.environ.get("REDDIT_CLIENT_ID") and os.environ.get("REDDIT_CLIENT_SECRET")):
        return None
    try:
        response = requests.post("https://www.reddit.com/api/v1/access_token",
                                 auth=(os.environ["REDDIT_CLIENT_ID"], os.environ["REDDIT_CLIENT_SECRET"]),
                                 data={"grant_type": "client_credentials"},
                                 headers={"User-Agent": "artist-research-v0/1.0"}, timeout=20)
        response.raise_for_status()
        return response.json().get("access_token")
    except requests.RequestException:
        return None


def subreddits(args) -> list[str]:
    if args.kind == "actor":
        return ["movies", "entertainment", "bollywood"] if args.language == "Hindi" else ["movies", "entertainment"]
    city = (args.city or "").lower()
    local = {"mumbai": "mumbai", "delhi": "delhi", "bengaluru": "bangalore", "bangalore": "bangalore"}
    return ["indiamusic", local[city]] if city in local else ["indiamusic", "india"]


def collect(args, query_seeds: list[str], logger=None) -> dict:
    if requests is None:
        return {"status": "skipped", "reason": "requests is not installed", "items": []}
    access_token = token()
    log(logger, f"Reddit: starting {'OAuth' if access_token else 'public JSON'} collection")
    headers = {"User-Agent": "artist-research-v0/1.0", **({"Authorization": f"bearer {access_token}"} if access_token else {})}
    base = "https://oauth.reddit.com" if access_token else "https://www.reddit.com"
    results, seen, calls = [], set(), 0
    for subreddit in subreddits(args):
        for query in list(REDDIT_QUERIES) + query_seeds[:2]:
            calls += 1
            try:
                endpoint = "/search" if access_token else "/search.json"
                response = requests.get(f"{base}/r/{subreddit}{endpoint}", headers=headers,
                    params={"q": query, "restrict_sr": "true", "sort": "new", "t": "month", "limit": REDDIT_RESULTS_PER_QUERY}, timeout=20)
                if response.status_code != 200:
                    continue
                for child in response.json().get("data", {}).get("children", []):
                    item = child.get("data", {})
                    permalink = item.get("permalink", "")
                    if not permalink or permalink in seen:
                        continue
                    seen.add(permalink)
                    results.append({"subreddit": subreddit, "title": item.get("title", ""), "text": (item.get("selftext") or "")[:1000],
                                    "score": item.get("score", 0), "comments": item.get("num_comments", 0), "url": f"https://www.reddit.com{permalink}"})
                time.sleep(0.5 if access_token else 1)
            except requests.RequestException:
                continue
    results.sort(key=lambda item: item["score"] + item["comments"] * 2, reverse=True)
    batch, previously_seen = select_new(results, "reddit", lambda item: item.get("url"), REDDIT_BATCH_SIZE)
    mark_processed("reddit", batch, lambda item: item.get("url"))
    status = "collected" if results else "empty"
    log(logger, f"Reddit: {status}; {len(results)} posts; selected {len(batch)} new posts")
    return {"status": status, "auth": "oauth" if access_token else "public_json", "calls": calls, "count": len(results),
            "batch_count": len(batch), "previously_seen": previously_seen, "batch_items": batch, "items": results,
            **({"reason": "no matching posts returned"} if not results else {})}
