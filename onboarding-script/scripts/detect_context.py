#!/usr/bin/env python3
"""Discover a company's identity + stack from whatever tooling is connected.

Probes the CLI-visible, read-only sources — GitHub (`gh`), the cloud CLIs
(`az`/`gcloud`/`vercel`) and past chat transcripts — and writes a
`company_context.json` the rest of the skill (and the agent) build on. It never
fails the run when a tool is missing: each probe records `present/authed` and the
gap is added to `sources[]`. MCP-only and doc-only sources (Notion, Linear, repo
READMEs) are left for the agent to augment afterwards (see REFERENCE.md).

Pure stdlib.

    python3 detect_context.py --out onboarding/acme/context/company_context.json
    python3 detect_context.py --org acme --keywords "widget,platform" --no-workflows
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# CLIs we name-detect (presence only) to round out the inferred stack.
OTHER_CLIS = ["aws", "flyctl", "fly", "wrangler", "kubectl", "docker", "heroku",
              "netlify", "supabase", "terraform", "pulumi", "railway", "render"]

# Repo-name signals for the "create a new project" topic.
NOTABLE_PATTERNS = {
    "skills_repo": re.compile(r"(^|[-_])skills?($|[-_])", re.I),
    "templates": re.compile(r"template|starter|boilerplate|scaffold|cookiecutter|create-", re.I),
    "dotgithub": re.compile(r"^\.github$", re.I),
}

# Substrings that hint at a deploy target inside a CI workflow file.
DEPLOY_HINTS = {
    "azure": re.compile(r"azure|az webapp|azure/webapps-deploy|azure/login", re.I),
    "gcp": re.compile(r"gcloud|google-github-actions|cloud run|gke|app engine", re.I),
    "vercel": re.compile(r"vercel", re.I),
    "aws": re.compile(r"aws-actions|amazon|s3 sync|elastic beanstalk|ecs", re.I),
    "fly": re.compile(r"fly deploy|superfly/flyctl", re.I),
    "cloudflare": re.compile(r"cloudflare|wrangler", re.I),
    "kubernetes": re.compile(r"kubectl|helm|kustomize", re.I),
    "docker": re.compile(r"docker build|docker/build-push-action|docker push", re.I),
    "npm_publish": re.compile(r"npm publish|npm-publish|release-please|changesets", re.I),
    "pages": re.compile(r"github-pages|actions/deploy-pages|peaceiris/actions-gh-pages", re.I),
}


def which(tool: str) -> str | None:
    return shutil.which(tool)


def run(cmd: list[str], timeout: int = 20) -> tuple[int, str, str]:
    """Run a command defensively: never raise, return (rc, stdout, stderr)."""
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "CLICOLOR": "0", "NO_COLOR": "1"},
        )
        return p.returncode, (p.stdout or "").strip(), (p.stderr or "").strip()
    except FileNotFoundError:
        return 127, "", "not found"
    except subprocess.TimeoutExpired:
        return 124, "", f"timeout after {timeout}s"
    except Exception as exc:  # noqa: BLE001
        return 1, "", str(exc)


def try_json(text: str):
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------- gh

def probe_github(org: str | None, want_workflows: bool,
                 wf_repos: int, wf_files: int) -> dict:
    out: dict = {"tool": "gh", "present": bool(which("gh")), "authed": False}
    if not out["present"]:
        out["detail"] = "gh CLI not on PATH"
        return out

    rc, _, _ = run(["gh", "auth", "status"])
    out["authed"] = rc == 0
    if not out["authed"]:
        out["detail"] = "gh present but not authenticated (`gh auth login`)"
        return out

    user = try_json(run(["gh", "api", "user"])[1]) or {}
    out["login"] = user.get("login")
    orgs = try_json(run(["gh", "api", "user/orgs"])[1]) or []
    out["orgs"] = [o.get("login") for o in orgs if isinstance(o, dict)]

    owner = org or out.get("login")
    out["selected_owner"] = owner
    if len(out["orgs"]) > 1 and not org:
        out["ambiguous_owner"] = True  # agent should ask which org

    # Owner profile (org or user).
    prof = try_json(run(["gh", "api", f"orgs/{owner}"])[1]) if owner else None
    if not prof:
        prof = try_json(run(["gh", "api", f"users/{owner}"])[1]) if owner else None
    if prof:
        out["owner_profile"] = {
            "name": prof.get("name") or prof.get("login"),
            "description": prof.get("description") or prof.get("bio"),
            "blog": prof.get("blog"),
            "type": prof.get("type"),
            "public_repos": prof.get("public_repos"),
        }

    # Repos.
    fields = "name,description,primaryLanguage,repositoryTopics,defaultBranchRef,isTemplate,url,visibility,updatedAt"
    repos_raw = try_json(run(
        ["gh", "repo", "list", owner, "--limit", "100", "--json", fields], timeout=40
    )[1]) or []
    repos = []
    for r in repos_raw:
        repos.append({
            "name": r.get("name"),
            "description": r.get("description"),
            "language": (r.get("primaryLanguage") or {}).get("name"),
            "topics": [t.get("name") for t in (r.get("repositoryTopics") or []) if isinstance(t, dict)],
            "default_branch": (r.get("defaultBranchRef") or {}).get("name") or "main",
            "is_template": r.get("isTemplate", False),
            "visibility": r.get("visibility"),
            "url": r.get("url"),
            "updated_at": r.get("updatedAt"),
        })
    out["repos"] = repos

    # Notable repos for the create-project topic.
    notable = {"skills_repo": None, "templates": [], "dotgithub": None, "template_flagged": []}
    for r in repos:
        nm = r["name"] or ""
        if NOTABLE_PATTERNS["skills_repo"].search(nm) and not notable["skills_repo"]:
            notable["skills_repo"] = f"{owner}/{nm}"
        if NOTABLE_PATTERNS["templates"].search(nm):
            notable["templates"].append(f"{owner}/{nm}")
        if NOTABLE_PATTERNS["dotgithub"].match(nm):
            notable["dotgithub"] = f"{owner}/{nm}"
        if r["is_template"]:
            notable["template_flagged"].append(f"{owner}/{nm}")
    out["notable"] = notable

    # CI workflows -> deploy hints (bounded).
    out["workflows"] = []
    if want_workflows and owner:
        candidates = []
        # Prefer the notable repos, then the most recently updated ones.
        seen = set()
        for key in ("template_flagged", "templates"):
            for full in notable.get(key, []):
                nm = full.split("/", 1)[1]
                if nm not in seen:
                    candidates.append(nm); seen.add(nm)
        for r in sorted(repos, key=lambda x: x.get("updated_at") or "", reverse=True):
            if r["name"] not in seen:
                candidates.append(r["name"]); seen.add(r["name"])
        for nm in candidates[:wf_repos]:
            listing = try_json(run(
                ["gh", "api", f"repos/{owner}/{nm}/contents/.github/workflows"], timeout=20
            )[1])
            if not isinstance(listing, list):
                continue
            hits: dict[str, list[str]] = {}
            for f in listing[:wf_files]:
                path = f.get("path")
                if not path or not str(path).endswith((".yml", ".yaml")):
                    continue
                content = run(
                    ["gh", "api", f"repos/{owner}/{nm}/contents/{path}",
                     "--jq", ".content"], timeout=20
                )[1]
                text = ""
                if content:
                    try:
                        import base64
                        text = base64.b64decode(content).decode("utf-8", "ignore")
                    except Exception:  # noqa: BLE001
                        text = ""
                targets = [name for name, rx in DEPLOY_HINTS.items() if rx.search(text)]
                if targets:
                    hits.setdefault(nm, []).extend(targets)
            if hits.get(nm):
                out["workflows"].append({"repo": f"{owner}/{nm}", "deploy_hints": sorted(set(hits[nm]))})
    out["detail"] = f"{len(repos)} repos under {owner}"
    return out


# ------------------------------------------------------------------------ cloud

def probe_azure() -> dict:
    o = {"tool": "az", "present": bool(which("az")), "authed": False, "projects": []}
    if not o["present"]:
        return o
    acc = try_json(run(["az", "account", "show", "-o", "json"])[1])
    if acc:
        o["authed"] = True
        o["identity"] = {
            "subscription": acc.get("name"),
            "subscription_id": acc.get("id"),
            "tenant_id": acc.get("tenantId"),
            "user": (acc.get("user") or {}).get("name"),
        }
    return o


def probe_gcloud() -> dict:
    o = {"tool": "gcloud", "present": bool(which("gcloud")), "authed": False, "projects": []}
    if not o["present"]:
        return o
    cfg = try_json(run(["gcloud", "config", "list", "--format=json"])[1]) or {}
    account = (cfg.get("core") or {}).get("account")
    project = (cfg.get("core") or {}).get("project")
    if account:
        o["authed"] = True
        o["identity"] = {"account": account, "project": project}
    projs = try_json(run(
        ["gcloud", "projects", "list", "--format=json", "--limit=25"], timeout=30
    )[1]) or []
    o["projects"] = [
        {"id": p.get("projectId"), "name": p.get("name")}
        for p in projs if isinstance(p, dict)
    ]
    return o


def probe_vercel() -> dict:
    o = {"tool": "vercel", "present": bool(which("vercel")), "authed": False, "projects": []}
    if not o["present"]:
        return o
    rc, who, _ = run(["vercel", "whoami"], timeout=25)
    if rc == 0 and who:
        o["authed"] = True
        o["identity"] = {"account": who.splitlines()[-1].strip()}
    rc, ls, _ = run(["vercel", "projects", "ls"], timeout=30)
    if rc == 0 and ls:
        names = []
        for line in ls.splitlines():
            line = line.strip()
            # skip headers / decoration; keep plausible project tokens
            if not line or line.lower().startswith(("vercel", "project", ">", "?")):
                continue
            tok = line.split()[0]
            if re.match(r"^[a-zA-Z0-9][\w.-]*$", tok):
                names.append(tok)
        o["projects"] = names[:25]
    return o


# ------------------------------------------------------------------- transcripts

def find_transcript_dirs(explicit: str | None) -> list[Path]:
    dirs: list[Path] = []
    if explicit:
        p = Path(explicit).expanduser()
        if p.is_dir():
            dirs.append(p)
        return dirs
    cwd = Path.cwd().resolve()
    base = Path.home() / ".cursor" / "projects"
    # Cursor slugifies the abs path (/ -> -, leading - stripped).
    slug = str(cwd).replace(os.sep, "-").lstrip("-")
    guess = base / slug / "agent-transcripts"
    if guess.is_dir():
        dirs.append(guess)
    if base.is_dir():  # fallback: any project dir mentioning this repo folder
        needle = cwd.name.lower()
        for d in base.glob("*/agent-transcripts"):
            if d not in dirs and needle in d.parent.name.lower():
                dirs.append(d)
    return dirs


def scan_transcripts(dirs: list[Path], keywords: list[str], max_hits: int = 12) -> dict:
    out = {"dirs": [str(d) for d in dirs], "files_scanned": 0, "matches": []}
    if not keywords:
        return out
    rx = re.compile("|".join(re.escape(k) for k in keywords if k), re.I)
    for d in dirs:
        for f in sorted(d.rglob("*.jsonl")):
            out["files_scanned"] += 1
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:  # noqa: BLE001
                continue
            snippets = []
            for m in rx.finditer(text):
                if len(snippets) >= 3:
                    break
                s = max(0, m.start() - 60)
                snippets.append(re.sub(r"\s+", " ", text[s:m.end() + 60]).strip())
            if snippets:
                out["matches"].append({"file": f.name, "hits": snippets})
            if len(out["matches"]) >= max_hits:
                return out
    return out


# --------------------------------------------------------------------- assembly

def infer_stack(gh: dict, clouds: list[dict], others: list[dict]) -> list[str]:
    stack: list[str] = []
    langs = {r.get("language") for r in gh.get("repos", []) if r.get("language")}
    stack.extend(sorted(langs))
    for c in clouds:
        if c.get("authed"):
            stack.append({"az": "Azure", "gcloud": "Google Cloud", "vercel": "Vercel"}.get(c["tool"], c["tool"]))
    stack.extend(o["tool"] for o in others if o.get("present"))
    for wf in gh.get("workflows", []):
        stack.extend(wf.get("deploy_hints", []))
    # de-dup, keep order
    seen, res = set(), []
    for s in stack:
        if s and s.lower() not in seen:
            seen.add(s.lower()); res.append(s)
    return res


def resolve_company(gh: dict, override: str | None) -> dict:
    if override:
        return {"name": override, "slug": slugify(override), "kind": "explicit"}
    owner = gh.get("selected_owner")
    if owner:
        prof = gh.get("owner_profile") or {}
        kind = "github_org" if prof.get("type") == "Organization" else "github_account"
        return {
            "name": prof.get("name") or owner,
            "login": owner,
            "slug": slugify(owner),
            "kind": kind,
            "description": prof.get("description"),
            "url": f"https://github.com/{owner}",
        }
    return {"name": "unknown", "slug": "company", "kind": "unknown"}


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-") or "company"


# Consumer email domains that don't identify a company.
CONSUMER_DOMAINS = {"gmail.com", "googlemail.com", "outlook.com", "hotmail.com",
                    "live.com", "icloud.com", "yahoo.com", "proton.me", "protonmail.com"}


def collect_company_candidates(gh: dict, clouds: list[dict]) -> list[dict]:
    """Aggregate every probable company across the connected sources.

    The same name seen in more than one source (e.g. a gh login that is also a
    Vercel team) is merged and gains a stronger multi-source signal.
    """
    cands: dict[str, dict] = {}

    def add(name: str | None, kind: str, source: str, signal: str) -> None:
        if not name:
            return
        slug = slugify(name)
        if slug == "company":
            return
        c = cands.setdefault(slug, {"name": name, "slug": slug, "kind": kind,
                                    "sources": [], "signals": []})
        if source not in c["sources"]:
            c["sources"].append(source)
        if signal and signal not in c["signals"]:
            c["signals"].append(signal)

    if gh.get("authed"):
        add(gh.get("login"), "github_account", "gh", "authenticated GitHub login")
        for o in gh.get("orgs", []) or []:
            add(o, "github_org", "gh", "GitHub org membership")

    for c in clouds:
        if not c.get("authed"):
            continue
        ident = c.get("identity", {}) or {}
        if c["tool"] == "gcloud":
            acct = ident.get("account") or ""
            dom = acct.split("@", 1)[1].lower() if "@" in acct else ""
            if dom and dom not in CONSUMER_DOMAINS:
                add(dom.split(".")[0], "gcloud", "gcloud", f"GCP account domain {dom}")
            elif ident.get("project"):
                add(ident["project"], "gcloud", "gcloud", f"active GCP project {ident['project']}")
        elif c["tool"] == "vercel":
            add(ident.get("account"), "vercel", "vercel", "Vercel account/team")
        elif c["tool"] == "az":
            add(ident.get("subscription"), "az", "az", "Azure subscription")

    return list(cands.values())


def choose_company(candidates: list[dict], gh: dict, override: str | None) -> dict:
    """Pick a default company and decide whether the user must disambiguate."""
    if override:
        slug = slugify(override)
        return {"selected": slug, "needs_user_choice": False, "reason": "explicit --company/--org"}
    if not candidates:
        return {"selected": None, "needs_user_choice": False, "reason": "no company detected"}
    if len(candidates) == 1:
        return {"selected": candidates[0]["slug"], "needs_user_choice": False, "reason": "single probable company"}

    kind_bonus = {"github_org": 3, "github_account": 2, "vercel": 1, "az": 1, "gcloud": 1}

    def score(c: dict) -> tuple[int, int]:
        return (len(c.get("sources", [])), kind_bonus.get(c.get("kind"), 0))

    best = max(candidates, key=score)
    return {"selected": best["slug"], "needs_user_choice": True,
            "reason": f"{len(candidates)} probable companies — ask the user to choose"}


def company_from_selection(selection: dict, candidates: list[dict], gh: dict,
                           override: str | None) -> dict:
    """Build the resolved `company` block from the chosen candidate."""
    if override:
        return {"name": override, "slug": slugify(override), "kind": "explicit"}
    sel = selection.get("selected")
    cand = next((c for c in candidates if c["slug"] == sel), None)
    if not cand:
        return resolve_company(gh, None)
    company = {"name": cand["name"], "slug": cand["slug"], "kind": cand["kind"],
               "sources": cand["sources"]}
    # Enrich a GitHub owner with its profile + url.
    if cand["kind"] in ("github_org", "github_account"):
        company["login"] = cand["name"]
        company["url"] = f"https://github.com/{cand['name']}"
        if gh.get("selected_owner") == cand["name"]:
            prof = gh.get("owner_profile") or {}
            company["name"] = prof.get("name") or cand["name"]
            company["description"] = prof.get("description")
    return company


def main() -> int:
    ap = argparse.ArgumentParser(description="Discover company identity + stack from connected tools.")
    ap.add_argument("--org", help="GitHub org/owner to profile (default: authed login)")
    ap.add_argument("--company", help="Override the resolved company name")
    ap.add_argument("--keywords", default="", help="Comma-separated extra keywords to grep transcripts for")
    ap.add_argument("--transcripts-dir", help="Explicit agent-transcripts dir (else auto-detected)")
    ap.add_argument("--no-workflows", action="store_true", help="Skip fetching CI workflow files (faster)")
    ap.add_argument("--workflow-repos", type=int, default=4, help="Max repos to scan for CI workflows")
    ap.add_argument("--workflow-files", type=int, default=3, help="Max workflow files per repo")
    ap.add_argument("--out", type=Path, default=Path("onboarding/company/context/company_context.json"))
    args = ap.parse_args()

    gh = probe_github(args.org, not args.no_workflows, args.workflow_repos, args.workflow_files)
    clouds = [probe_azure(), probe_gcloud(), probe_vercel()]
    others = [{"tool": t, "present": bool(which(t))} for t in OTHER_CLIS]
    others = [o for o in others if o["present"]]

    candidates = collect_company_candidates(gh, clouds)
    selection = choose_company(candidates, gh, args.company)
    company = company_from_selection(selection, candidates, gh, args.company)

    # Grep transcripts for the chosen company AND every other probable one.
    kw = [k.strip() for k in args.keywords.split(",") if k.strip()]
    for extra in [company.get("login"), company.get("name")] + [c["name"] for c in candidates]:
        if extra and extra not in kw:
            kw.append(extra)
    tdirs = find_transcript_dirs(args.transcripts_dir)
    transcripts = scan_transcripts(tdirs, kw)

    # sources[] status roll-up.
    def status(present, authed, ok_detail, miss_detail):
        if not present:
            return {"status": "missing", "detail": miss_detail}
        if not authed:
            return {"status": "unauthenticated", "detail": miss_detail}
        return {"status": "ok", "detail": ok_detail}

    sources = []
    sources.append({"source": "github", **status(
        gh["present"], gh.get("authed"), gh.get("detail", ""), gh.get("detail", "gh not usable"))})
    for c in clouds:
        sources.append({"source": c["tool"], **status(
            c["present"], c.get("authed"),
            f"{c['tool']}: {c.get('identity', {})}", f"{c['tool']} not usable")})
    sources.append({"source": "transcripts",
                    "status": "ok" if transcripts["files_scanned"] else "missing",
                    "detail": f"{transcripts['files_scanned']} file(s), {len(transcripts['matches'])} match(es)"})
    # MCP + doc sources the agent must fill.
    for s in ("notion_mcp", "linear_mcp", "repo_docs"):
        sources.append({"source": s, "status": "unknown", "detail": "agent to augment (see REFERENCE.md)"})

    stack = infer_stack(gh, clouds, others)

    # Pre-populate what we can; leave the rest for the agent to ground + confirm.
    tools_accounts = []
    if gh.get("authed"):
        tools_accounts.append({"tool": "GitHub", "detail": company.get("url"), "source": "gh"})
    for c in clouds:
        if c.get("authed"):
            tools_accounts.append({"tool": {"az": "Azure", "gcloud": "Google Cloud", "vercel": "Vercel"}[c["tool"]],
                                    "detail": c.get("identity"), "source": c["tool"]})
    deploy_hints = sorted({h for wf in gh.get("workflows", []) for h in wf.get("deploy_hints", [])})

    gaps = []
    if selection.get("needs_user_choice"):
        names = ", ".join(c["name"] for c in candidates)
        gaps.append(f"Multiple probable companies ({names}) — ask the user which is correct, "
                    f"then re-run with --company/--org.")
    if not gh.get("authed"):
        gaps.append("GitHub not authed — company identity + create-project/deploy from CI are unknown.")
    if not any(c.get("authed") for c in clouds):
        gaps.append("No cloud CLI authed (az/gcloud/vercel) — confirm the deploy target with the user.")
    if not deploy_hints:
        gaps.append("No deploy hints found in CI workflows — confirm 'how we deploy' with the user or a doc.")
    if not transcripts["matches"]:
        gaps.append("No company-specific chat transcripts matched — rely on docs/MCP or confirm facts.")
    gaps.append("facts{} (mission/values/best_practices/create_project/deploy) need agent augmentation + user sign-off.")

    context = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "company": company,
        "company_candidates": candidates,
        "company_selection": selection,
        "github": gh,
        "clouds": clouds,
        "other_clis": others,
        "transcripts": transcripts,
        "mcp": {"notion": "unknown", "linear": "unknown"},
        "stack_inferred": stack,
        "sources": sources,
        "facts": {
            "mission": None,
            "values": [],
            "team": None,
            "tools_accounts": tools_accounts,
            "best_practices": {"summary": None, "items": [], "sources": []},
            "create_project": {"summary": None, "steps": [], "sources": [],
                               "skills_repo": (gh.get("notable") or {}).get("skills_repo"),
                               "templates": (gh.get("notable") or {}).get("templates", [])},
            "deploy": {"summary": None, "steps": [], "sources": [], "hints": deploy_hints},
        },
        "gaps": gaps,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Human summary.
    print(f"  -> {args.out}")
    print("-" * 64)
    print(f"Company : {company['name']}  ({company['kind']})")
    if len(candidates) > 1:
        print("Probable companies (across sources):")
        for c in candidates:
            pick = " <- default" if c["slug"] == selection.get("selected") else ""
            print(f"  - {c['name']}  [{', '.join(c['sources'])}]{pick}")
        if selection.get("needs_user_choice"):
            print("  ** ASK THE USER which company is correct, then re-run with --company/--org. **")
    print(f"Stack   : {', '.join(stack) or '—'}")
    print("Sources :")
    for s in sources:
        mark = {"ok": "[ok]", "missing": "[--]", "unauthenticated": "[!!]", "unknown": "[??]"}.get(s["status"], "[??]")
        print(f"  {mark} {s['source']:<12} {s['detail']}")
    if deploy_hints:
        print(f"Deploy  : hints from CI -> {', '.join(deploy_hints)}")
    print("Gaps    :")
    for g in gaps:
        print(f"  - {g}")
    print("-" * 64)
    print("Next: augment mcp{}/facts{} (Notion/Linear/repo docs/transcripts), confirm with the user,")
    print("      then scaffold_curriculum.py.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
