# broll-finder — examples

## 1. Find Anthony Bourdain street-food footage for a `lolo` reel

```bash
# Stage 1+2: search + transcripts, then stops at the checkpoint
python3 .cursor/skills/broll-finder/scripts/find_broll.py \
    --query "anthony bourdain street food vietnam" \
    --avatar-dir lolo --max-candidates 8 --lang en --creative-commons --frames
```

Console (truncated):

```
=== [1/3] search.py ===
=== [2/3] transcripts.py ===
========================================================================
CHECKPOINT — agent action required:
  1. Skim found-broll/anthony-bourdain-street-food-vietnam/candidates.md
     and .../transcripts/*.md
  2. Copy selection.template.json -> selection.json and edit it
  3. Re-run the same command to cut the clips.
========================================================================
```

Now the **agent** reads the transcripts (each line is a `[mm:ss]` block), e.g.:

```
[02:10] this is the best pho I have had in my entire life, right here on a
        plastic stool on the sidewalk in Hanoi
[02:18] the broth, the herbs, everything about this is perfect
```

…and writes `found-broll/anthony-bourdain-street-food-vietnam/selection.json`:

```json
{
  "segments": [
    { "url": "https://youtu.be/VIDEOID", "start": 130, "end": 136,
      "description": "Bourdain comiendo pho en un puesto callejero de Hanoi", "fit": "crop" },
    { "url": "https://youtu.be/VIDEOID", "start": 152, "end": 158,
      "description": "primer plano del caldo de pho humeante con hierbas", "fit": "blur" }
  ]
}
```

Re-run the same command → stage 3 downloads only those windows and writes:

```
lolo/broll/found/001_bourdain-comiendo-pho-en-un-puesto-callejero.mp4
lolo/broll/found/002_primer-plano-del-caldo-de-pho-humeante.mp4
lolo/broll/found/manifest.json     # source_url, channel, license, segment, rights_note
lolo/broll/found/001_*.jpg         # review frames (--frames)
```

## 2. One clip directly (no orchestrator)

```bash
python3 .cursor/skills/broll-finder/scripts/cut_segment.py \
    --url "https://youtu.be/VIDEOID" --start 41.5 --end 47 \
    --description "mercado nocturno, vapor de los puestos, multitud" \
    --avatar-dir lolo --fit blur --frame
```

## 3. Use a found clip in a storyboard

```json
{
  "avatar_dir": "lolo",
  "slug": "viajar-cambia",
  "scenes": [
    { "id": "s1", "type": "talking_head", "text": "déjame contarte algo sobre viajar.", "angle": "eye_level" },
    { "id": "s2", "type": "broll", "broll_source": "existing",
      "broll_clip": "lolo/broll/found/001_bourdain-comiendo-pho-en-un-puesto-callejero.mp4",
      "text": "a veces una comida en la calle te enseña más que un libro." }
  ]
}
```

```bash
python3 ~/.cursor/skills/avatar-reel-composer/scripts/compose_reel.py viajar-cambia.storyboard.json --language es
```

## 4. Standalone search / transcripts (debugging)

```bash
python3 .cursor/skills/broll-finder/scripts/search.py \
    --query "ocean waves drone" --creative-commons --sort views -o ./work

python3 .cursor/skills/broll-finder/scripts/transcripts.py \
    --candidates ./work/candidates.json --max 5 --lang en -o ./work
```

## Notes

- Add `found-broll/` and `**/broll/found/` to `.gitignore` (research + third-party media).
- For videos with no captions, add `--whisper` (downloads audio + faster-whisper; slower).
- Bot-gated videos: add `--cookies-from-browser firefox`.
```
