---
name: tiktok-videos
description: Download all public videos from a TikTok profile (or a single TikTok video / short link) to a local folder, named with upload date-time (YYYY-MM-DD_HH-MM-SS.mp4). Uses yt-dlp as the primary engine with the tikwm.com no-watermark API as a fallback. Use when the user asks to download TikTok videos, save a TikTok profile's videos locally, grab a TikTok without watermark, or batch-download profile videos with datetime filenames.
---

# TikTok Videos Downloader

Download every public video from a TikTok profile (or a single video / short link) into a user-specified folder, named by upload datetime.

**Unlike Instagram, TikTok does NOT require a browser mirror.** `yt-dlp` works directly on profile and video URLs, so there is no Picnob-style scrape here. Keep the two-source resilience pattern though: `yt-dlp` is primary, `tikwm.com` (no-watermark public API) is the fallback.

## Inputs

| Parameter | Required | Example |
|---|---|---|
| TikTok URL (profile, video, or short link) | yes | `https://www.tiktok.com/@scout2015` |
| Output directory | yes | `out/tiktok` |
| Engine | no | `hybrid` (default), `ytdlp`, or `tikwm` |
| Timezone for filenames | no | `America/Santiago` (default) |

Accepted URL shapes (the script normalizes them):
- Profile: `tiktok.com/@user` → all videos
- Single video: `tiktok.com/@user/video/{id}`
- Photo carousel: `tiktok.com/@user/photo/{id}` (skipped unless `--include-images`)
- Short links: `vm.tiktok.com/xxx`, `vt.tiktok.com/xxx` (redirect is resolved first)

## Prerequisites

`yt-dlp` and `ffmpeg` must be installed (both present on this machine). Keep yt-dlp fresh — TikTok rotates its signing, so an outdated yt-dlp is the #1 cause of failures:

```bash
yt-dlp --version || python3 -m pip install -U yt-dlp
```

## Workflow checklist

```
- [ ] Step 1: Verify profile/video is public
- [ ] Step 2: (optional) Pre-fetch listing to review before downloading
- [ ] Step 3: Run download script
- [ ] Step 4: Report results
```

---

## Step 1: Verify it's public

Open the URL. If it shows "This account is private" / a login wall / "Video currently unavailable", **stop** — this skill is for public content only.

## Step 2 (optional): Pre-fetch the listing

The script lists internally, but you can inspect first. This needs no browser:

```bash
yt-dlp --flat-playlist -J "https://www.tiktok.com/@username" > listing.json
```

`listing.json` has an `entries` array of `{id, url, title}`. Pass it back in with `--listing-json` to download exactly that set.

## Step 3: Download and rename

```bash
python3 .cursor/skills/tiktok-videos/scripts/download_profile_videos.py \
  --url "https://www.tiktok.com/@username" \
  --output-dir out/tiktok \
  --engine hybrid \
  --timezone America/Santiago
```

The script:
1. Resolves short links and lists the profile's videos (yt-dlp `--flat-playlist`; falls back to tikwm `user/posts` if yt-dlp listing fails)
2. Downloads each video — **yt-dlp primary, tikwm no-watermark fallback** per item
3. Reads the exact upload `timestamp` (yt-dlp `info.json`) or `create_time` (tikwm)
4. Renames to `YYYY-MM-DD_HH-MM-SS.mp4` in the chosen timezone
5. Writes `{output_dir}/videos_manifest.json` (id, url, title, uploadDate, source, file)

Useful flags: `--max N` (cap count), `--engine tikwm` (force no-watermark), `--engine ytdlp` (no third-party dependency), `--include-images`, `--delay-ms`.

**Collisions:** two videos at the same second get `_2`, `_3` suffixes.

## Step 4: Report to user

Summarize: handle/URL, output path, count downloaded, any failures, engine source per file, and list filenames sorted newest-first.

---

## Engine strategy (why hybrid)

| Engine | Strength | Weakness |
|---|---|---|
| **yt-dlp** (primary) | Most maintained, handles TikTok signing, whole-profile in one call, no third-party | Occasionally serves a watermarked render; breaks for a few days when TikTok changes signing |
| **tikwm** (fallback) | Guaranteed no-watermark + exact `create_time`, simple JSON | Third-party service, ~1 req/sec rate limit, can go down |

`hybrid` runs yt-dlp first and only calls tikwm for items yt-dlp fails on — mirroring the `instagram-videos` Picnob+ImgInn dual-source resilience.

## Anti-patterns

1. **Do not** start by hand-scraping the TikTok web page — `yt-dlp` already handles listing. (This is the opposite of Instagram, where direct tools 401.)
2. **Do not** run with a stale yt-dlp. Update it before blaming the site.
3. **Do not** hammer tikwm faster than ~1 req/sec — it rate-limits.
4. **Do not** download private / age-gated / region-locked content.
5. **Do not** commit large `out/` video folders — add the output dir to `.gitignore`.

## Utility scripts

| Script | Purpose |
|---|---|
| `scripts/download_profile_videos.py` | List + download (yt-dlp + tikwm fallback) + datetime rename + manifest (main entry point) |

## Additional resources

- Real run example: [examples.md](examples.md)
- For Instagram (needs a browser mirror), use the `instagram-videos` skill.
