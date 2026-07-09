# Examples

## A single watch link (the common case)

```bash
python3 .cursor/skills/facebook-videos/scripts/download_facebook_videos.py \
  --url "https://www.facebook.com/watch/?v=10154325234224113" \
  --output-dir out/facebook \
  --timezone America/Santiago
```

## Real run (verified)

```
Listing videos for: https://www.facebook.com/watch/?v=10154325234224113
Found 1 video(s). max_height=1080. Downloading to /tmp/fb_smoke
  - 10154325234224113: ok (2907228 bytes)

Done. 1 downloaded, 0 skipped, 0 failed -> /tmp/fb_smoke
Manifest: /tmp/fb_smoke/videos_manifest.json
  2016-05-25_12-42-58.mp4
```

Resulting files (named by exact upload datetime — the long caption stays in the manifest, not the filename):

```
2016-05-25_12-42-58.mp4
download-archive.txt
videos_manifest.json
```

Manifest entry shape:

```json
{
  "id": "10154325234224113",
  "url": "https://www.facebook.com/watch/?v=10154325234224113",
  "title": "26 reactions · 10 comments | La periodista Mariela Aravena estuvo en la audiencia de formalización de uno de los alumnos que ingresó a La Moneda...",
  "timestamp": 1464194578,
  "uploadDate": "2016-05-25T12:42:58-04:00",
  "height": 1080,
  "local": "2016-05-25_12-42-58",
  "file": "2016-05-25_12-42-58.mp4"
}
```

Re-running the same command skips the already-downloaded video via `download-archive.txt`:

```
  - 10154325234224113: skipped (archive)
Done. 0 downloaded, 1 skipped, 0 failed
```

## A reel or a video permalink

Same command — just swap the URL:

```bash
python3 .cursor/skills/facebook-videos/scripts/download_facebook_videos.py \
  --url "https://www.facebook.com/reel/1234567890" \
  --output-dir out/facebook
```

```bash
python3 .cursor/skills/facebook-videos/scripts/download_facebook_videos.py \
  --url "https://www.facebook.com/somepage/videos/1234567890/" \
  --output-dir out/facebook
```

Short links work too: `https://fb.watch/xxxxxxxx/`.

## Just the first video of a Page

A Page's `/videos` tab lists many videos. Cap to the first with `--max 1`:

```bash
python3 .cursor/skills/facebook-videos/scripts/download_facebook_videos.py \
  --url "https://www.facebook.com/somepage/videos" \
  --output-dir out/facebook \
  --max 1
```

## Login-walled public video (use your own browser cookies)

If the run prints `No videos found` or yt-dlp errors with "log in" / "cookies":

```bash
python3 .cursor/skills/facebook-videos/scripts/download_facebook_videos.py \
  --url "https://www.facebook.com/watch/?v=ID" \
  --output-dir out/facebook \
  --cookies-from-browser chrome
```

## Two-step (review listing before downloading)

```bash
yt-dlp --flat-playlist -J "https://www.facebook.com/somepage/videos" > listing.json
# inspect listing.json, trim entries if desired, then:
python3 .cursor/skills/facebook-videos/scripts/download_facebook_videos.py \
  --listing-json listing.json \
  --output-dir out/facebook
```
