# broll-story — reference

Detailed guidance for authoring the **Phase-1 storyboard prompt** for a
broll-story clip. The baseline methodology lives in gpt-image-2's
`prompts/storyboard_framework.md` — this file only adds the broll-story-specific
adaptation. **Do not simplify the baseline**; this narrows it, it does not replace it.

## Panel grid by ratio (6 panels)
| Ratio | Grid | Sheet aspect to pass gpt-image-2 |
|---|---|---|
| `16:9` (horizontal) | **3 columns × 2 rows** | `-ar 16:9` |
| `9:16` (vertical) | **2 columns × 3 rows** | `-ar 9:16` |

The framework flips the grid for vertical (rows×columns), so a vertical sheet
reads top-to-bottom in two columns. State the exact grid in section A.

## What makes it a "story" B-roll (not a talking head)
Every panel is about the **action**, framed by the **camera**:
- POV / first-person (the avatar's hands, the avatar showing a place).
- Over-the-shoulder and **from behind** (avatar's back to camera while doing the thing).
- Full-body wide that shows the whole activity and the environment.
- Inserts / macro of the object being used (phone, screen, calendar, ingredients, tool).
- A camera change between most panels (push-in, orbit, whip, crane, rack focus).
- Optional invented side-characters the avatar interacts with — consistent design.

The avatar is **not** addressing the lens to speak; treat any "dialogue" as
off-screen VO and leave it out of the panels. Write **Action**, never `Dialogue`.

## Phase-1 storyboard prompt template (adapt, keep all sections)
Author one continuous block (≈800–1,200 words for 6 panels), sections A–H from the
framework:

- **A) Title & Format Header** — e.g. *"6-panel cinematic storyboard sheet for a
  vertical 9:16 product-demo B-roll titled '<slug>'. A clean professional
  storyboard presentation page with 6 sequential panels arranged in a 2×3 grid
  (2 columns × 3 rows), numbered with timeline labels and a short action note
  under each frame."*
- **B) Style Declaration** — match the avatar's look (e.g. soft-3D Pixar /
  Monsters-Inc feature CG for Doki). Be a creative-director brief for that look.
- **C) Character Descriptions** — the avatar's identity/wardrobe DNA (pulled from
  `--avatar-ref`) + any invented side-characters; demand they stay identical.
- **D) Visual Tone** — palette, lighting, atmosphere, brand glow.
- **E) Storyboard Layout Details** — production board look: numbered frames,
  timeline labels, action notes, clean typography, studio-quality sheet.
- **F) Scene Breakdown** — `Panel N: [Shot type] shot. [what the avatar is DOING,
  the environment, the camera]`. Vary shot type every panel; carry the action
  forward. Distribute character detail across panels (face in close-ups, full
  wardrobe in wides). Timecodes are optional and **not** constrained to 8s.
- **G) Art Direction Footer** — expression/animation quality, camera variety,
  texture/environment detail, composition.
- **H) Rendering & Format Footer** — render-quality cues, the aspect ratio,
  "professional storyboard sheet", quality tier.

## Worked example (Doki, 9:16, "shows the office & schedules")
Short script (VO, added later): *"Te muestro mi oficina… contesto, agendo y dejo
todo listo, mientras tú sigues con lo tuyo."*

6 action beats → 2×3 grid:
1. POV wide: Doki walks the camera through a cozy night studio (his back to us).
2. Over-the-shoulder: a chat window lights up; he turns toward it.
3. Insert/macro: his hand taps a glowing reply on a floating panel.
4. Medium: he switches to a voice/video call — a second invented character appears on a screen.
5. Wide full-body: he gestures to a calendar wall that fills with "Reunión ✓".
6. Low-angle hero: he gives a satisfied thumbs-up to the room, lights settle.

Then animate the single sheet:
```bash
python3 .cursor/skills/broll-story/scripts/make_broll_story.py \
  --prompt-file doki_office.board.txt \
  --avatar-ref doki-monster/refs/doki-monster_hero_master.png \
  --ratio 9:16 --slug doki-office --avatar-dir doki-monster \
  --script "Te muestro mi oficina… contesto, agendo y dejo todo listo."
```

## Seedance prompt (handled by the script, shown for transparency)
The script fetches the verbatim baseline from
`~/.cursor/skills/seedance-2/scripts/prompt_tools.py storyboard`:
```
Use the reference storyboard to make a full animation movie from panels. Audio: Diegetic sound only — natural ambience, environmental foley, and subject-driven sound.
```
It passes the sheet as the reference image, `--duration 8 --resolution 720p
--aspect_ratio <ratio>`, waits, downloads, and strips audio. Do not hand-edit
this prompt or request specific sounds/voices — the result is muted regardless.

## Troubleshooting
- **Panels blur into one another** — add *"strong black borders between each
  panel, clearly separated frames"* to section E and regenerate the sheet.
- **Identity drift** — pass a second `--avatar-ref` (a different angle) and
  restate the DNA in section C; re-run image gen.
- **seedance `ip_detected`** — stylize any realistic human side-character to match
  the avatar's render; avoid photoreal faces in the sheet.
- **Clip feels too fast** — the whole 6-panel arc is compressed to 8s by design;
  if it must breathe, split into two broll-story calls (two 8s clips) instead of
  one long render.
- **Reuse a sheet** — pass `--sheet <NNN>_<slug>_board.png` to re-animate without
  paying for image generation again.
