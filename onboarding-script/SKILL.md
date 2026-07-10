---
name: onboarding-script
description: Generate an ordered SERIES of onboarding video scripts (a curriculum) to introduce a new team member to a company — who we are, the tools/accounts we use, our engineering best practices, how to create a new project with the company's skills/templates, and how we deploy. Auto-discovers the company's identity, stack, project-creation and deploy flow from whatever is connected (gh CLI org/account + repos + CI workflows; az/gcloud/vercel cloud CLIs; a Notion MCP; a Linear MCP; past chat transcripts) and degrades gracefully when a source is missing. Company-agnostic. Produces text/JSON only (no video, no API key): per topic it writes a shooting script (.script.md), a clean narration track (.narration.txt), an avatar-video-reel script with [DEMO] screen-recording markers (.reel.txt) and an avatar-reel-composer storyboard scaffold (.storyboard.json). Use when the user wants onboarding videos/reels for a new hire, an employee-onboarding series, scripts for "how we work / create a project / deploy", or mentions onboarding, new team member, new hire, or company induction videos.
---

# Onboarding Script

Write the **words + screens** for an ordered **series of onboarding reels** that
introduce a new team member to a company. This skill only produces the
**scripts** (text/JSON); the videos are generated later by the avatar pipeline
([`avatar-video-reel`](../avatar-video-reel/SKILL.md) /
[`avatar-reel-composer`](../avatar-reel-composer/SKILL.md)), which the outputs
drop straight into.

It is **company-agnostic**: it learns the company from whatever tooling is
connected — the logged-in GitHub org/account (`gh`), the cloud CLIs
(`az`/`gcloud`/`vercel`), a Notion MCP, a Linear MCP, and past chat transcripts —
and **degrades gracefully** when a source is missing (records the gap and asks
you to confirm an assumption instead of inventing facts).

## What it produces

An ordered curriculum (`curriculum.json`) and, per episode, a **format-agnostic
package** so either downstream skill can consume it:

- `NN_<slug>.script.md` — human shooting script (beats: VO + on-screen + `[DEMO]` intent + B-roll + captions + timing).
- `NN_<slug>.narration.txt` — clean spoken VO only (feed to `voice-clone` / `avatar-reel-composer`'s `narrate.py`).
- `NN_<slug>.reel.txt` — plain-text script with `[DEMO: url | intent]...[/DEMO]` markers (drop-in for [`avatar-video-reel`](../avatar-video-reel/SKILL.md)).
- `NN_<slug>.storyboard.json` — a storyboard scaffold (talking_head + broll scenes whose `text` tiles the narration verbatim) for [`avatar-reel-composer`](../avatar-reel-composer/SKILL.md); fill `avatar_dir` when you pick an avatar.
- `README.md` — the series index, in order.

All outputs land under `onboarding/<company>/` (git-ignored).

## Workflow

Copy this checklist and track progress:

```
- [ ] 1. Discover context   (detect_context.py + augment with MCP/CI/transcripts)
- [ ] 2. Confirm the company (fill facts{}, resolve gaps, get sign-off on assumptions)
- [ ] 3. Plan the curriculum (scaffold_curriculum.py — user guideline OR default minimum)
- [ ] 4. Scaffold episodes   (scaffold_episode.py — one beat sheet per episode)
- [ ] 5. Write the copy       (fill each episode.json, grounded in company_context.json)
- [ ] 6. Validate             (check_episode.py — fix every FAIL, weigh WARNs)
- [ ] 7. Render               (render_episode.py — the 4 files/episode + README)
- [ ] 8. Hand off             (feed .reel.txt / .storyboard.json to the avatar skills)
```

### 1. Discover context

Probe every connected source and write `company_context.json`:

```bash
python3 .cursor/skills/onboarding-script/scripts/detect_context.py \
  --out onboarding/<company>/context/company_context.json
# optional: --org <github-org>  --keywords "acme,widget,platform"  --no-workflows
```

The script covers the **CLI-visible** sources (read-only, short timeouts, never
fails a run if a tool is absent):
- **GitHub** (`gh`): login, orgs, repos (name/description/language/topics/default branch/template flag), flags a `skills`/`templates`/`starter`/`.github` repo, and scans a few repos' `.github/workflows/*.yml` for deploy hints.
- **Clouds** (first-class, each optional): `az account show`; `gcloud config list` + `gcloud projects list`; `vercel whoami` + `vercel projects ls`. Plus name-detection of `aws`/`flyctl`/`wrangler`/`kubectl`/`docker`/…
- **Transcripts**: finds this project's `agent-transcripts/` and greps for company/stack keywords.

Then **you (the agent) augment** the JSON with the MCP-only and doc-only sources
(the script can't call MCPs) — see [REFERENCE.md](REFERENCE.md) "Discovery
playbook" for the exact queries:
- If a **Notion MCP** is connected: search for handbook / onboarding / engineering-guidelines / deploy pages; pull the relevant ones.
- If a **Linear MCP** is connected: read the team, workflow states, labels and projects (the real "how we work" process).
- Read the flagged repos' `README`/`CONTRIBUTING` and CI workflows via `gh api` to ground the **create-project** and **deploy** steps.
- Mine the transcript matches for company-specific facts.

Fill the `facts{}` block and set each `sources[].status`. **Never fabricate
internal process**: if a fact is unknown, leave it and mark it `[TO CONFIRM]`.

### 2. Confirm the company

**If `company_selection.needs_user_choice` is `true`** (the probe found more than
one probable company across the connected sources — e.g. a `gh` login/org plus a
different `gcloud`/`vercel`/`az` account), STOP and ask the user which one is
correct before doing anything else. Use `AskQuestion` and list
`company_candidates[]` (show each name + the sources that suggested it). Then
lock it in by re-running:

```bash
python3 .cursor/skills/onboarding-script/scripts/detect_context.py \
  --company <chosen>   # or --org <chosen> if it's the GitHub org \
  --out onboarding/<company>/context/company_context.json
```

Then show the user the resolved company, stack, and the `gaps[]` list, and get
sign-off on any assumption before scripting.

### 3. Plan the curriculum

Ask the user for a **guideline** (which topics, order, target role, language,
length). If they don't give one, propose the **minimum default curriculum**:

1. **Welcome & company intro** — mission, values, team, what we build.
2. **Tools & accounts we use** — the detected stack (gh org, cloud, Notion, Linear, comms) + how to get access.
3. **Engineering best practices** — branching, PRs, reviews, coding standards.
4. **Create a new project with the company skills** — the concrete bootstrap (template repo / `npx skills add <org>/…` / scaffold).
5. **How we deploy** — the real CI/CD + cloud flow (from the CI workflows and the detected cloud: Azure/GCP/Vercel).
6. **Where to get help & what's next** — people, docs, rituals.

```bash
# default minimum curriculum (grounded in the context)
python3 .cursor/skills/onboarding-script/scripts/scaffold_curriculum.py \
  --context onboarding/<company>/context/company_context.json \
  --language en --audience "new engineer" --seconds 45 \
  --out onboarding/<company>/curriculum.json

# custom set: write an episodes JSON (id/title/objective/topics/demo_targets) and pass it
python3 .cursor/skills/onboarding-script/scripts/scaffold_curriculum.py \
  --context .../company_context.json --episodes-file my_topics.json \
  --out onboarding/<company>/curriculum.json
```

### 4. Scaffold episodes

Turn the curriculum into one beat-sheet `episode.json` per episode:

```bash
python3 .cursor/skills/onboarding-script/scripts/scaffold_episode.py \
  --curriculum onboarding/<company>/curriculum.json \
  --out-dir onboarding/<company>/episodes/
# or a single one: --episode create-project
```

### 5. Write the copy

Edit each `episodes/<slug>.episode.json`. Every beat has a `kind`
(`talking_head` | `demo` | `broll`), `narration` (the spoken VO), `on_screen`,
`caption`, and — for `demo` beats — a `demo.url` + `demo.intent` (natural-language
description of the screen recording). Ground **every claim** in
`company_context.json`; cite the source in the episode's `sources[]`; mark
anything unverified `[TO CONFIRM]`. Keep sentences **short and spoken** (this is
read aloud / lip-synced and captioned).

### 6. Validate (feedback loop)

```bash
python3 .cursor/skills/onboarding-script/scripts/check_episode.py \
  onboarding/<company>/episodes/*.episode.json
```

Fix every **FAIL**; weigh each **WARN**. Re-run until it passes.

### 7. Render

```bash
python3 .cursor/skills/onboarding-script/scripts/render_episode.py \
  onboarding/<company>/episodes/*.episode.json \
  --out onboarding/<company>/scripts/
```

Writes the four files per episode + the series `README.md` index.

### 8. Hand off

The rendered files are drop-in for the avatar pipeline the user installs later:

```bash
# avatar-video-reel: the [DEMO]-marked plain-text script
python3 .cursor/skills/avatar-video-reel/scripts/generate_reel.py \
  --script-file onboarding/<company>/scripts/04_create-project.reel.txt --language en --format reel ...

# avatar-reel-composer: the storyboard scaffold (set avatar_dir first)
python3 .cursor/skills/avatar-reel-composer/scripts/compose_reel.py \
  onboarding/<company>/scripts/01_welcome.storyboard.json --finish
```

## Output layout

```
onboarding/<company>/
  context/company_context.json   # what we discovered (+ your MCP/doc augmentation)
  curriculum.json                # ordered episodes
  episodes/<slug>.episode.json   # per-episode beat sheet (source of truth; edit these)
  scripts/                       # rendered: .script.md .narration.txt .reel.txt .storyboard.json
  README.md                      # the series index, in order
```

## Anti-patterns

1. **Inventing internal process** (deploy steps, tools) not backed by a source — mark `[TO CONFIRM]` and ask instead.
2. **Hard-coding one company** — always resolve identity/stack from the connected tools; nothing is specific to any org.
3. **One long block of VO** — short sentences per beat so captions show one phrase at a time.
4. **A `demo` beat without a `url` + `intent`** — the recorder needs both (it drives the browser from the intent).
5. **Skipping the confirmation step** — never ship assumptions as facts.

## Additional resources

- The full discovery playbook (exact gh + az/gcloud/vercel probes, Notion/Linear
  prompts, transcript mining, degrade-gracefully rules), the JSON schemas, and the
  tool-to-topic map: [REFERENCE.md](REFERENCE.md)
- Worked examples: [examples/curriculum.example.json](examples/curriculum.example.json),
  [examples/episode.example.json](examples/episode.example.json),
  [examples/01_welcome.script.example.md](examples/01_welcome.script.example.md)
