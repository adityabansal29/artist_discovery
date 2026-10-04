# Artist and Actor Research — V0 Architecture

## Scope

V0 researches two independent domains using shared collection infrastructure:

```text
Indian artists
    ├── discovery
    ├── trend evidence
    ├── public contact discovery
    └── draft-profile findings

Movie actors
    ├── configurable language/market research
    ├── trend evidence
    ├── movie associations
    └── public profile/management links
```

Restaurant enrichment is excluded from V0. It can be added later as a
secondary evidence source when restaurant records and social handles are
available.

## Dashboard controls

- Research type: Artists or Actors
- Actor language/market: configurable rather than fixed to Bollywood or Hollywood
- Time window: 7, 15, or 30 days
- Sources: Instagram, YouTube, web search, Reddit, and X
- Artist inputs: city, language, artist category, and genre/tag
- Actor inputs: language, country/market, actor, movie, or keyword filters

Artist research defaults to India-specific searches. Actor research can cover
any selected language or market, including Hindi, English, Tamil, Telugu,
Korean, Japanese, Spanish, and others.

## Shared research flow

```text
Dashboard request
    ↓
Query planner
    ↓
Platform collectors
    ↓
Raw evidence collector
    ↓
Deduplication and basic normalization
    ↓
Research summarizer
    ↓
Markdown + JSON dump
    ↓
Dashboard viewer/download
```

V0 intentionally has no database, marketplace schema, booking workflow, or
automatic outreach.

## Source roles

### Instagram

Primary source for artist discovery, reels/posts, public business contacts,
artist handles, event/performance evidence, and actor social activity.

### YouTube

Primary source for artist channels, performance videos, view/comment/like
metrics, channel descriptions, actor interviews, trailers, and appearances.

The existing `moviesTrending` YouTube snapshot and engagement logic can be
reused where useful. Preserve YouTube channel IDs and video IDs.

### Web search

Used for official profile resolution, booking pages, manager/agency details,
websites, bio-link pages, actor/movie associations, awards, releases,
interviews, and current events.

### Reddit

Optional supporting source for artist discovery, local recommendations,
organic discussion, actor/movie buzz, and controversy signals.

Reddit is not authoritative contact information.

### X

Optional supporting source for breaking announcements, current actor/movie buzz,
artist announcements, event announcements, and public conversation velocity.

X is corroboration, not the sole reason to rank an entity.

## Artist V0

Artist searches use:

```text
India
+ city
+ language
+ StarClinch L1 category
+ StarClinch L2 genre/type
```

Examples:

```text
Mumbai + singer + Bollywood
Bengaluru + DJ + EDM
Delhi + stand-up comedian
Kolkata + live band + Bengali
Hyderabad + Sufi singer
```

The output contains:

- Discovered artist names
- Platform handles
- Profile URLs
- Content URLs
- Recent activity
- Engagement metrics
- Mentioned cities and languages
- L1/L2 tag suggestions
- Public booking contacts
- Manager/agency links
- Evidence for why the artist appears relevant
- Confidence notes
- Duplicate and identity warnings

Contacts are discovered but not contacted.

## Actor V0

Actor research uses configurable language and market parameters:

```text
language = Hindi | English | Tamil | Telugu | Korean | Japanese | ...
market = India | US | UK | Global | ...
```

These are examples, not a fixed allowed list. The dashboard should allow the
research scope to be selected per run.

Actor output contains:

- Actor names
- Associated movies/shows
- Recent releases or announcements
- Trailer/interview evidence
- Social activity
- Awards
- News and public discussion
- Current momentum indicators
- Official profile and management links
- Source URLs and dates
- Confidence notes

Different languages and markets are researched separately and are not mixed
into one V0 ranking.

## Contact discovery

Only publicly listed business contacts are collected:

- Booking email
- Public business phone or WhatsApp number
- Manager or agency contact
- Official website
- Booking page
- Linktree or other bio-link page

Contact records preserve the source URL, source platform, capture time, and
confidence. Personal details must not be inferred or exposed publicly.

V0 does not send email or WhatsApp messages. WhatsApp outreach requires a
separate opt-in and approved-template workflow.

## Output format

V0 does not use database tables or dashboard tables.

Each run produces:

### Human-readable Markdown

- Research summary
- Queries executed
- Discovered entities
- Evidence by platform
- Public contacts and management links
- Recent activity
- Confidence notes
- Duplicates or uncertain matches
- Source coverage

### Raw JSON

The JSON preserves:

- Query
- Source
- URL
- Retrieved content or metadata
- Platform
- Timestamp
- Extracted names
- Metrics
- Contact candidates
- Confidence
- Processing notes

The data will be inspected before deciding the permanent schema.

## Platform usefulness measurement

Each run records:

- Queries executed
- Results returned
- Relevant results
- Unique artists or actors discovered
- Duplicate results
- Public contacts found
- Verified official profiles
- Useful engagement metrics
- Failed or blocked sources
- Run duration
- Approximate cost where available

Important derived measures:

```text
profile_resolution_rate
relevant_content_rate
unique_entity_yield
public_contact_yield
duplicate_rate
cost_per_useful_entity
```

## Search provider decision

Use the existing movie-trending search capability where practical.

Tavily is not mandatory for V0. Add a separate search provider only if:

- Search results need to be consumed programmatically
- The current search path is difficult to measure
- Contact/profile enrichment needs predictable structured results

The goal is to validate data quality before adding another paid dependency.

## Technology

Use Python for V0:

- Existing YouTube and Instagram code is reusable
- Existing Reddit logic is reusable
- Current movie velocity logic provides a useful reference
- Search, extraction, and classification can be changed quickly
- Filesystem-based outputs are sufficient before database design

## Explicitly excluded from V0

- Restaurant discovery
- Restaurant event enrichment
- Database persistence
- Public marketplace profiles
- Booking workflows
- Automatic email sending
- Automatic WhatsApp sending
- Final ranking algorithm
- Final production schema
- Full actor-universe crawling
