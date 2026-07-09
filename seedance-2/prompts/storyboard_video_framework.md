# Storyboard → Video — Prompt Framework

This skill (`seedance-2`) owns **Phase 2** of the project's storyboard
methodology — turning an approved storyboard into a cinematic video. **Phase 1**
(building the multi-panel storyboard *image*) is the `gpt-image-2` skill's job and
is not repeated here, since Seedance doesn't generate the sheet.

## Which video prompt to use

- **Phase 2 — per-shot cinematic video prompt (preferred).** Use this **only when
  the referenced storyboard was generated with the guide's Phase 1** — i.e. you
  have the panel breakdown (beats, timecodes, shot types, scene descriptions) to
  expand into shots. Author the prompt by following **Phase 2** below: a
  production header, one timed shot per panel, ending with the fixed `Audio:`
  line. Pass the storyboard sheet as a reference image (reference-image role /
  `[Image1]`) and set `duration` to the storyboard's length.
- **Simple one-liner (fallback).** Use this for **any other storyboard sheet**
  (one not built via Phase 1, so there is no structured breakdown to expand).
  `scripts/prompt_tools.py storyboard [--panels 4-6]` prints it.

Both paths end with the guide's fixed audio line, exactly:
`Audio: Diegetic sound only — natural ambience, environmental foley, and subject-driven sound.`

### Simple one-liner (fallback) — project-specific, not part of the guide

Full board (all panels):

```
Use the reference storyboard to make a full animation movie from panels. Audio: Diegetic sound only — natural ambience, environmental foley, and subject-driven sound.
```

A specific range of panels (e.g. panels 4 to 6):

```
Use the reference storyboard to make a full animation movie from panels 4 to 6. Audio: Diegetic sound only — natural ambience, environmental foley, and subject-driven sound.
```

The storyboard sheet is supplied as a reference image, so the model has the
panels to work from. Adapt the panel numbers to the requested range.

---

The guide's **Phase 2** section follows, kept **verbatim** from the source.

## Phase 2: Cinematic Video Prompt

Only proceed to this phase when the user explicitly confirms they're happy with the storyboard. Ask: *"Happy with the storyboard? I'll build the video prompt next."*

### Step 1 — Map storyboard panels to video shots

Each storyboard panel becomes a timed video shot. The total duration matches the storyboard's specified length (default 15 seconds). Each shot gets a timecode range matching the panel's position.

For a 15-panel, 15-second storyboard: each shot is 1 second (Panel 1 = [0s – 1s], Panel 2 = [1s – 2s], etc.).

For longer durations or fewer panels, distribute time intelligently:
- Establishing shots and emotional beats get more time (2–3 seconds)
- Quick action beats and transitions get less (1 second)
- The total must equal the specified duration

### Step 2 — Expand each panel into cinematic direction

For each shot, provide:

1. **Timecode** — [Xs – Ys] format
2. **Shot label** — "SHOT N — [SCENE NAME]" in caps
3. **Shot type and camera** — shot size, angle, camera movement described in cinematic language
4. **Scene direction** — what's happening, expanded from the storyboard panel with more cinematic detail: blocking, staging, environmental action, character acting beats
5. **Dialogue** — any character lines, formatted as Character: "Line"
6. **SFX** — sound effects and ambient audio for the shot
7. **Camera direction** — specific camera movement described as a verb phrase (slow dolly-in, handheld tracking, orbit, push-in, pull-out, static, etc.)

### Step 3 — Add production headers and footers

**Header block (before the shots):**
- Reference to character sheet/storyboard image as the visual keyframe reference
- Instruction to follow the exact beat progression, framing structure, and emotional pacing from the storyboard
- Character consistency mandate: list each character's identifying features and demand they remain identical across every shot
- Style block: expanded from the storyboard's style declaration into cinematic motion terms (add animation principles like squash & stretch for animation styles, or handheld naturalism for live-action)
- Focus block: emotional readability, visual storytelling priorities, motion quality, continuity

**Footer:** None needed — the prompt ends with the final shot.

### Step 4 — Adapt to style

The video prompt's language shifts with the visual style:

**3D Animation / Pixar-style:**
- Reference animation principles: squash & stretch, anticipation, follow-through, exaggerated expressions
- Camera language: cinematic dolly, orbit, snap zoom, rack focus
- Lighting: warm practicals, volumetric, neon accents, global illumination
- Acting: expressive character animation, readable silhouettes, comedic timing

**Live-action / Cinematic:**
- Reference film grammar: handheld, Steadicam, crane, Dutch angle
- Lighting: practical sources, naturalistic, motivated lighting
- Acting: subtle performance cues, micro-expressions, body language
- Sound: diegetic audio, environmental foley, naturalistic ambience

**Anime:**
- Reference anime conventions: speed lines, impact frames, limited animation on holds, sakuga for action peaks
- Camera: dramatic snap zooms, static wide holds, rapid cuts
- Effects: particle effects, light bloom, dramatic shadows, wind animation
- Acting: anime expression language (sweat drop, sparkle eyes, dramatic reaction takes)

**2D Animation / Hand-drawn:**
- Reference traditional animation: smears, multiples, held poses with moving holds
- Line quality: consistent weight, boil/texture on lines
- Background: painterly environments, parallax layers
- Movement: fluid character animation, secondary motion on hair/clothing

### Step 5 — Compose and deliver the video prompt

Output the complete video prompt in a **single fenced code block**. Structure:

```
[Production header — reference image, consistency mandate, style block, focus block]

[Shot 1 — timecode, label, full direction]

[Shot 2 — timecode, label, full direction]

...

[Final shot — timecode, label, full direction]

Audio: Diegetic sound only — natural ambience, environmental foley, and subject-driven sound.
```

Each shot is separated by a blank line. The header sits above all shots, separated by a blank line.

**Always end the video prompt with the fixed Audio metadata line** after a blank line following the final shot:

`Audio: Diegetic sound only — natural ambience, environmental foley, and subject-driven sound.`

This line is non-negotiable and appears in every video prompt regardless of style. Individual shots still include their own SFX notes for specific sound design cues, but this closing line establishes the overall audio philosophy for the generation.

Below the code block, add a **brief companion note** (3–5 sentences) covering:
- Pacing choices: where the edit breathes vs where it accelerates
- Any shots that might need adjustment if the first generation doesn't land
- Suggestions for audio/music pairing if relevant

### Video prompt length guidance

Video prompts are longer than image prompts because they encode temporal direction. Target ranges:

- **9 shots / 15 seconds:** 800–1,200 words
- **15 shots / 15 seconds:** 1,200–2,000 words
- **15 shots / 30 seconds:** 1,500–2,500 words
- **20 shots / 60 seconds:** 2,000–3,500 words
