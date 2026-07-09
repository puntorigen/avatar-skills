---
name: brand-content-strategy
description: Turn a website or personal brand into a research-backed content + channel strategy. Profiles the site's positioning/credentials, discovers what reels rank in its niche (reel-discovery), filters out official/brand accounts to rank only real individual creators, reverse-engineers their cross-platform distribution playbook (perplexity_ask), and writes a positioning + 30-day content plan (with an optional AI-voice podcast layer wired to voice-clone + audio-theater). Use when the user wants to promote/grow a website, get known, position themselves as an expert/authority, decide what videos to make, launch a YouTube/TikTok/Instagram channel, find a target audience, or build a content/creator strategy for a domain or brand.
---

# Brand Content Strategy

Turn a **website / personal brand** into a research-backed **content + channel
strategy**: what to post, where, for whom, and a 30-day plan to get known and
generate leads. It is an orchestration skill — it drives
[`reel-discovery`](../reel-discovery/SKILL.md), the `perplexity_ask` MCP, and the
avatar/audio pipeline ([`viral-video-script`](../viral-video-script/SKILL.md),
[`voice-clone`](../voice-clone/SKILL.md),
[`avatar-reel-composer`](../avatar-reel-composer/SKILL.md), and the
`audio-theater` skill) — and produces one markdown deliverable.

## When to use

- "How do I get my site / brand known?" / "position me as an expert."
- "What kind of videos should I make? Who should I target?"
- "Build me a YouTube / TikTok / content strategy for `<domain>`."
- "Research what's working in my niche and turn it into a plan."

## Inputs to gather (ask only what's missing)

| Input | Why |
|---|---|
| Website / domain (or brand name) | Profile positioning + credentials |
| Business goal | leads/consultancy vs audience vs sales — drives the funnel |
| Target geos + languages | e.g. US/Canada (EN) + Chile/LatAm (ES) → language arbitrage |
| Niche topics | seeds the discovery queries |
| Competitor handles (optional) | extra `--business` discovery |

## Setup

- **YouTube** (recommended): set `YT_API_KEY` for exact counts — see reel-discovery.
- **TikTok/IG/Facebook** (optional, robust): set `APIFY_TOKEN`.
- **perplexity_ask** MCP for the creator footprint research (step 5).

## Workflow

```
- [ ] 1. Profile the brand   (fetch the site → positioning, credentials, assets)
- [ ] 2. Design niches+geos  (3-6 queries: core niche, broad authority, news, per language)
- [ ] 3. Discover            (reel-discovery per query, --sort velocity)
- [ ] 4. Filter to humans    (scripts/filter_creators.py → drop brands, rank people)
- [ ] 5. Reverse-engineer    (perplexity_ask each top creator: footprint + funnel)
- [ ] 6. Synthesize          (positioning, platforms, pillars, 30-day plan, funnel, audio)
- [ ] 7. Write deliverable   (<brand>-30dias.md from the template in REFERENCE.md)
```

### 1. Profile the brand

Fetch the site (WebFetch). Extract the brand's **positioning, credentials,
proof points, products/services, and unfair advantages** — these become the
*credential shortcut* (see Principles). Also audit the site as the **funnel
destination**: funnel coverage (top/mid/bottom), the existing CTA,
locales/languages, and whether analytics exist — this seeds the website punch
list (step 6).

### 2. Design niches + geos

Derive 3–6 discovery queries from the brand's niche. Cover, at minimum:
- the **core niche** (the brand's real differentiator),
- one **broad authority** term,
- one **news / trend** angle,
- the **same core niche per target language** (EN for US/CA, ES for LatAm…).

### 3. Discover

Run reel-discovery per query, sorted by **velocity** (what's breaking out *now*):

```bash
python3 .cursor/skills/reel-discovery/scripts/discover.py \
  --topic "<query>" --platforms youtube,tiktok \
  --sort velocity --since 120 --max-duration 240 \
  --limit 25 --per-platform 12 --region US --lang en \
  --slug <slug>
```

Repeat per language with `--region/--lang` (e.g. `--region CL --lang es`). Read
each `discovery/<slug>/results.md` for the **"Cómo están publicados"** section
(hashtags, sounds, channel sizes, captions) — that is the packaging playbook.

### 4. Filter to humans (exclude official/brand accounts)

Official product accounts (Claude, Kimi, Unity, monday…) are not competition.
Collapse all discoveries into a ranked **humans-only** shortlist:

```bash
python3 .cursor/skills/brand-content-strategy/scripts/filter_creators.py \
  --slugs <slug1>,<slug2> \
  --keywords "agent,claude,coding,ia,automat,llm,cursor,codex" \
  --min-views 8000 --sort velocity --top 30 \
  --out discovery/_creators.md
```

It drops a default brand stoplist (extend with `--exclude`), ranks individuals by
views/day, and extracts links found in their descriptions (first read on their
footprint). Rank by **velocity, not raw views** — raw views favor mega media
channels and old hits.

### 5. Reverse-engineer the playbook

For the top ~6 individual creators (and the ES cluster), research their full
distribution with `perplexity_ask`. Use the prompt template in
[REFERENCE.md](REFERENCE.md) → "Creator footprint prompt". Capture per creator:
platforms + followers, what they monetize, signature hook/format, and how they
repurpose across platforms. Flag unverifiable claims.

### 6. Synthesize the strategy

Combine the brand profile + publishing patterns + creator playbooks into:
positioning, audience + platform priority, content pillars, hook/bio formulas, a
**30-day calendar**, the funnel + monetization ladder, a **website punch list
(P0/P1/P2 — always include it; see REFERENCE.md §9)**, metrics, the production
pipeline, and (optional) the audio/podcast layer. Apply the Principles below.

### 7. Write the deliverable

Write `<brand>-30dias.md` using the full template in
[REFERENCE.md](REFERENCE.md) → "30-day strategy template".

## Principles (the reverse-engineered playbook)

Apply all — they are how the winners actually grow:

1. **Credential in the first second / bio** (authority shortcut). Lead with the
   brand's strongest proof, not the product.
2. **Hook = result + number + tool**, never the product first
   (e.g. "How I built [outcome in $/time] with [tool/agents]").
3. **Funnel architecture:** short-form (TikTok/Reels/Shorts = discovery) →
   long-form (YouTube = proof + SEO) → link-in-bio → site.
4. **One asset → many surfaces.** Produce once, distribute to all (and clip
   long-form into shorts). This repo's pipeline *is* that engine.
5. **Monetization ladder:** free lead magnet/workshop → course/cohort →
   community → high-ticket consulting (the real back-end).
6. **Borrowed authority:** guest on existing podcasts / press.
7. **Language arbitrage:** an underserved language/region (e.g. Chile/LatAm in
   Spanish) is far easier to own than the saturated EN market.

## Anti-patterns

1. **Ranking brands as competitors** — always run `filter_creators.py` first.
2. **Ranking by raw views** for trend-spotting — use `velocity`.
3. **Pure AI-voice impersonation** in a credibility brand — clone the person's
   *own* voice (voice-clone) and **declare** it; never fake a real guest's voice.
4. **Fully automated publishing** with no human-in-the-loop — quality > volume.
5. **Inventing formats** — steal proven ones (see viral-video-script).
6. **Treating the podcast as a discovery channel** — it deepens/converts; clips
   and short-form do the discovery.

## Outputs

- `discovery/<slug>/` — raw reel-discovery research (gitignored).
- `discovery/_creators.md` + `.json` — humans-only ranked shortlist.
- `<brand>-30dias.md` — the strategy deliverable.

## Utility scripts

| Script | Purpose |
|---|---|
| `scripts/filter_creators.py` | Aggregate reel-discovery output, drop brand/official accounts, rank individual creators by velocity, extract their links |

## Additional resources

- Brand-profiling checklist, query-design heuristics, the perplexity footprint
  prompt, the full distribution playbook, the 30-day template, and the audio /
  podcast layer: [REFERENCE.md](REFERENCE.md)
