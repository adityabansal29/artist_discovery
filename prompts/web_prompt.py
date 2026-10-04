"""Builder for the isolated Web/X evidence phase."""


def build(args, run_dir, metadata) -> str:
    queries = "\n".join(f"- {query}" for query in metadata["queries"])
    profile_queries = "\n".join(f"- {query}" for query in metadata.get("profile_queries", [])) or "- None"
    return f"""You are the Web/X evidence collection phase of a {args.kind} research run.

Read `{run_dir / 'claude_input.json'}` for direct collector evidence and use it
to understand the research topic. Search only the selected Web/X sources below.
Use the initial queries as the search plan; do not recursively search every
artist. Limit external search work to at most 8 calls total.

Selected sources: {', '.join(args.sources)}

Initial queries:
{queries}

Web-only identity/profile queries (use these for Web, never prepend them to X queries):
{profile_queries}

Write only the selected evidence files in `{run_dir}`:
- `web_data.json` when Web is selected
- `x_data.json` when X is selected

Each file must contain `source`, `queries`, `results`, and `warnings`. Preserve
actual URLs, dates, snippets, and relevance notes. Write an empty results list
when no usable evidence is found. Do not write findings.md or findings.json.
After the evidence files are written, print `WEB_EVIDENCE_WRITTEN` and stop.
"""
