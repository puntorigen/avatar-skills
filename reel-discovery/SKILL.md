---
name: reel-discovery
description: Find highly-ranking PUBLIC short videos/reels by TOPIC (keyword/hashtag) or by BUSINESS (brand name/handle) across YouTube, TikTok, Instagram and Facebook, then rank them by views/engagement/velocity into one unified manifest. Free-first (YouTube Data API + tikwm + Instagram web endpoints) with an optional paid Apify upgrade for robust TikTok keyword search, Instagram topic search and all Facebook discovery (Facebook has no free anonymous path). Optionally downloads the top N MP4s ready for the video-scene-analysis -> reel-restyle pipeline. Use when the user wants to discover trending/top/viral reels, research a competitor's or topic's best-performing short videos, find reference reels to analyze or restyle, or "what reels are working for <topic/brand> on TikTok/YouTube/Instagram/Facebook".
---

# Reel Discovery (rank top public reels by topic or business)

Search YouTube, TikTok, Instagram and Facebook for the best-performing public
short videos about a **topic** or a **business**, normalize every hit into one schema,
rank by views / engagement / velocity / recency, and write a unified manifest.
Optionally download the top N so they flow straight into
[`video-scene-analysis`](../video-scene-analysis/SKILL.md) and then
[`reel-restyle`](../reel-restyle/SKILL.md).

This is the discovery front-door of the avatar pipeline:
**discover topic/competitor winners -> analyze their structure -> restyle for your avatar.**

## When to use

- "Find the top reels about <topic> on TikTok / YouTube / Instagram."
- "What short videos are performing best for <business / competitor>?"
- "Get me reference reels to analyze and restyle for my avatar."

## Decision tree

```
What is the query?
├── A TOPIC (keyword / hashtag)            -> --topic "ai productivity"
│     YouTube : real keyword search (Data API or yt-dlp)
│     TikTok  : real keyword search (tikwm feed/search; hashtag fallback)
│     IG      : hashtag (best-effort free; reliable only with APIFY_TOKEN)
│     Facebook: APIFY_TOKEN only (no free anonymous search)
└── A BUSINESS (brand name or @handle)     -> --business nike   (or --business @nike)
      Resolves the brand's account per platform AND keyword-searches the brand
      (captures third-party reels mentioning it). Facebook still needs APIFY_TOKEN.

Do you have credentials?
├── YT_API_KEY set      -> YouTube uses the official Data API (exact counts, fast)
├── APIFY_TOKEN set     -> TikTok keyword + IG topic + ALL Facebook become robust (PAID)
└── neither             -> YouTube/TikTok/IG run free best-effort; Facebook returns nothing
```

**Facebook is opt-in.** It is a valid platform but NOT in the default
`--platforms` list (its free path is empty), so add it explicitly:
`--platforms youtube,tiktok,instagram,facebook`. Without `APIFY_TOKEN` it returns
0 hits plus a note. To download a *known* Facebook video URL (no discovery), use
the [`facebook-videos`](../facebook-videos/SKILL.md) skill.

## Setup / cost (how reliable, what it costs)

- **YouTube** - most reliable, free. Get a Google Cloud API key, enable
  "YouTube Data API v3", then `export YT_API_KEY=...`. Quota is 10,000 units/day
  (search.list = 100 units, videos.list = 1 unit -> ~90 searches/day). Without a
  key it falls back to `yt-dlp "ytsearchN:..."` (slower, still has view counts).
  Each search also captures **publishing metadata** (description, tags, hashtags,
  category, language, captions, channel size) at negligible quota cost: +1 unit
  for `videoCategories.list` (cached per region) and +1 unit per 50 channels for
  `channels.list`; the richer `videos.list` parts are free.
- **TikTok** - free via `tikwm.com` (no key, ~1 req/sec). `feed/search` gives
  real keyword search with `play_count`; `user/posts` covers a business handle.
  For maximum reliability + true keyword search at scale, set `APIFY_TOKEN`
  (paid actor).
- **Instagram** - hard. Free best-effort uses Instagram's anonymous web
  endpoints (`web_profile_info` for a handle, `tags/web_info` for a hashtag);
  these are frequently rate-limited/gated. Set `APIFY_TOKEN` for reliable IG
  topic + profile discovery, or use the browser-based
  [`instagram-scraper`](../instagram-scraper/SKILL.md) skill for a deep profile pull.
- **Facebook** - hardest: **no free anonymous path at all.** yt-dlp can only
  extract/download an *individual* FB video URL (it returns "Unsupported URL" for
  a Page or its /videos tab), and Facebook search needs login. Discovery is
  therefore `APIFY_TOKEN`-only; without it, Facebook returns 0 hits with a note.
  To grab a *known* FB video URL, use the
  [`facebook-videos`](../facebook-videos/SKILL.md) skill.
- `yt-dlp` + `ffmpeg` are already installed (used for listing + downloads).

Optional env to pick different Apify actors: `APIFY_TIKTOK_ACTOR`,
`APIFY_IG_ACTOR`, `APIFY_FACEBOOK_ACTOR` (see [REFERENCE.md](REFERENCE.md)).

### Where to put the keys

Credentials resolve with this precedence: **environment variable first, then a
git-ignored `config.json`** next to the skill. Either works:

```bash
# Option A -- environment variables (per shell / ~/.zshrc)
export YT_API_KEY="AIza..."
export APIFY_TOKEN="apify_api_..."   # optional

# Option B -- persistent git-ignored config.json (no re-export needed)
python3 .cursor/skills/reel-discovery/scripts/setup_key.py --yt-api-key AIza... [--apify-token apify_...]
python3 .cursor/skills/reel-discovery/scripts/setup_key.py --show
```

`config.json` lives at `.cursor/skills/reel-discovery/config.json` and is covered
by `.cursor/skills/.gitignore` -- never commit it.

## Workflow checklist

```
- [ ] Step 1: Decide topic vs business; pick platforms + sort
- [ ] Step 2: (recommended) set YT_API_KEY; (optional) APIFY_TOKEN -- env var or setup_key.py
- [ ] Step 3: Run discover.py -> discovery/<slug>/results.json + results.md
- [ ] Step 4: Review the ranked table; adjust filters (--sort, --since, --min-views)
- [ ] Step 5: (optional) --download-top N -> discovery/<slug>/videos/*.mp4
- [ ] Step 6: Hand the MP4s to video-scene-analysis -> reel-restyle
```

## Quick start

```bash
# Topic discovery, ranked by recent virality (views/day), last 90 days:
python3 .cursor/skills/reel-discovery/scripts/discover.py \
    --topic "ai productivity" \
    --platforms youtube,tiktok,instagram \
    --sort velocity --since 90 --max-duration 180 \
    --limit 30 --per-platform 12

# Competitor/business research on two platforms, then grab the top 5 videos:
python3 .cursor/skills/reel-discovery/scripts/discover.py \
    --business nike \
    --platforms youtube,tiktok \
    --sort views --download-top 5

# A single platform searcher can be run standalone for debugging:
python3 .cursor/skills/reel-discovery/scripts/search_tiktok.py --topic "vibe coding" --limit 10

# Include Facebook (needs APIFY_TOKEN; opt-in via --platforms):
APIFY_TOKEN=apify_... python3 .cursor/skills/reel-discovery/scripts/discover.py \
    --business "24 Horas" \
    --platforms youtube,tiktok,instagram,facebook \
    --sort views --download-top 5
```

Outputs (under `discovery/<slug>/`):
- `results.json` - `{meta, count, results:[{rank, ...Reel}]}` (machine-readable).
  YouTube, TikTok and Instagram records also carry publishing metadata
  (`hashtags`, plus a `metadata` dict; YouTube adds `description`/`tags`/
  `category`/`language` + captions/definition/channel subscribers, TikTok adds
  the sound/region/saves, Instagram adds the post type).
- `results.md` - ranked table (views/likes/engagement/age/author/title/URL) plus
  a **"Cómo están publicados"** section, grouped per platform, summarizing the
  publishing patterns (top hashtags, top TikTok sounds, category/language
  breakdown, captions ratio, channel-size range) with per-platform detail tables.
- `videos/` + `videos/download_manifest.json` - only when `--download-top` is used.

## Key flags

- Query (one required): `--topic TEXT` | `--business TEXT` (a `@handle` works too).
- `--platforms youtube,tiktok,instagram` (default these three; add `facebook` to
  opt into Apify-only Facebook discovery).
- `--sort views|engagement|velocity|recent` (default `views`). `velocity` =
  views/day, surfacing recent breakouts rather than only old mega-hits.
- Filters: `--min-views N`, `--since DAYS`, `--max-duration SECONDS`.
- Localization (YouTube): `--region US|CL|...`, `--lang en|es|...`.
- Sizing: `--limit` (total kept), `--per-platform` (cap per platform pre-merge).
- `--download-top N`, `--out-dir`, `--slug`, `--timezone`.
- Credential overrides: `--yt-api-key`, `--apify-token` (else read from env).

## How ranking works

Each hit becomes a `Reel` with `views/likes/comments/shares`,
`published_at`, `duration_s`. Derived per record: `engagement_rate =
(likes+comments+shares)/views` and `velocity = views/day`. When a platform hides
views (common on Instagram), reach is estimated from likes and flagged
(`views_estimated`, shown as `*` in the table). See
[REFERENCE.md](REFERENCE.md) for the exact schema, scoring formulas and Apify
field mappings.

## How videos are published (publishing metadata)

Ranking tells you *how big* a video is; publishing metadata tells you *how it was
packaged*. For every YouTube, TikTok and Instagram hit the skill records
`hashtags` (parsed from the title/caption) plus a per-platform `metadata` dict:

- **YouTube** - `description`, `tags`, `category`, `language`, captions on/off,
  hd/sd, made-for-kids, license, topic categories, channel subscribers/size.
- **TikTok** - the **sound** used (`music_title`/`music_author`), `region`,
  saves/downloads, ad flag.
- **Instagram** - `product_type` (`clips`/carousel/image) and caption length.

`results.md` rolls these up into a **"Cómo están publicados"** section, grouped
per platform so signals don't get mixed — top hashtags, most-used TikTok sounds,
category/language mix, captions ratio, channel-size range — so you can see each
platform's publishing playbook at a glance before restyling for your avatar.
Full key list in [REFERENCE.md](REFERENCE.md).

## Handoff to the rest of the pipeline

`discovery/<slug>/videos/*.mp4` is exactly what `video-scene-analysis` consumes:

```bash
# After --download-top, analyze a downloaded winner, then restyle for your avatar:
python3 .cursor/skills/video-scene-analysis/scripts/analyze_video.py \
    discovery/ai-productivity/videos/01_tiktok_7648341282682719496.mp4
# ... then feed the analysis into reel-restyle (extract_template.py / apply_template.py).
```

## Anti-patterns

1. **Do not** scrape tikwm or the Instagram web endpoints faster than ~1 req/sec
   - they rate-limit/block. The scripts already throttle; don't loop them tightly.
2. **Do not** expect free arbitrary keyword search on Instagram - it is
   hashtag-only and frequently gated. Use `--business <handle>` or `APIFY_TOKEN`.
3. **Do not** treat a missing YouTube key as fatal - it degrades to yt-dlp; just
   set `YT_API_KEY` for speed and exact counts.
4. **Do not** download private / age-gated / region-locked content.
5. **Do not** commit `discovery/` - it is gitignored (raw research + media).
6. **Do not** rank only by `views` for trend-spotting - use `--sort velocity`
   with `--since` to catch reels that are blowing up *now*.
7. **Do not** expect any free Facebook discovery - it is `APIFY_TOKEN`-only. For a
   *known* FB URL use the `facebook-videos` skill instead of `discover.py`.

## Utility scripts

| Script | Purpose |
|---|---|
| `scripts/discover.py` | Orchestrator: dispatch per platform, rank, write manifest, optional download (main entry point) |
| `scripts/search_youtube.py` | YouTube Data API v3 + yt-dlp ytsearch fallback |
| `scripts/search_tiktok.py` | tikwm feed/search + challenge + user posts; yt-dlp handle fallback |
| `scripts/search_instagram.py` | IG anonymous web endpoints (best-effort) + Apify |
| `scripts/search_facebook.py` | Facebook discovery (Apify-only; graceful empty + note otherwise) |
| `scripts/providers/apify.py` | Optional PAID actors (TikTok kw, IG topic/profile, FB topic/page) |
| `scripts/setup_key.py` | Store YT_API_KEY / APIFY_TOKEN in git-ignored config.json |
| `scripts/sync_global.sh` | Sync this copy <-> the global ~/.cursor/skills copy |
| `scripts/_common.py` | `Reel` schema, scoring/ranking, HTTP, writers, credential resolution |

## Project-local vs global copy

This skill can live both in a project (`<project>/.cursor/skills/reel-discovery/`)
and globally (`~/.cursor/skills/reel-discovery/`). Treat the **project-local copy
as the source of truth** and push changes to the global one:

```bash
bash .cursor/skills/reel-discovery/scripts/sync_global.sh            # push -> global
bash .cursor/skills/reel-discovery/scripts/sync_global.sh --pull     # global -> here
bash .cursor/skills/reel-discovery/scripts/sync_global.sh --dry-run  # preview only
```

`config.json` (your keys), `__pycache__/` and `discovery/` (research output) are
never synced, so each location keeps its own credentials and results.

## Additional resources

- Full record schema, scoring formulas, per-provider quirks and Apify actor
  field mappings: [REFERENCE.md](REFERENCE.md).
- Profile-only / single-URL download skills (deeper): `instagram-videos`,
  `instagram-scraper`, `tiktok-videos`, `youtube-videos`, `facebook-videos`.
