# Artist research instructions

Research Indian artists using the supplied research brief and selected
platforms. Use public information only.

Priorities:

- Find real artists, performers, bands, DJs, comedians, anchors, and similar
  bookable talent.
- Prefer official Instagram profiles, YouTube channels, websites, booking
  pages, and management pages.
- Use Reddit and X only as supporting evidence when selected.
- Extract only publicly listed business contacts. Never infer an email or phone
  number.
- When Instagram profile enrichment is available, inspect `biography`,
  `externalUrl`, `businessEmail`, and `businessPhoneNumber`; preserve the
  profile URL and mark the contact source as Instagram.
- When YouTube channel enrichment is available, inspect the channel
  description and external links for booking contacts, Instagram handles,
  websites, and management details; preserve the channel URL and mark the
  contact source as YouTube.
- Use `activity_summary` and dated posts/videos when assigning trend status.
  The summary is evidence for recent activity, not a guarantee of relevance.
- For YouTube, treat `channel_profiles` as one record per unique channel and
  use their nested `videos` list for channel activity. Do not count repeated
  channel records as separate channels.
- For artist YouTube runs, use only `channel_profiles` as primary artist
  evidence. `secondary_candidates` are un-enriched leads and must not be
  presented as confirmed artist profiles.
- Within `channel_profiles`, treat `lead_type=secondary_agency_or_vendor` as
  a secondary booking lead, not an individual artist profile. Keep it separate
  from `lead_type=primary_artist` findings.
- For YouTube, copy `activity_summary.latest_activity_date` and each video's
  `publishedAt` exactly from the evidence. Never infer or alter dates.
- Keep uncertain identity matches clearly marked.
- Do not call an artist trending from fame, follower count, or historical
  success alone. Require a source dated inside the selected window, or label
  the result `discovered, trend unverified`.
- Separate established artists from artists with fresh measurable momentum.
- For every named artist finding, use these JSON fields when evidence exists:
  `name`, `personal_details`, `biography`, `services`, `genres`,
  `official_profiles`, `news`, `videos`, `social_activity`, `awards`,
  `trend_status`, `evidence`, and `contacts`. Keep unknown fields empty or
  clearly state that no evidence was found; never infer missing profile
  details.
- Do not contact anyone.

Write these files in the current directory:

1. `findings.md`: a readable narrative report with headings and bullet lists;
   do not use Markdown tables.
2. `findings.json`: a JSON object containing `run`, `queries`, `findings`,
   `contacts`, `source_yield`, and `warnings`.
3. Use the already-saved `web_data.json` and `x_data.json` when those sources
   are selected. Do not rewrite these evidence files during synthesis.

Preserve source URLs and publication/profile dates wherever available. Mention
when a source could not be accessed. Do not invent metrics, contacts, dates,
recent events, or URLs. Treat generic biography pages as identity evidence only,
not trend evidence. Mark third-party contact claims as unverified unless the
official profile or official website shows them.
Do not run project scripts or unrelated tools. Once the requested files are
written, stop immediately and print `RESEARCH_WRITTEN`.
