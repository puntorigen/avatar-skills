---
name: instagram-videos
description: Download all public videos/reels from an Instagram profile to a local folder, named with upload date-time (YYYY-MM-DD_HH-MM-SS.mp4). Uses Picnob via browser automation plus a Python download script. Use when the user asks to download Instagram videos, reels, or video content from a public profile, save IG videos locally, or batch-download profile reels with datetime filenames.
---

# Instagram Videos Downloader

Download every public video/reel from an Instagram profile into a user-specified folder, named by upload datetime.

**Do not use** `instaloader`, `yt-dlp`, or `gallery-dl` on profile URLs first — they return 401 without a session cookie. Use Picnob.

## Inputs

| Parameter | Required | Example |
|---|---|---|
| Instagram handle or profile URL | yes | `arnoldo_schaffner_bofill` |
| Output directory | yes | `lolo/videos` |
| Timezone for filenames | no | `America/Santiago` (default) |

Extract handle from URLs: `instagram.com/{handle}/` → `{handle}`.

## Workflow checklist

```
- [ ] Step 1: Verify profile is public
- [ ] Step 2: Scrape Picnob profile feed (browser)
- [ ] Step 3: Save posts JSON
- [ ] Step 4: Run download script
- [ ] Step 5: Report results
```

---

## Step 1: Verify profile is public

Open `https://www.instagram.com/{handle}/` in the browser. If it shows a login wall or "This Account is Private", **stop** — this skill is public profiles only.

## Step 2: Scrape Picnob via browser MCP

Navigate to `https://www.picnob.com/profile/{handle}/`.

Run via `browser_cdp` → `Runtime.evaluate` with `awaitPromise: true`:

```javascript
(async () => {
  let lastCount = 0, stable = 0;
  for (let i = 0; i < 60; i++) {
    window.scrollTo(0, document.body.scrollHeight);
    await new Promise(r => setTimeout(r, 1500));
    const c = document.querySelectorAll('.post_box').length;
    if (c === lastCount) { if (++stable >= 3) break; } else { stable = 0; }
    lastCount = c;
  }
  const posts = [];
  document.querySelectorAll('.post_box').forEach((box, idx) => {
    const a = box.querySelector('a[href*="/post/"]');
    const m = a?.href?.match(/\/post\/([^/?#]+)/);
    const counts = Array.from(box.querySelectorAll('.num')).map(e => e.textContent.trim());
    posts.push({
      idx, pId: m?.[1],
      caption: box.querySelector('.sum')?.textContent?.trim() || '',
      time: box.querySelector('.time')?.textContent?.trim() || '',
      likes: counts[0], comments: counts[1],
      downloadUrl: box.querySelector('.downbtn')?.href,
      isVideo: !!box.querySelector('.icon_video, [class*=video]'),
      isSidecar: !!box.querySelector('.icon_album, [class*=sidecar], [class*=album]'),
      picnobHref: a?.href,
    });
  });
  return posts;
})()
```

## Step 3: Save posts JSON

Save the result to `{project}/posts-raw/meta/picnob_{handle}.json`. Create `posts-raw/` if needed; add to `.gitignore` if not already there.

## Step 4: Download and rename

```bash
python3 ~/.cursor/skills/instagram-videos/scripts/download_profile_videos.py \
  --posts-json posts-raw/meta/picnob_{handle}.json \
  --output-dir {output_folder} \
  --timezone America/Santiago
```

The script:
1. Filters videos (`.mp4` in `downloadUrl` or `isVideo: true`)
2. Downloads each file from Picnob CDN URLs
3. Fetches exact `uploadDate` from each post's JSON-LD schema on Picnob
4. Renames to `YYYY-MM-DD_HH-MM-SS.mp4` in the chosen timezone
5. Writes `{output_folder}/videos_manifest.json`

**Video detection note:** Picnob often omits the video icon on reels. Always treat posts with `.mp4` in `downloadUrl` as videos — the script handles this.

**Collisions:** Two posts at the same second get `_2`, `_3` suffixes.

## Step 5: Report to user

Summarize: handle, output path, count downloaded, any errors, and list filenames sorted newest-first.

---

## Anti-patterns

1. **Do not** scrape faster than ~1 req/sec on Picnob post pages (date lookup).
2. **Do not** commit `posts-raw/` — scraping artifacts belong in `.gitignore`.
3. **Do not** use Picnob `pId` as Instagram shortcode — it's an internal ID.
4. **Do not** scrape private profiles.

## Utility scripts

| Script | Purpose |
|---|---|
| `scripts/download_profile_videos.py` | Download + datetime rename (main entry point) |
| `scripts/scrape_picnob.js` | Reference for browser-side scrape logic |

## Additional resources

- Real run example: [examples.md](examples.md)
- Full post/caption scraping (images, sidecars): use the `instagram-scraper` skill
