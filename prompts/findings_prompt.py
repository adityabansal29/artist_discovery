"""Builder for the isolated final findings synthesis phase."""

import json

from config import prompt_path


def build(args, run_dir, metadata) -> str:
    template = prompt_path(args.kind).read_text(encoding="utf-8")
    brief = json.dumps(metadata["brief"], indent=2)
    queries = "\n".join(f"- {query}" for query in metadata["queries"])
    profile_queries = "\n".join(f"- {query}" for query in metadata.get("profile_queries", [])) or "- None"
    return f"""{template}

## Research brief

```json
{brief}
```

## Initial query seeds

{queries}

## Actor identity/profile query seeds

{profile_queries}

## Selected sources

{', '.join(args.sources)}

## Evidence inputs

Read `{run_dir / 'claude_input.json'}` and the saved `web_data.json` and
`x_data.json` files when present. Treat direct collector data as primary
evidence. Do not perform Web/X searches in this phase and do not call external
tools. Use only the saved evidence files.

Write `findings.md` and `findings.json` inside `{run_dir}`. Finish by printing
`RESEARCH_WRITTEN`.
"""
