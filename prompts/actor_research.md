# Actor research instructions

Research movie actors for the supplied language and market. The language and
market are configurable; do not assume Bollywood or Hollywood unless selected.

Priorities:

- When no specific actor or movie is supplied, produce a discovery shortlist of
  up to 30 named actors relevant to the selected language and market. Use Web
  sources to identify the names, then attach IMDb/TMDB identity links and
  profile details where available. Do not treat a popularity list alone as
  evidence that an actor is currently trending.
- For a named actor or movie, use IMDb and The Movie Database (TMDB) Web
  results for identity/profile details such as biography, known-for works,
  filmography, and official profile URLs. Treat them as identity/background
  sources, not proof of current trend.
- Find current actor/movie activity inside the selected research window.
- Use official profiles, trailers, interviews, release announcements, awards,
  and credible entertainment coverage.
- Use Reddit and X only as supporting evidence when selected.
- Include public management or official contact links when available, but do
  not infer personal contact information.
- Use `activity_summary` and dated posts/videos when assigning trend status.
  The summary is evidence for recent activity, not a guarantee of relevance.
- For YouTube, treat `channel_profiles` as one record per unique channel and
  use their nested `videos` list for channel activity. Do not count repeated
  channel records as separate channels.
- For YouTube, copy `activity_summary.latest_activity_date` and each video's
  `publishedAt` exactly from the evidence. Never infer or alter dates.
- Keep uncertain actor/movie identity matches clearly marked.
- Do not call an actor trending from fame, follower count, or an old film alone.
  Require a source dated inside the selected window, or label the result
  `discovered, trend unverified`.
- For every named actor finding, use these JSON fields when evidence exists:
  `actor`, `personal_details`, `biography`, `official_profiles`, `genres`,
  `filmography`, `upcoming_projects`, `awards`, `news`, `videos`,
  `social_activity`, `trend_status`, `evidence`, and `contacts`. Keep unknown
  fields empty or clearly state that no evidence was found; never infer missing
  filmography or awards.

Write these files in the current directory:

1. `findings.md`: a readable narrative report with headings and bullet lists;
   do not use Markdown tables.
2. `findings.json`: a JSON object containing `run`, `queries`, `findings`,
   `contacts`, `source_yield`, and `warnings`.
3. `web_data.json` when Web is selected: saved Web search results and warnings.
4. `x_data.json` when X is selected: saved X search results and warnings.

Preserve source URLs and publication/profile dates wherever available. Mention
when a source could not be accessed. Do not invent metrics, contacts, dates,
recent events, or URLs. Treat generic biography pages as identity evidence only,
not trend evidence. Mark third-party contact claims as unverified unless the
official profile or official website shows them.
Do not run project scripts or unrelated tools. Once the requested files are
written, stop immediately and print `RESEARCH_WRITTEN`.
