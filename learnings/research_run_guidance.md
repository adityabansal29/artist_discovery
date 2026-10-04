# Research Run Guidance

Use this checklist before starting an artist research run.

## Parameter selection

- Use `language + category + L2 genre` for focused runs. A broad `Singer`
  run produces labels, media pages, agencies, venues, and non-Indian results.
- Research activity is evaluated over a fixed 30-day window.
- Use `refresh-mode: trend` for frequent recent-activity checks and
  `refresh-mode: discovery` for broader profile/contact enrichment.
- Use All India for the first language/genre discovery pass.
- Use Zone, State, or City for focused follow-up runs and Tier 2/3 coverage.

Examples:

```bash
.venv/bin/python main.py \
  --kind artist \
  --language Hindi \
  --category Singer \
  --genre Bollywood \
  --refresh-mode discovery \
  --sources instagram,youtube,web,x
```

```bash
.venv/bin/python main.py \
  --kind artist \
  --language Gujarati \
  --category Singer \
  --genre "Indian Folk" \
  --refresh-mode discovery \
  --sources instagram,youtube,web,x
```

## How to interpret a run

- Instagram and YouTube are discovery-rich but noisy. Agencies, labels,
  media pages, fan pages, and venues must not be treated as bookable artists.
- A single low-engagement or fan-page post is not enough to label an artist
  `trending`; use `discovered, trend unverified` unless there is stronger
  corroboration.
- Contacts from agencies or event promoters belong to those third parties,
  not automatically to the artist. Keep them labelled as agency/promoter
  contacts.
- Keep the enrichment batch at 25 until candidate filtering improves. Run
  again to process later unique batches.
- Reddit is optional for now; zero results should not block the run.
- Web/X are strongest for corroboration and market context, not broad artist
  discovery when the seed query is only `Singer`.

## Current observed baseline

The broad Singer baseline returned 500 Instagram posts and 400 YouTube videos,
but only 6 useful Instagram profiles and 3 useful YouTube artist channels.
This is why the next run should narrow language and L2 genre before increasing
result counts or enrichment batch size.
