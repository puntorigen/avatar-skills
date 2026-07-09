# Examples

## Download a whole public profile

```bash
python3 .cursor/skills/tiktok-videos/scripts/download_profile_videos.py \
  --url "https://www.tiktok.com/@username" \
  --output-dir out/tiktok \
  --timezone America/Santiago
```

## Real run (verified)

Downloading 2 videos from a public profile with the default `hybrid` engine. yt-dlp's
per-video extraction was temporarily broken (TikTok signing change), and the tikwm
fallback transparently handled both — exactly what hybrid is for:

```
Listing videos for: https://www.tiktok.com/@scout2015
    yt-dlp failed (ERROR: [TikTok] ...: Unable to extract universal data...); falling back to tikwm
Found 2 video(s). Engine=hybrid. Downloading to /tmp/tiktok_smoke
  - 7650148586478521631: ok via tikwm (18143833 bytes)
  - 7650141715604589854: ok via tikwm (20449569 bytes)

Done. 2 downloaded, 0 failed -> /tmp/tiktok_smoke
Manifest: /tmp/tiktok_smoke/videos_manifest.json
  2026-06-12_17-30-00.mp4  (tikwm)
  2026-06-11_15-30-00.mp4  (tikwm)
```

Resulting files (named by exact upload datetime, newest sorts last alphabetically):

```
2026-06-11_15-30-00.mp4
2026-06-12_17-30-00.mp4
videos_manifest.json
```

Manifest entry shape:

```json
{
  "id": "7650148586478521631",
  "url": "https://www.tiktok.com/@scout2015/video/7650148586478521631",
  "title": "I genuinely thought I wasted an entire day on this ... #pool #cutedogs",
  "timestamp": 1781299800,
  "uploadDate": "2026-06-12T17:30:00-04:00",
  "source": "tikwm",
  "local": "2026-06-12_17-30-00",
  "file": "2026-06-12_17-30-00.mp4"
}
```

## A single video or short link

```bash
python3 .cursor/skills/tiktok-videos/scripts/download_profile_videos.py \
  --url "https://vm.tiktok.com/ZMabcdef/" \
  --output-dir out/tiktok
```

The short link is resolved to its canonical `.../video/{id}` URL automatically.

## Force no-watermark via tikwm only

```bash
python3 .cursor/skills/tiktok-videos/scripts/download_profile_videos.py \
  --url "https://www.tiktok.com/@username" \
  --output-dir out/tiktok \
  --engine tikwm
```

## Two-step (review listing before downloading)

```bash
yt-dlp --flat-playlist -J "https://www.tiktok.com/@username" > listing.json
# inspect listing.json, trim entries if desired, then:
python3 .cursor/skills/tiktok-videos/scripts/download_profile_videos.py \
  --listing-json listing.json \
  --output-dir out/tiktok
```
