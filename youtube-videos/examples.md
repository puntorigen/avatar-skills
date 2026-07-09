# Examples

## Download a whole channel (videos + shorts)

A bare channel URL expands to both the `/videos` and `/shorts` tabs automatically.

```bash
python3 .cursor/skills/youtube-videos/scripts/download_channel_videos.py \
  --url "https://www.youtube.com/@handle" \
  --output-dir out/youtube \
  --max-height 720 \
  --timezone America/Santiago
```

For large channels, cap the count (or just re-run — the archive resumes):

```bash
  --max 25
```

## Real run (verified)

Downloading 2 Shorts from a public channel at 720p:

```
Listing videos for: https://www.youtube.com/@mkbhd/shorts
  listing: https://www.youtube.com/@mkbhd/shorts
Found 2 video(s). max_height=720. Downloading to /tmp/yt_smoke
  - n3V3LZh_r40: ok (12259873 bytes)
  - ImRy_PiXstI: ok (2380993 bytes)

Done. 2 downloaded, 0 skipped, 0 failed -> /tmp/yt_smoke
Manifest: /tmp/yt_smoke/videos_manifest.json
  2026-06-04_15-41-28.mp4
  2026-05-29_12-16-48.mp4
```

Resulting files (named by exact upload datetime):

```
2026-05-29_12-16-48.mp4
2026-06-04_15-41-28.mp4
download-archive.txt
videos_manifest.json
```

Manifest entry shape (clean H.264 + AAC mp4, confirmed via ffprobe):

```json
{
  "id": "n3V3LZh_r40",
  "url": "https://www.youtube.com/shorts/n3V3LZh_r40",
  "title": "Apple Products That DON'T Exist",
  "timestamp": 1780602088,
  "uploadDate": "2026-06-04T15:41:28-04:00",
  "height": 720,
  "local": "2026-06-04_15-41-28",
  "file": "2026-06-04_15-41-28.mp4"
}
```

Re-running the same command skips already-downloaded videos via `download-archive.txt`:

```
  - n3V3LZh_r40: skipped (archive)
  - ImRy_PiXstI: skipped (archive)
Done. 0 downloaded, 2 skipped, 0 failed
```

## A single video or short

```bash
python3 .cursor/skills/youtube-videos/scripts/download_channel_videos.py \
  --url "https://youtu.be/aqz-KE-bpKQ" \
  --output-dir out/youtube
```

Works the same for `https://www.youtube.com/watch?v=...` and `https://www.youtube.com/shorts/...`.

## A playlist

```bash
python3 .cursor/skills/youtube-videos/scripts/download_channel_videos.py \
  --url "https://www.youtube.com/playlist?list=PLxxxxxxxx" \
  --output-dir out/youtube
```

## Higher quality

```bash
python3 .cursor/skills/youtube-videos/scripts/download_channel_videos.py \
  --url "https://www.youtube.com/@handle" \
  --output-dir out/youtube \
  --max-height 1080
```

## Age/bot-gated public videos (use your own browser cookies)

If yt-dlp reports "Sign in to confirm you're not a bot" or an age gate:

```bash
python3 .cursor/skills/youtube-videos/scripts/download_channel_videos.py \
  --url "https://www.youtube.com/@handle" \
  --output-dir out/youtube \
  --cookies-from-browser chrome
```

## Two-step (review listing before downloading)

```bash
yt-dlp --flat-playlist -J "https://www.youtube.com/@handle/videos" > listing.json
# inspect listing.json, trim entries if desired, then:
python3 .cursor/skills/youtube-videos/scripts/download_channel_videos.py \
  --listing-json listing.json \
  --output-dir out/youtube
```
