---
name: facebook-videos
description: Download public Facebook videos (a watch link, video permalink, reel, fb.watch short link, or a Page's videos tab) to a local folder, named by upload datetime (YYYY-MM-DD_HH-MM-SS.mp4). Single-engine yt-dlp + ffmpeg; uses --cookies-from-browser for login-walled public videos. Use when the user asks to download a Facebook video or reel, save an FB video locally, grab a video from a facebook.com/watch or fb.watch link, or batch-download a Page's videos.
---

# Facebook Videos Downloader

Download a public Facebook video (or a Page's videos) into a user-specified folder, named by upload datetime.

**Facebook is a single-engine `yt-dlp` target — like `youtube-videos`, not `instagram-videos`.** No browser mirror and no third-party fallback API. The one real difference: **Facebook is the most login-walled platform**, so the primary resilience path is `--cookies-from-browser` (your own logged-in session), NOT a second engine.

## Inputs

| Parameter | Required | Example |
|---|---|---|
| Facebook URL (watch, video, reel, fb.watch, or Page videos tab) | yes | `https://www.facebook.com/watch/?v=10154325234224113` |
| Output directory | yes | `out/facebook` |
| Max height | no | `1080` (default) |
| Timezone for filenames | no | `America/Santiago` (default) |

Accepted URL shapes (the script handles them via yt-dlp):
- Watch link: `facebook.com/watch/?v=ID` → single video
- Video permalink: `facebook.com/<page>/videos/ID/` → single video
- Reel: `facebook.com/reel/ID` → single video
- Share short link: `fb.watch/xxxx/` → yt-dlp resolves it
- Page videos tab: `facebook.com/<page>/videos` → a playlist (use `--max 1` for just the first)

## Prerequisites

`yt-dlp` AND `ffmpeg` must be installed (both present on this machine). ffmpeg is needed when Facebook serves separate video+audio (DASH) streams that must be merged. Keep yt-dlp fresh — an outdated yt-dlp is the #1 cause of Facebook failures:

```bash
yt-dlp --version || python3 -m pip install -U yt-dlp
ffmpeg -version | head -1
```

## Workflow checklist

```
- [ ] Step 1: Verify the video is public
- [ ] Step 2: (optional) Pre-fetch listing to review before downloading
- [ ] Step 3: Run download script
- [ ] Step 4: Report results
```

---

## Step 1: Verify it's public

Open the URL. If it sits behind a login wall, is friends-only, or is unavailable in the region, this skill can still work **if you pass your own cookies** (see Step 3 / cookies note). For truly private content you don't have access to, **stop**.

## Step 2 (optional): Pre-fetch the listing

The script lists internally, but for a Page you can inspect first:

```bash
yt-dlp --flat-playlist -J "https://www.facebook.com/<page>/videos" > listing.json
```

`listing.json` has an `entries` array of `{id, url, title}` (dates are resolved during download). Pass it back with `--listing-json` to download exactly that set.

## Step 3: Download and rename

```bash
python3 .cursor/skills/facebook-videos/scripts/download_facebook_videos.py \
  --url "https://www.facebook.com/watch/?v=10154325234224113" \
  --output-dir out/facebook \
  --max-height 1080 \
  --timezone America/Santiago
```

The script:
1. Lists entries via `yt-dlp --flat-playlist` (a single watch/video/reel URL → one entry; a Page videos tab → a playlist), dedupes by id/URL
2. Downloads each video (best ≤ `--max-height`, falling back to absolute best so Facebook's `hd`/`sd` progressive formats always download), merged to mp4
3. Reads the exact upload `timestamp` (or `upload_date`) from each video's `info.json`
4. Renames to `YYYY-MM-DD_HH-MM-SS.mp4` in the chosen timezone (date-only → `..._00-00-00`; no date → `unknown_<id>.mp4`)
5. Maintains `download-archive.txt` in the output dir so re-runs resume instead of re-downloading
6. Writes `{output_dir}/videos_manifest.json` (id, url, title, timestamp, uploadDate, height, file)

**To grab only the first video** of a Page's videos tab, add `--max 1`.

Useful flags: `--max N` (cap count), `--cookies-from-browser chrome`, `--max-height 720`, `--no-archive`, `--delay-ms`.

**Collisions:** two videos at the same second get `_2`, `_3` suffixes.

## Step 4: Report to user

Summarize: URL, output path, count downloaded / skipped / failed, and list filenames sorted newest-first. Datetime naming means a long Facebook caption never becomes the filename (the caption is kept in the manifest `title` instead).

---

## Login-walled videos (the Facebook gotcha)

If the run prints `No videos found` or yt-dlp errors with "log in" / "cookies" / "not available", the video is gated to logged-in users. Pass cookies from a browser where you're signed in to Facebook:

```bash
python3 .cursor/skills/facebook-videos/scripts/download_facebook_videos.py \
  --url "https://www.facebook.com/watch/?v=ID" \
  --output-dir out/facebook \
  --cookies-from-browser chrome
```

`--cookies-from-browser` accepts `chrome`, `firefox`, `safari`, `edge`, `brave`. The script auto-appends a hint to error messages reminding you to retry with cookies.

## Why no fallback engine

| Platform | Listing | Download | Resilience |
|---|---|---|---|
| Instagram | browser scrape (Picnob) | Picnob/ImgInn | direct tools 401 |
| TikTok | yt-dlp flat-playlist | yt-dlp + tikwm fallback | yt-dlp signing breaks intermittently |
| YouTube | yt-dlp | yt-dlp | keep yt-dlp fresh; cookies for bot-gate |
| **Facebook** | **yt-dlp** | **yt-dlp** | **`--cookies-from-browser` for login walls** |

## Anti-patterns

1. **Do not** hand-scrape the Facebook page HTML — `yt-dlp` already extracts the video. (Unlike Instagram.)
2. **Do not** run with a stale yt-dlp. Update it before blaming the site.
3. **Do not** assume failure means impossible — try `--cookies-from-browser` first; Facebook gates much more aggressively than YouTube.
4. **Do not** download private / friends-only content you don't have access to.
5. **Do not** forget ffmpeg — without it, DASH merges fail.
6. **Do not** commit large `out/` video folders — add the output dir to `.gitignore`.

## Utility scripts

| Script | Purpose |
|---|---|
| `scripts/download_facebook_videos.py` | List + download (yt-dlp, mp4) + datetime rename + archive resume + manifest (main entry point) |

## Additional resources

- Real run example: [examples.md](examples.md)
- For YouTube (channels/playlists/Shorts), use the `youtube-videos` skill.
- For TikTok (yt-dlp + tikwm fallback), use the `tiktok-videos` skill.
- For Instagram (needs a browser mirror), use the `instagram-videos` skill.
