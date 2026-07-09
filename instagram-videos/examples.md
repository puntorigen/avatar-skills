# Instagram Videos — Examples

## Example: @arnoldo_schaffner_bofill → `lolo/videos/`

**User request:** Download public videos from `https://www.instagram.com/arnoldo_schaffner_bofill/` into `lolo/videos`, named with date-time.

### Step 1 — Scrape Picnob

Navigate to `https://www.picnob.com/profile/arnoldo_schaffner_bofill/`, scroll + extract via browser MCP. Result: 10 posts, all reels (`.mp4` URLs despite `isVideo: false`).

### Step 2 — Save JSON

```bash
# Save browser result to:
posts-raw/meta/picnob_arnoldo_schaffner_bofill.json
```

### Step 3 — Download

```bash
python3 ~/.cursor/skills/instagram-videos/scripts/download_profile_videos.py \
  --posts-json posts-raw/meta/picnob_arnoldo_schaffner_bofill.json \
  --output-dir lolo/videos \
  --timezone America/Santiago
```

### Result

```
10 videos downloaded, 0 errors
Manifest: lolo/videos/videos_manifest.json

2026-06-08_15-02-03.mp4
2026-05-21_21-33-22.mp4
2026-05-16_12-25-46.mp4
2024-04-19_20-00-32.mp4
2024-02-24_21-28-59.mp4
2024-02-10_22-18-40.mp4
2024-01-21_15-46-18.mp4
2024-01-13_17-02-42.mp4
2024-01-10_22-53-51.mp4
2024-01-10_10-05-31.mp4
```

---

## Example: Custom timezone

US Eastern time:

```bash
python3 ~/.cursor/skills/instagram-videos/scripts/download_profile_videos.py \
  --posts-json posts-raw/meta/picnob_somehandle.json \
  --output-dir assets/reels \
  --timezone America/New_York
```

---

## Example: Re-run safely

The download script skips files that already exist at the temp stage. To refresh all videos, delete the output folder first.
