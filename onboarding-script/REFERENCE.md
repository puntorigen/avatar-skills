# Onboarding Script — reference

The discovery playbook (how the agent augments the machine-detected context),
the JSON schemas, the tool-to-topic map, and the degrade-gracefully rules.

## Discovery playbook

`detect_context.py` covers the **CLI-visible** sources. You (the agent) then
augment `company_context.json` with the sources a script can't reach (MCPs, repo
docs) and fill the `facts{}` block. Ground every claim; never invent internal
process — mark unknowns `[TO CONFIRM]` and confirm with the user.

### GitHub (`gh`) — identity, create-project, deploy

Already probed by the script (login, orgs, repos, notable repos, CI deploy
hints). Deepen the two action topics by reading the flagged repos:

```bash
OWNER=<org>; REPO=<skills-or-template-repo>
gh api repos/$OWNER/$REPO/readme --jq '.content' | base64 -d | head -c 4000
gh api repos/$OWNER/$REPO/contents/CONTRIBUTING.md --jq '.content' 2>/dev/null | base64 -d | head -c 4000
gh api repos/$OWNER/$REPO/contents/.github/workflows --jq '.[].name'
# read a specific workflow to ground "how we deploy"
gh api repos/$OWNER/$REPO/contents/.github/workflows/deploy.yml --jq '.content' | base64 -d
```

Put the concrete steps into `facts.create_project.steps[]` and
`facts.deploy.steps[]`, each with the repo/workflow it came from in `sources[]`.

### Notion MCP (if connected)

Detect it first (inspect the MCP servers). If present, search for the handbook
and process docs and pull the relevant pages. Typical queries:
- "onboarding" / "new hire" / "getting started" / "handbook"
- "engineering guidelines" / "code review" / "branching" / "definition of done"
- "deploy" / "release" / "runbook" / "infrastructure"
- "tools" / "accounts" / "access" / "provisioning"

Record `mcp.notion = "connected"` and cite each page title/URL used in the
episode's `sources[]`. If no Notion MCP is connected, set `mcp.notion = "absent"`
and rely on the other sources.

### Linear MCP (if connected)

If present, read the real "how we work":
- teams + members (who owns what)
- workflow states (the actual pipeline: Backlog -> ... -> Done)
- labels, cycles/sprints, and any Linear "Documents"
- a couple of representative projects/issues to show the flow

Feed this into the **best-practices** and **get-help** episodes. Record
`mcp.linear = "connected"` (or `"absent"`), cite what you used.

### Chat transcripts

`detect_context.py` greps this project's `agent-transcripts/*.jsonl` for the
company/stack keywords and records matches. Read the matched files for
company-specific decisions (stack choices, deploy quirks, naming conventions).
Treat them as **hints**, not authority — confirm anything you'll state as fact.

### Public info (optional, intro only)

A `perplexity_ask` MCP (if present) can enrich the **welcome** episode with
*public* positioning only. Never use it to fabricate internal process.

## Degrade-gracefully rules

- Every source is optional. A missing source is recorded in `sources[]` with
  `status` ∈ `ok | missing | unauthenticated | unknown` and added to `gaps[]`.
- For any fact you can't ground, write the copy with a `[TO CONFIRM]` marker and
  surface it in the confirmation step (workflow step 2). `check_episode.py` warns
  on residual `[TO CONFIRM]`.
- Prefer asking one targeted question over guessing. In particular, when
  `company_selection.needs_user_choice` is true (more than one probable company
  across gh/gcloud/vercel/az), ask the user to pick from `company_candidates[]`
  and re-run with `--company`/`--org`. Likewise ask "What's our deploy target?"
  when no cloud CLI is authed and CI has no hints.

## Tool -> topic map

Which discovered source primarily feeds which episode:

- **Welcome & company intro** <- gh owner profile, Notion handbook, public info.
- **Tools & accounts** <- gh org, clouds (`az`/`gcloud`/`vercel`), other CLIs, Notion "accounts/access".
- **Best practices** <- gh CONTRIBUTING + branch protection, Linear workflow states, Notion "engineering guidelines".
- **Create a new project** <- gh `skills`/`templates`/`.github` repo READMEs, `npx skills add`, template repos.
- **How we deploy** <- gh `.github/workflows/*.yml` deploy hints + the authed cloud CLI (Azure/GCP/Vercel), Notion runbook.
- **Get help & next** <- Linear teams/owners, Notion index, gh CODEOWNERS.

## Cloud CLI probes (first-class, read-only)

- **Azure** `az`: `az account show -o json` -> subscription/tenant/user.
- **GCP** `gcloud`: `gcloud config list --format=json` + `gcloud projects list --format=json --limit=25`.
- **Vercel** `vercel`: `vercel whoami` + `vercel projects ls`.
- **Name-detected** (presence only): `aws`, `flyctl`/`fly`, `wrangler`, `kubectl`, `docker`, `heroku`, `netlify`, `supabase`, `terraform`, `pulumi`, `railway`, `render`.

Each records `{tool, present, authed, identity?, projects[]}`.

## Schemas

### company_context.json

```
generated_at        ISO timestamp
company             { name, login?, slug, kind, description?, url?, sources[] }   # the resolved/selected one
company_candidates[] { name, slug, kind: github_org|github_account|gcloud|vercel|az,
                       sources[], signals[] }   # every probable company, merged across sources
company_selection   { selected: <slug|null>, needs_user_choice: bool, reason }   # ask the user when true
github              { present, authed, login, orgs[], selected_owner, ambiguous_owner?,
                      owner_profile{}, repos[]{name,description,language,topics,default_branch,is_template,visibility,url,updated_at},
                      notable{ skills_repo, templates[], dotgithub, template_flagged[] },
                      workflows[]{ repo, deploy_hints[] } }
clouds[]            { tool: az|gcloud|vercel, present, authed, identity?{}, projects[] }
other_clis[]        { tool, present }
transcripts         { dirs[], files_scanned, matches[]{file, hits[]} }
mcp                 { notion: unknown|connected|absent, linear: ... }   # agent fills
stack_inferred[]    strings
sources[]           { source, status: ok|missing|unauthenticated|unknown, detail }
facts               { mission, values[], team,
                      tools_accounts[]{tool,detail,source},
                      best_practices{summary,items[],sources[]},
                      create_project{summary,steps[],sources[],skills_repo,templates[]},
                      deploy{summary,steps[],sources[],hints[]} }               # agent fills
gaps[]              strings (assumptions to confirm)
```

### curriculum.json

```
company, company_name, language, audience, generated_at, guideline, context_path
episodes[] { id, order, slug, title, objective, audience, language,
             target_seconds, topics[], needs_demo, demo_targets[]{url,intent}, sources[] }
```

### episode.json (source of truth — edit these)

```
id, order, slug, title, company, company_name, language, audience,
target_seconds, objective, topics[], sources[], voice{emotion,...}
beats[] {
  id, kind: talking_head|demo|broll, seconds,
  narration,            # the spoken VO (the avatar says this)
  on_screen, caption, note,
  demo?  { url, intent, language }     # when kind == demo
  broll? "visual description"          # when kind == broll
}
```

### Rendered outputs

- `<slug>.script.md` — human shooting script table.
- `<slug>.narration.txt` — VO paragraphs (blank-line separated).
- `<slug>.reel.txt` — `avatar-video-reel` plain text; `demo` beats become
  `[DEMO: url | intent]\n<VO>\n[/DEMO]`; others are plain talking-head lines.
- `<slug>.storyboard.json` — `avatar-reel-composer` scaffold. `talking_head`
  beats -> `talking_head` scenes; `demo`/`broll` beats -> `broll` scenes. Every
  `scene.text` is the beat's verbatim narration and `script` is those joined by
  single spaces (reel-composer's hard tiling rule). `avatar_dir` is a placeholder.

## Handoff

```bash
# avatar-video-reel — the [DEMO]-marked script (records the demos interactively)
python3 .cursor/skills/avatar-video-reel/scripts/generate_reel.py \
  --script-file onboarding/<company>/scripts/04_create-project.reel.txt \
  --language <lang> --format reel --preview

# avatar-reel-composer — set avatar_dir in the storyboard first, then:
python3 .cursor/skills/avatar-reel-composer/scripts/compose_reel.py \
  onboarding/<company>/scripts/01_welcome.storyboard.json --dry-run
```
