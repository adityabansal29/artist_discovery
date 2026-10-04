# Artist and Actor Research V0

File-based research prototype for Indian artist discovery and configurable
movie-actor research.

## Run the sanity check

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python self_check.py
```

## Run artist research

```bash
.venv/bin/python main.py \
  --kind artist \
  --city Mumbai \
  --language Hindi \
  --category Singer \
  --genre Bollywood \
  --refresh-mode discovery \
  --sources instagram,youtube,web,reddit,x
```

## Run actor research

```bash
.venv/bin/python main.py \
  --kind actor \
  --language Hindi \
  --market India \
  --sources instagram,youtube,web,reddit,x
```

The research runner requires the `claude` CLI to be installed and authenticated.
Set `CLAUDE_CODE_OAUTH_TOKEN` in `.env` or export it before starting the
dashboard. Do not set it together with `ANTHROPIC_API_KEY`.
Instagram and YouTube use `APIFY_API_TOKEN`; Reddit uses OAuth credentials when
available and otherwise tries the public JSON endpoint. Web and X are searched
by the Claude research step. Each run writes direct platform data, Markdown,
JSON, the generated prompt, metadata, and a log under `outputs/runs/`.

Use `--refresh-mode trend` for regular recent-activity checks, `discovery` for
broader profile/contact enrichment, and `backfill` to refresh every candidate
returned by the current search. Search collection still runs in every mode;
refresh mode only controls which known profiles/channels are enriched again. Persistent
profile snapshots are stored under `outputs/entities/`, while
`outputs/reddit_content_index.json` stores Reddit post IDs for cross-run
deduplication. Research activity is always evaluated over a fixed 30-day
window; this is not a run input.

Artist Instagram enrichment prioritizes India-confirmed candidates, then likely
India candidates, then unknown candidates. Foreign candidates are used only
when the requested batch cannot otherwise be filled. Actor enrichment remains
market/language driven rather than India-only.

Instagram hashtag performance is stored in `hashtags/performance.json`. Tags
are scored per research context (kind, L1/L2, language, and location). A tag
is suppressed only after `2` runs below the `0.25` score threshold; a small
exploration set is retained so new tags can recover.

## Start the dashboard

```bash
.venv/bin/python dashboard_server.py
```

## Run with Docker

Keep credentials in the existing `.env` file, then start the dashboard:

```bash
docker compose up -d --build
docker compose logs -f dashboard
```

Open `http://127.0.0.1:8780`. `outputs/` and `hashtags/` are mounted from the
host, so run history and hashtag performance survive container rebuilds. The
container installs the Claude Code CLI; provide `CLAUDE_CODE_OAUTH_TOKEN`,
`APIFY_API_TOKEN`, and optional Reddit credentials through `.env`.

Stop it with:

```bash
docker compose down
```

Open http://127.0.0.1:8780.

Before running similar research, review
[`learnings/research_run_guidance.md`](learnings/research_run_guidance.md) for
parameter recommendations and interpretation rules.

V0 does not send email or WhatsApp messages, create public profiles, or persist
data in a database.

## Sequential collection flow

The collector code is split into `source_collectors/apify.py`,
`instagram.py`, `youtube.py`, `reddit.py`, `web_x.py`, and `claude.py`. Static research
rules remain in `prompts/artist_research.md` and `prompts/actor_research.md`;
the dynamic Web/X and findings prompt builders are in
`prompts/web_prompt.py` and `prompts/findings_prompt.py`. Every run follows
the same sequence:

1. Build the source queries/hashtags from the dashboard or CLI parameters.
2. Fetch the complete raw result set available to that collector.
3. Save the raw direct-source data for audit in `apify_data.json`.
4. Deduplicate within the current run.
5. Check entity snapshots for refresh eligibility and the content index for
   previously processed Reddit posts.
6. Select the first batch for the source.
7. Enrich new or refreshable profiles/channels where an Actor exists.
8. Save the selected evidence in `claude_input.json`.
9. Run the separate Claude Web/X phase; it performs searches and writes
   `web_data.json` and `x_data.json`.
10. Run the separate Claude synthesis phase; it reads the saved direct-source
    and Web/X evidence and writes `findings.md` and `findings.json`.

Current batch behavior:

```text
Instagram: 100 posts → 25 unique profile usernames → profile enrichment
YouTube:   100 videos → 25 unique channels → channel-description enrichment
Reddit:    search results → 50 unique posts → no profile enrichment
Web/X:     query delegation → Claude Web/X phase → saved search results
```

The index is updated only after processing succeeds: Instagram after profile
records return, YouTube after channel enrichment returns, and Reddit after its
selected post batch is accepted. The complete raw results and the selected batch are intentionally separate.
This means a later batch can be processed without losing the original source
evidence. Each run creates its own findings files; findings from different
runs are not automatically merged.
`progress.log` is the single run-level operational log, including collector
and Claude phase messages. Detailed Claude diagnostics are written to
`web_claude_debug.log` and `findings_claude_debug.log`.

## Instagram selection and result limits

The pipeline has two different stages:

1. **Post discovery:** the Instagram hashtag Actor returns posts for the
   generated hashtags. The current V0 request uses `resultsLimit: 100` in
   `collectors.py`. The raw returned posts are saved in `apify_data.json`.
2. **Profile enrichment:** usernames are deduplicated from those posts and a
   smaller batch is sent to the Instagram profile Actor. The current V0 sends
   up to 25 previously unseen usernames, selecting hashtag coverage first and
   then filling remaining slots by the strongest returned-post signal:

   ```text
   selection_score = likes + (2 * comments)
   ```

This is only a first-pass strategy. It can over-select popular accounts and
miss Tier 2/3 artists. The intended next strategy is **stratified batching**:

```text
Example returned data:
  100 posts
   84 unique usernames
    5 hashtags

Batch size: 25

Batch 1: select candidates across all 5 hashtags, prioritising one account
         per hashtag before filling remaining slots by engagement.
Batch 2: select the next unseen usernames using the same coverage rule.
Batch 3: continue until the candidate pool is exhausted.
```

Each batch records its successfully enriched usernames in a persistent
enrichment index. Future runs skip already-enriched usernames unless an
explicit refresh is requested.
This gives coverage across hashtags instead of repeatedly enriching the same
top accounts. The hashtag counts are counts of posts returned by Apify, not
Instagram's total search volume.

### Does Apify need client-side pagination?

No client rewrite is needed. `dataset(...).iterate_items()` already iterates
through the completed dataset pages. To request more Instagram posts, change
the Actor input (`resultsLimit`) or run additional hashtag batches. The
application now requests `resultsLimit: 100`; changing that value changes the
Actor request and does not require changing the Apify Python client.

The important distinction is:

- **Dataset pagination:** handled by the existing Apify client code.
- **Actor result limit:** controlled by the Actor input and may cap how many
  posts are produced in the first place.
- **Profile batch size and uniqueness:** controlled by our application code,
  not by Apify pagination.

Increasing the post limit alone will not enrich every discovered account; the
profile batch size and entity refresh rules must also be applied.

## YouTube and Reddit batches

The same run-level selection pattern now applies to the other direct sources:

- **YouTube:** requests up to 100 results, deduplicates by channel ID (or
  channel URL), classifies channels, enriches up to 25 new channels using
  artist/agency/ecosystem/media quotas, and passes their public descriptions
  and external links to Claude.
- **Reddit:** requests up to 25 results per search call, keeps the complete
  deduplicated raw result set, and passes up to 50 previously unseen posts to
  Claude.
- Instagram and YouTube refresh timestamps are stored in their entity files.
  Reddit post IDs are tracked in `outputs/reddit_content_index.json`.

Raw results remain in `apify_data.json`. `claude_input.json` contains the
selected batch for YouTube/Reddit plus the Instagram evidence and enriched
profiles. YouTube descriptions and links are included under
`channel_profiles`. Claude writes one `findings.md` and one `findings.json` for
that run;
separate runs are not automatically merged.
