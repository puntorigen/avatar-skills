#!/usr/bin/env python3
"""Plan an ordered onboarding curriculum -> curriculum.json.

Uses the user's guideline (a custom --episodes-file) OR, when none is given, the
minimum default onboarding curriculum. Grounds `company`, `language` and each
episode's `demo_targets`/`sources` in a company_context.json when provided.

Pure stdlib.

    # default minimum curriculum, grounded in the discovered context
    python3 scaffold_curriculum.py --context onboarding/acme/context/company_context.json \
        --language en --audience "new engineer" --seconds 45 \
        --out onboarding/acme/curriculum.json

    # custom set of topics
    python3 scaffold_curriculum.py --context .../company_context.json \
        --episodes-file my_topics.json --out onboarding/acme/curriculum.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# The minimum default onboarding curriculum (proposed when no guideline given).
# Each entry: id, title, objective, topics, demo (whether it usually needs a
# screen recording). `context_fill` names a hook the script uses to inject
# discovered facts into demo_targets/sources.
DEFAULT_CURRICULUM = [
    {
        "id": "welcome",
        "title": "Welcome & company intro",
        "objective": "Make the new hire feel welcome and understand our mission, values, team and what we build.",
        "topics": ["mission", "values", "team", "what we build"],
        "demo": False,
        "context_fill": "company",
    },
    {
        "id": "tools-accounts",
        "title": "Tools & accounts we use",
        "objective": "Show the stack and the accounts to request so the new hire can get set up on day one.",
        "topics": ["the stack", "accounts to request", "how to get access"],
        "demo": True,
        "context_fill": "tools",
    },
    {
        "id": "best-practices",
        "title": "Engineering best practices",
        "objective": "Explain how we write and ship code: branching, pull requests, reviews and coding standards.",
        "topics": ["branching", "pull requests", "code review", "coding standards"],
        "demo": False,
        "context_fill": "best_practices",
    },
    {
        "id": "create-project",
        "title": "Create a new project with the company skills",
        "objective": "Walk through bootstrapping a new project the way we do it, using our templates/skills.",
        "topics": ["templates/skills", "scaffolding a repo", "first commit"],
        "demo": True,
        "context_fill": "create_project",
    },
    {
        "id": "deploy",
        "title": "How we deploy",
        "objective": "Show the real path from a merged PR to production on our cloud, including CI/CD.",
        "topics": ["CI/CD", "environments", "cloud deploy", "rollbacks"],
        "demo": True,
        "context_fill": "deploy",
    },
    {
        "id": "get-help",
        "title": "Where to get help & what's next",
        "objective": "Point the new hire to people, docs and rituals so they know where to turn next.",
        "topics": ["who to ask", "docs", "rituals/ceremonies", "next steps"],
        "demo": False,
        "context_fill": "help",
    },
]


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-") or "topic"


def load_context(path: Path | None) -> dict:
    if not path:
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"WARN  could not read context {path}: {exc}", file=sys.stderr)
        return {}


def demo_targets_for(fill: str, ctx: dict) -> list[dict]:
    """Suggest screen-recording targets grounded in the discovered context."""
    facts = ctx.get("facts", {}) or {}
    gh = ctx.get("github", {}) or {}
    out: list[dict] = []
    if fill == "tools":
        url = (ctx.get("company") or {}).get("url")
        if url:
            out.append({"url": url, "intent": "Tour the GitHub org: repos, teams, projects."})
    elif fill == "create_project":
        cp = facts.get("create_project", {}) or {}
        repo = cp.get("skills_repo") or (gh.get("notable") or {}).get("skills_repo")
        if repo:
            out.append({"url": f"https://github.com/{repo}",
                        "intent": f"Open {repo} and show how a new project is scaffolded from it."})
        for t in (cp.get("templates") or (gh.get("notable") or {}).get("templates", []))[:1]:
            out.append({"url": f"https://github.com/{t}",
                        "intent": f"Use the {t} template to create a new repo."})
    elif fill == "deploy":
        hints = (facts.get("deploy", {}) or {}).get("hints", [])
        label = ", ".join(hints) if hints else "our cloud"
        out.append({"url": "", "intent": f"Show a deploy running in CI to {label} (fill the real URL/console)."})
    return out


def sources_for(fill: str, ctx: dict) -> list[str]:
    src = []
    facts = ctx.get("facts", {}) or {}
    if fill == "create_project":
        cp = facts.get("create_project", {}) or {}
        if cp.get("skills_repo"):
            src.append(cp["skills_repo"])
    if fill == "deploy":
        for wf in (ctx.get("github", {}) or {}).get("workflows", []):
            src.append(f"{wf.get('repo')} CI ({', '.join(wf.get('deploy_hints', []))})")
    return src


def build_episodes(spec: list[dict], ctx: dict, language: str,
                   audience: str, seconds: int) -> list[dict]:
    episodes = []
    for i, e in enumerate(spec, start=1):
        eid = e.get("id") or slugify(e.get("title", f"topic-{i}"))
        slug = f"{i:02d}_{slugify(eid)}"
        fill = e.get("context_fill", "")
        episodes.append({
            "id": eid,
            "order": i,
            "slug": slug,
            "title": e.get("title", eid.replace("-", " ").title()),
            "objective": e.get("objective", ""),
            "audience": e.get("audience", audience),
            "language": e.get("language", language),
            "target_seconds": int(e.get("target_seconds", seconds)),
            "topics": e.get("topics", []),
            "needs_demo": bool(e.get("demo", False)),
            "demo_targets": e.get("demo_targets") or demo_targets_for(fill, ctx),
            "sources": e.get("sources") or sources_for(fill, ctx),
        })
    return episodes


def main() -> int:
    ap = argparse.ArgumentParser(description="Plan an ordered onboarding curriculum.")
    ap.add_argument("--context", type=Path, help="company_context.json from detect_context.py")
    ap.add_argument("--company", help="Override the company name/slug")
    ap.add_argument("--language", default="en", help="Spoken language code (default: en)")
    ap.add_argument("--audience", default="new team member", help="Who the series is for")
    ap.add_argument("--seconds", type=int, default=45, help="Default target seconds per episode")
    ap.add_argument("--episodes-file", type=Path,
                    help="Custom episodes JSON (list of {id,title,objective,topics,demo,demo_targets,sources})")
    ap.add_argument("--guideline", default="", help="Free-text note recording the user's guideline")
    ap.add_argument("--out", type=Path, default=Path("onboarding/company/curriculum.json"))
    ap.add_argument("--force", action="store_true", help="Overwrite if the file exists")
    args = ap.parse_args()

    ctx = load_context(args.context)
    company = args.company or (ctx.get("company") or {}).get("slug") or "company"
    company_name = (ctx.get("company") or {}).get("name") or company

    if args.episodes_file:
        try:
            spec = json.loads(args.episodes_file.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"ERROR: could not read --episodes-file: {exc}", file=sys.stderr)
            return 1
        if not isinstance(spec, list) or not spec:
            print("ERROR: --episodes-file must be a non-empty JSON list", file=sys.stderr)
            return 1
        guideline = args.guideline or "custom (from --episodes-file)"
    else:
        spec = DEFAULT_CURRICULUM
        guideline = args.guideline or "default-minimum"

    episodes = build_episodes(spec, ctx, args.language, args.audience, args.seconds)

    curriculum = {
        "company": company,
        "company_name": company_name,
        "language": args.language,
        "audience": args.audience,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "guideline": guideline,
        "context_path": str(args.context) if args.context else None,
        "episodes": episodes,
    }

    if args.out.exists() and not args.force:
        print(f"ERROR: {args.out} exists (use --force to overwrite)", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(curriculum, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"  -> {args.out}")
    print(f"  Company: {company_name}  ·  Language: {args.language}  ·  {len(episodes)} episodes ({guideline})")
    for e in episodes:
        demo = "  [demo]" if e["needs_demo"] else ""
        print(f"   {e['order']:>2}. {e['title']}{demo}")
    print("  Next: scaffold_episode.py --curriculum " + str(args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
