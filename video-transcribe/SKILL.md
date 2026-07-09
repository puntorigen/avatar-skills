---
name: video-transcribe
description: Download a single video by URL (Instagram reel/post, or any yt-dlp-supported link) and transcribe its spoken audio to text with faster-whisper — or transcribe a local media file. Writes plain text, an SRT subtitle file, and a JSON with per-segment timecodes. Uses yt-dlp for download and faster-whisper (default `small`, CPU/int8) for transcription. Use when the user wants the spoken text / transcript / subtitles of an Instagram reel or other video, wants to turn a reel's audio into a script, or wants to transcribe a local audio/video file.
---

# Video Transcribe

Download one video by URL and extract its spoken audio as text, or transcribe a
local media file. One script does both: `scripts/transcribe.py`.

Output (in the chosen folder): `<basename>.txt` (full text), `<basename>.srt`
(subtitles), `<basename>.json` (language, duration, model, and per-segment
timecodes).

## Inputs

| Parameter | Required | Example |
|---|---|---|
| Video URL **or** local file path | yes | `https://www.instagram.com/reels/DZScDIDNTi7/` |
| `--output-dir` | no | `reference-reels/DZScDIDNTi7` |
| `--language` | no | `es` (default: auto-detect) |
| `--model` | no | `small` (default), `medium`, `large-v3`, `tiny` |

## Prerequisites

`yt-dlp`, `ffmpeg`, and `faster-whisper` must be available (all present on this
machine). If needed: `pip3 install -r requirements.txt` and `brew install ffmpeg`.

## Workflow checklist

```
- [ ] Step 1: Confirm the content is public (URL) or the file exists (local)
- [ ] Step 2: Run transcribe.py (downloads if URL, then transcribes)
- [ ] Step 3: Report the text + output file paths
```

## Step 1: Source check

For a URL, open it to confirm it is **public** (no login wall / not private). For
a local file, confirm the path exists. Stop if private/missing.

## Step 2: Download + transcribe

```bash
# Instagram reel (or any yt-dlp URL): download + transcribe, force Spanish
python3 .cursor/skills/video-transcribe/scripts/transcribe.py \
  "https://www.instagram.com/reels/DZScDIDNTi7/" \
  --output-dir reference-reels/DZScDIDNTi7 --language es

# Local file (outputs land next to it as <stem>.txt/.srt/.json)
python3 .cursor/skills/video-transcribe/scripts/transcribe.py path/to/clip.mp4
```

The script:
1. If the source is a URL, downloads it with `yt-dlp --no-playlist` (best mp4) to
   `<output-dir>/<basename>.<ext>`.
2. Transcribes the media with faster-whisper (VAD-filtered). faster-whisper decodes
   the media via ffmpeg, so **no separate audio extraction step is needed**.
3. Writes `<basename>.txt`, `<basename>.srt`, `<basename>.json` and prints the
   full text to stdout.

Defaults: `--basename transcript` for URLs (file stem for local files),
`--output-dir .` for URLs (the file's own folder for local files).

Useful flags: `--model large-v3` (higher accuracy, slower + ~GBs download),
`--language es` (skip auto-detect / fix wrong detection), `--cleanup` (delete the
downloaded video afterwards), `--device cuda` `--compute-type float16` (GPU).

## Step 3: Report to user

Give the detected language, duration, the transcript text, and the output paths.
Fix only obvious ASR slips (it is phonetic: e.g. `tu menta` → `tu mente`,
acronyms mis-heard) when handing the text to the user — note any corrections.

## Model choice

`small` (default) matches the repo's voice / alignment pipeline (`voice-isolate`,
`avatar-reel-composer`) and is fast on CPU with good Spanish accuracy. Step up to
`medium` / `large-v3` only when accuracy matters more than speed; `tiny` for quick
tests. First use of a model downloads its weights (large-v3 is ~3 GB).

## Anti-patterns

1. **Do not** hand-extract audio with a separate ffmpeg call first — faster-whisper
   decodes the media directly.
2. **Do not** use this for a whole Instagram/TikTok/YouTube *profile* — it handles
   one video. For batch profile downloads use `instagram-videos`, `tiktok-videos`,
   or `youtube-videos`, then point this at the saved files.
3. **Do not** transcribe private / login-walled content.
4. **Do not** commit downloaded videos — add the output dir to `.gitignore`.

## Utility scripts

| Script | Purpose |
|---|---|
| `scripts/transcribe.py` | Download (yt-dlp) if URL + transcribe (faster-whisper) → txt/srt/json (main entry point) |

## Additional resources

- Usage examples: [examples.md](examples.md)
- To then clone the voice / build a reel from the transcript, see the
  `voice-clone` and `avatar-reel-composer` skills.
