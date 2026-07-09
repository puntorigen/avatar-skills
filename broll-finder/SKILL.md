---
name: broll-finder
description: Find real public YouTube footage about a topic or person (e.g. Anthony Bourdain) and turn the relevant moments into clean 9:16, silent B-roll clips for an avatar reel. The found-footage counterpart of broll-generator — instead of synthesizing B-roll with AI, it searches YouTube, fetches timecoded transcripts so the agent can pick the relevant windows WITHOUT downloading whole videos, downloads only those segments, and normalizes them into a broll/-compatible manifest (with source + license metadata) that avatar-reel-composer can drop in via a broll scene. Use when the user wants real/archival B-roll, complementary footage about a subject or person, "find clips of X on YouTube to use in the reel", or footage inserts to lay under an avatar voice-over.
---

# B-roll Finder (real footage from YouTube)

The **found-footage counterpart of `broll-generator`**. Where `broll-generator`
*synthesizes* B-roll with an AI model, `broll-finder` *finds* real public
YouTube footage about a **topic** or **person** (e.g. *Anthony Bourdain*),
downloads only the relevant windows, and normalizes them into the same clean
**9:16, silent, manifest-backed** clips that `avatar-reel-composer` lays under an
avatar voice-over.

Key difference from `broll-generator`: that one **forbids** the presenter on
screen. Here the footage often **should** show the subject (Bourdain himself in
a market) — found B-roll can contain real people and the subject.

It is an **orchestrator** built on existing skills' patterns:
`reel-discovery` (search), `youtube-audio-toolkit` / `video-transcribe`
(transcripts), `youtube-videos` (yt-dlp download) and `broll-generator`
(manifest + ffmpeg normalization).

## ⚠️ Rights / licensing (read first)

Third-party YouTube footage is **copyrighted**. This skill records the license
of every clip and labels it:

- **Creative Commons** (`--creative-commons`) → reuse generally allowed **with
  attribution** to the original channel. Safer for a published reel; still
  verify per video and credit the source.
- **Standard YouTube license** (default) → **NOT cleared for republishing**.
  Treat those clips as **reference / research only**. Using them in a published
  reel may infringe copyright unless it qualifies as fair use or you get
  permission. The manifest flags each clip `reusable: false` with a `rights_note`.

When in doubt, run with `--creative-commons`.

## Setup

```bash
pip3 install -r ~/.cursor/skills/broll-finder/scripts/requirements.txt
```

`yt-dlp` + `ffmpeg`/`ffprobe` must be on PATH (already installed in this repo).
A **YouTube Data API key is optional**: set `YT_API_KEY` (or reuse
`reel-discovery`'s `config.json`) for exact view counts and a real
Creative-Commons search filter; without it, search degrades to `yt-dlp
ytsearch`. No Replicate token is needed — search + download are free.

## Pipeline (idempotent, with one agent checkpoint)

```
query (topic/person)  [+ optional --creative-commons]
  │
1 search.py       ─► <work>/candidates.json + candidates.md          (ranked)
  │
2 transcripts.py  ─► <work>/transcripts/<id>.{json,md}               (timecoded, NO download)
  │                  <work>/selection.template.json                  (skeleton)
  │
  ▼  ── CHECKPOINT: agent reads candidates.md + transcripts/*.md, then writes
  │     selection.json with the [start,end] windows worth cutting ──
  │
3 cut_segment.py  ─► <avatar>/broll/found/<NNN>_<slug>.mp4 + manifest.json
                     (downloads ONLY each window, crops to 9:16, strips audio,
                      records source + license + rights_note)
```

**The relevance "engine" is the agent** reading timecoded transcripts and
(optionally) review frames — exactly the agent-in-the-loop pattern of
`video-scene-analysis` and `create_avatar.py`. Two complementary signals:
*what is said* (transcript → candidate window, cheap, no download) and *what is
shown* (review the `--frames` jpg or run `video-scene-analysis` to confirm the
shot is usable footage, not a chyron'd interview).

## Quick start (orchestrated)

```bash
# from the repo root so <avatar>/... paths resolve
python3 .cursor/skills/broll-finder/scripts/find_broll.py \
    --query "anthony bourdain street food vietnam" \
    --avatar-dir lolo --max-candidates 8 --lang en --creative-commons --frames
```

This searches + fetches transcripts, then **stops at the checkpoint** and prints
where to look. Then:

1. Skim `found-broll/<slug>/candidates.md` and `found-broll/<slug>/transcripts/*.md`.
2. Copy `selection.template.json` → `selection.json` and edit it: keep the
   windows you want, set real `start`/`end` (seconds, from the `mm:ss` markers)
   and a `description` per clip; add/remove entries from any candidate.
3. **Re-run the exact same command** — finished stages are skipped and stage 3
   cuts the clips into `<avatar>/broll/found/`.

`--status` prints stage progress without doing work. `--force-search` /
`--force-transcripts` re-run a stage.

### selection.json

```json
{
  "segments": [
    { "url": "https://youtu.be/VIDEOID", "start": 132, "end": 138,
      "description": "Bourdain comiendo pho en un puesto callejero de Hanoi", "fit": "crop" },
    { "url": "https://youtu.be/OTHERID", "start": 41.5, "end": 47,
      "description": "mercado nocturno, vapor de los puestos, multitud", "fit": "blur" }
  ]
}
```

## Single clip (workhorse, like generate_broll.py)

```bash
# from YouTube — downloads ONLY 02:12–02:18, saves into the avatar's broll/found/
python3 .cursor/skills/broll-finder/scripts/cut_segment.py \
    --url "https://youtu.be/VIDEOID" --start 132 --end 138 \
    --description "Bourdain comiendo pho en un puesto callejero de Hanoi" \
    --avatar-dir lolo --fit crop --frame

# from an already-downloaded local file
python3 .cursor/skills/broll-finder/scripts/cut_segment.py \
    --input footage.mp4 --start 5 --end 11 --description "olas al atardecer" --fit blur
```

Output: `<avatar>/broll/found/<NNN>_<slug>.mp4` + a `manifest.json` entry; a JSON
summary (path, dims, license, source_url, segment) is printed to stdout.

## 16:9 → 9:16 (`--fit`)

YouTube is mostly 16:9; reels are 9:16. **The rule / default is a center
crop-to-fill** — the source is scaled UP until it covers the whole 9:16 frame
(preserving aspect), then center-cropped. The result fills the ENTIRE frame;
there is **never** any letterbox/pillarbox padding of a scaled-down copy.

- `crop` **(default, recommended)** — center crop-to-fill that covers the whole
  9:16 frame. No black bars, ever. Best for talking subjects and most footage.
- `pad` — *opt-in only.* Letterbox with black bars (keeps the whole 16:9 frame).
- `blur` — *opt-in only.* Fits the frame over a blurred, enlarged copy of itself
  (soft backfill instead of hard bars).

Only switch away from `crop` deliberately, for a specific shot where center
cropping would cut out essential content (e.g. a wide landscape or on-screen
text near the edges).

## Handoff to avatar-reel-composer

Found clips are drop-in B-roll. In the storyboard, set a `broll` scene to use an
existing clip instead of generating one:

```json
{
  "id": "s3", "type": "broll", "broll_source": "existing",
  "broll_clip": "lolo/broll/found/001_bourdain-pho-hanoi.mp4",
  "text": "viajar te cambia la forma de ver el mundo"
}
```

`compose_reel.py` uses the clip as-is (looping a too-short silent clip to cover
its slot, then trimming) and keeps the avatar's single master narration in sync.
Use `--frames` + the manifest's `rights_note` to vet each clip before publishing.

## Scripts

| Script | Purpose |
|---|---|
| `scripts/find_broll.py` | Orchestrator: search → transcripts → [agent checkpoint] → cut. Idempotent resume, `--status`. |
| `scripts/search.py` | YouTube search (Data API v3 + yt-dlp fallback, CC filter) → `candidates.json/.md`. |
| `scripts/transcripts.py` | Timecoded transcripts (captions, no download; `--whisper` ASR fallback) → `transcripts/<id>.json/.md`. |
| `scripts/cut_segment.py` | One window → 9:16 silent clip + manifest entry (URL section-download or local file). |
| `scripts/_common.py` | Shared: creds, search, transcript parsing, yt-dlp section download, ffmpeg fit/cut, manifest, license. |

## Anti-patterns

1. **Do not** publish standard-license clips without clearing rights — they are
   `reusable: false` (reference only). Prefer `--creative-commons` for publishing.
2. **Do not** download whole videos to find a 6s window — transcripts are fetched
   first (free, no download) so only the chosen sections are downloaded.
3. **Do not** scan dozens of long videos — cap with `--max-candidates` and
   `--max-duration`; skim transcripts before cutting.
4. **Do not** letterbox a 16:9 clip into 9:16 by default — the default is center
   crop-to-fill that covers the whole frame (no black bars). Switch to `--fit
   blur`/`pad` only deliberately, for a wide/landscape shot where cropping would
   cut out essential content.
5. **Do not** commit `found-broll/` or large clips — add them to `.gitignore`
   (research output + third-party media).
6. **Do not** forget attribution for Creative-Commons clips — credit the channel
   (`channel` / `source_url` are in the manifest).

## Troubleshooting

- **`youtube-transcript-api failed` then "falling back to yt-dlp subtitles"** —
  normal. The captions API is often IP-blocked; the yt-dlp VTT fallback still
  produces the timecoded transcript.
- **`No supported JavaScript runtime` / impersonation warnings from yt-dlp** —
  warnings, not errors; section download and subtitle fetch still work. If a
  download fails, update yt-dlp (`pip3 install -U yt-dlp`) and/or install a JS
  runtime (deno) per the yt-dlp wiki.
- **"Sign in to confirm you're not a bot" / age-gate** — add
  `--cookies-from-browser firefox` (the browser where you're logged into YouTube).
- **No candidates** — set `YT_API_KEY` for real search, drop `--creative-commons`,
  or broaden the `--query`.

## Additional resources

- Usage walkthrough: [examples.md](examples.md)
- Synthetic counterpart: `broll-generator`. Consumer: `avatar-reel-composer`
  (`broll_source: existing`). Discovery at scale: `reel-discovery`.
