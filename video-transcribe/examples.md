# video-transcribe — examples

## 1. Instagram reel → transcript (the original use case)

```bash
python3 .cursor/skills/video-transcribe/scripts/transcribe.py \
  "https://www.instagram.com/reels/DZScDIDNTi7/" \
  --output-dir reference-reels/DZScDIDNTi7 --language es
```

Produces:

```
reference-reels/DZScDIDNTi7/
├── transcript.mp4    # the downloaded reel
├── transcript.txt    # full spoken text
├── transcript.srt    # subtitles with timecodes
└── transcript.json   # language, duration, model, per-segment timecodes
```

stdout (after the run) prints the text, e.g.:

```
lang=es (1.00)  dur=44.6s  model=small
============================================================
Vas a estar bien. No. Escúchame de verdad. Vas a estar bien. ...
```

## 2. Local file (already downloaded)

```bash
python3 .cursor/skills/video-transcribe/scripts/transcribe.py lolo/videos/2026-06-08_15-02-03.mp4
```

Outputs land next to the file as `2026-06-08_15-02-03.txt/.srt/.json`.

## 3. Higher accuracy, custom name, drop the video

```bash
python3 .cursor/skills/video-transcribe/scripts/transcribe.py \
  "https://www.instagram.com/reel/XXXX/" \
  --output-dir out --basename eva_vas_a_estar_bien \
  --model large-v3 --language es --cleanup
```

`--cleanup` deletes the downloaded mp4 after writing the transcript files.

## Tip: feed the transcript into a reel

The `.txt` is a ready starting point for a script. Adapt it to an avatar's voice
and structure, then build the reel with `avatar-reel-composer` (see that skill).
