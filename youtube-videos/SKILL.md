---
name: youtube-videos
description: Download all public videos from a YouTube channel (or a playlist, single video, or Short) to a local folder, named with upload date-time (YYYY-MM-DD_HH-MM-SS.mp4), capped at 720p mp4. Uses yt-dlp + ffmpeg. Use when the user asks to download YouTube videos, a channel's videos, a playlist, Shorts, or batch-download videos with datetime filenames.
---

# YouTube Videos Downloader

Download every public video from a YouTube channel (or a playlist / single video / Short) into a user-specified folder, named by upload datetime.

**YouTube is yt-dlp's strongest platform — this is the simplest of the three downloader skills.** No browser mirror (unlike `instagram-videos`) and no third-party fallback engine (unlike `tiktok-videos`). It is single-engine: `yt-dlp` does both listing and download.

## Inputs

| Parameter | Required | Example |
|---|---|---|
| YouTube URL (channel, playlist, video, or short) | yes | `https://www.youtube.com/@mkbhd` |
| Output directory | yes | `out/youtube` |
| Max height | no | `720` (default) |
| Timezone for filenames | no | `America/Santiago` (default) |

Accepted URL shapes (the script normalizes them):
- Channel root: `youtube.com/@handle`, `/channel/UC...`, `/c/name`, `/user/name` → expands to BOTH the `/videos` and `/shorts` tabs
- A specific tab/playlist: `.../videos`, `.../shorts`, `?list=...` → used as-is
- Single video: `youtube.com/watch?v=...`, `youtu.be/...`
- Short: `youtube.com/shorts/...`

## Prerequisites

`yt-dlp` AND `ffmpeg` must be installed (both present on this machine). ffmpeg is required because YouTube serves separate video and audio (DASH) streams that must be merged. Keep yt-dlp fresh — an outdated yt-dlp is the #1 cause of YouTube failures:

```bash
yt-dlp --version || python3 -m pip install -U yt-dlp
ffmpeg -version | head -1
```

## Workflow checklist

```
- [ ] Step 1: Verify the channel/video is public
- [ ] Step 2: (optional) Pre-fetch listing to review before downloading
- [ ] Step 3: Run download script
- [ ] Step 4: Report results
```

---

## Step 1: Verify it's public

Open the URL. If it's private, members-only, age-restricted, or unavailable in the region, **stop** — this skill is for public content. (For age/bot-gated *public* videos you own access to, see `--cookies-from-browser` below.)

## Step 2 (optional): Pre-fetch the listing

The script lists internally, but you can inspect first:

```bash
yt-dlp --flat-playlist -J "https://www.youtube.com/@handle/videos" > listing.json
```

`listing.json` has an `entries` array of `{id, url, title}` (no dates — those are resolved during download). Pass it back with `--listing-json` to download exactly that set.

## Step 3: Download and rename

```bash
python3 .cursor/skills/youtube-videos/scripts/download_channel_videos.py \
  --url "https://www.youtube.com/@handle" \
  --output-dir out/youtube \
  --max-height 720 \
  --timezone America/Santiago
```

The script:
1. Normalizes the URL (a bare channel → `/videos` + `/shorts`), lists entries via `yt-dlp --flat-playlist`, merges and dedupes by video id
2. Downloads each video at ≤720p, preferring H.264/AAC, merged to mp4 (clean for the downstream avatar pipeline)
3. Reads the exact upload `timestamp` (or `upload_date`) from each video's `info.json`
4. Renames to `YYYY-MM-DD_HH-MM-SS.mp4` in the chosen timezone (date-only videos → `..._00-00-00`)
5. Maintains `download-archive.txt` in the output dir so re-runs resume instead of re-downloading
6. Writes `{output_dir}/videos_manifest.json` (id, url, title, timestamp, uploadDate, height, file)

Useful flags: `--max N` (cap count — important for large channels), `--max-height 1080`, `--cookies-from-browser chrome`, `--no-archive`, `--delay-ms`.

**Collisions:** two videos at the same second get `_2`, `_3` suffixes.

## Step 4: Report to user

Summarize: channel/URL, output path, count downloaded / skipped / failed, and list filenames sorted newest-first.

---

## Why no fallback engine

| Platform | Listing | Download | Why |
|---|---|---|---|
| Instagram | browser scrape (Picnob) | Picnob/ImgInn | direct tools 401 |
| TikTok | yt-dlp flat-playlist | yt-dlp + tikwm fallback | yt-dlp signing breaks intermittently |
| **YouTube** | **yt-dlp** | **yt-dlp** | yt-dlp is the gold standard; no reliable second source needed |

Resilience for YouTube is: (a) keep yt-dlp updated, and (b) `--cookies-from-browser` for the occasional "Sign in to confirm you're not a bot" / age-gate.

## Anti-patterns

1. **Do not** default to 4K/best — files get huge. Default cap is 720p; raise with `--max-height` only when needed.
2. **Do not** run with a stale yt-dlp. Update it before blaming the site.
3. **Do not** download an entire large channel blindly — use `--max N` or rely on the resume archive.
4. **Do not** download private / members-only / age-restricted content you don't have access to.
5. **Do not** forget ffmpeg — without it, merged mp4 output fails.
6. **Do not** commit large `out/` video folders — add the output dir to `.gitignore`.

## Utility scripts

| Script | Purpose |
|---|---|
| `scripts/download_channel_videos.py` | List + download (yt-dlp, 720p mp4) + datetime rename + archive resume + manifest (main entry point) |

## Additional resources

- Real run example: [examples.md](examples.md)
- For TikTok (yt-dlp + tikwm fallback), use the `tiktok-videos` skill.
- For Instagram (needs a browser mirror), use the `instagram-videos` skill.
