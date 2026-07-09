# Storyboard — Prompt Framework

This is the canonical, project-wide storyboard methodology, kept **verbatim**
below. It is a two-phase pipeline split across two skills:

- **Phase 1 — Storyboard Image Prompt** → handled by THIS skill (`gpt-image-2`).
  Build the Phase 1 prompt for the story and generate the multi-panel sheet with
  `generate_image.py`. When a character reference sheet exists, pass it with
  `--ref` so characters stay consistent across panels.
- **Phase 2 — Cinematic Video Prompt** → handled by the **`seedance-2`** skill.
  After the storyboard is approved, that skill builds the Phase 2 cinematic video
  prompt and animates the storyboard sheet into video.

Defaults for this skill: 16:9 aspect, `--quality high` (the model's native
maximum resolution — gpt-image-2 has no resolution control, nothing is upscaled).
Adapt the framework to each story unless the user supplies a specific prompt.

The complete framework follows, kept verbatim from the source guide.

---

name: storyboard-prompt-builder
description: >
  Generate two-phase storyboard prompts from character references and a story overview — first an image prompt that produces a professional multi-panel storyboard sheet, then a cinematic video prompt that expands each panel into directed animation/live-action beats. Use this skill whenever the user wants a storyboard, a storyboard sheet, a visual story breakdown, a panel-by-panel scene layout, or asks for a "storyboard prompt." Also trigger when the user says "storyboard for," "break this story into panels," "storyboard sheet," "visual story prompt," "panel layout," or uploads character references and asks for a storyboard. Trigger when the user mentions storyboard in combination with any image or video generation tool (Nano Banana Pro, GPT Image, Midjourney, DALL-E, Seedance, Kling, Sora, Veo, Runway, Luma, Hailuo, Wan, Higgsfield, Flux). Also trigger if the user asks to turn a story idea into a visual production document or shot sheet. Works for any visual style — 3D animation, live-action, anime, 2D animation, stop-motion, editorial, comic book, or any other aesthetic.
---

# Storyboard Prompt Builder

This skill turns character references and a story overview into a two-phase prompt package:

**Phase 1 — Storyboard Image Prompt:** A single prompt that generates a professional multi-panel storyboard sheet as one composite image, with numbered panels, timecodes, shot descriptions, and scene metadata. Optimised for Nano Banana Pro and GPT Image 2.

**Phase 2 — Cinematic Video Prompt:** Once the user approves the storyboard, expand it into a full cinematic video prompt with per-shot direction, camera specs, dialogue, SFX, and emotional pacing. Designed for AI video generators.

Phase 2 is only delivered after the user confirms they're happy with the storyboard. Always ask before proceeding.

---

## Phase 1: Storyboard Image Prompt

### Step 1 — Gather inputs

You need three things. Collect whatever's missing in a single message:

1. **Character references** — uploaded images (turnarounds, portraits, concept art, photos). If the user hasn't uploaded any and the story involves characters, prompt once:
   *"Upload any character reference images you have — even a single clear portrait helps lock in consistency across panels. Otherwise I'll build the character descriptions from your story overview."*
   Ask once only. If they proceed without uploading, work from text.

2. **Story overview** — the narrative to tell. This can be anything from a one-sentence logline to a detailed beat sheet. The user might say "a robot discovers music" or provide a full scene-by-scene breakdown. Either works.

3. **Style** — the visual language. If not specified, infer from context (a story about a cute robot implies Pixar-style 3D; a noir detective implies cinematic live-action; a magical girl implies anime). When genuinely ambiguous, ask: *"What visual style — 3D animation, live-action, anime, something else?"*

**Optional inputs the user may provide:**
- **Panel count** — defaults to 15 (the standard storyboard sheet), but can be 9, 12, or 20 depending on story complexity
- **Duration** — defaults to 15 seconds, but can be adjusted (30s, 60s, etc.)
- **Aspect ratio** — defaults to 16:9, but can be 9:16 (vertical), 1:1, or 4:3
- **Target model** — Nano Banana Pro or GPT Image 2. Defaults to Nano Banana Pro. Prompt structure is similar but GPT Image 2 benefits from slightly more explicit layout instructions.

### Step 2 — Analyse character references

If character images are uploaded, extract a detailed visual inventory for each character:

- **Identifying features** — facial structure, skin tone, hair (colour, length, texture, style), age range, build, distinguishing marks (scars, freckles, tattoos)
- **Clothing and accessories** — garments, colours, materials, fit, layering, signature items
- **Design language** — proportions (realistic, stylised, chibi), silhouette readability, colour palette
- **Personality cues** — posture energy, expression tendency, how the design communicates character

Build a **compact character description** (80–150 characters per character) that serves as the "character DNA" for the prompt. This gets woven into the storyboard prompt to maintain consistency across panels.

For multiple characters, create distinct identifiers that won't blur together across panels.

### Step 3 — Break the story into beats

Decompose the story overview into the target panel count (default 15). Each beat needs:

1. **Panel number** (1–15)
2. **Timecode** (e.g., 00:00 – 01:00 for a 15-second/15-panel breakdown)
3. **Shot type** — Wide, Medium, Close-up, Low Angle, High Angle, Dynamic, Over-the-shoulder, Macro
4. **Scene description** — one sentence describing what's happening visually
5. **Action / Dialogue** — any character dialogue or specific actions (can be "None")

**Narrative arc principles:**
- **Acts structure:** Even in 15 panels, follow a three-act structure. Panels 1–3: setup. Panels 4–6: inciting incident. Panels 7–10: rising tension. Panels 11–13: climax/resolution. Panels 14–15: denouement/emotional landing.
- **Shot variety:** Vary shot types across the sequence. Never repeat the same shot type in consecutive panels. Alternate between establishing shots and intimate close-ups.
- **Emotional escalation:** Build intensity through the middle, peak around panel 10–12, then resolve. Use close-ups for emotional peaks, wide shots for context and breathing room.
- **Character consistency:** Reference character-identifying details in panels where they'd be visible at that shot size.

### Step 4 — Compose the storyboard image prompt

Write the prompt as a **single continuous block of text** inside a fenced code block. The prompt should be structured in clear sections but written as flowing natural language — not bullet points.

**Required prompt sections (in order):**

**A) Title & Format Header**
Open with the storyboard sheet concept: duration, title, panel count, grid layout, style genre.

Example opener: *"15-second animated storyboard sheet for a sci-fi adventure short film titled 'The Little Inventor & The Lost Robot'. A complete professional animation storyboard presentation page featuring 15 sequential cinematic panels arranged in a clean 3×5 grid layout."*

The grid layout depends on panel count:
- 9 panels → 3×3 grid
- 12 panels → 3×4 grid
- 15 panels → 3×5 grid (default)
- 20 panels → 4×5 grid

**B) Style Declaration**
A rich style block tailored to the user's specified or inferred visual language. This is NOT a fixed line — it adapts completely to the style.

For 3D animation: reference Pixar/DreamWorks quality, cinematic rendering, expressive character animation, warm lighting.
For live-action: reference cinematographic style, film stock look, practical lighting, grounded realism.
For anime: reference anime studio quality (Ghibli, Trigger, MAPPA depending on tone), cel-shading, dynamic line work.
For 2D animation: reference hand-drawn quality, colour palette approach, line weight, shading model.
For any other style: adapt accordingly — the style block should read like a creative director's brief for that specific aesthetic.

**C) Character Descriptions**
Detailed descriptions of each main character, pulled from uploaded references (Step 2) or built from the story overview. Include physical features, clothing, accessories, and distinguishing visual elements. Written as flowing prose, not a list.

**D) Visual Tone**
Colour grading, atmosphere, lighting quality, rendering approach. Should be consistent with the style declaration but focused on mood and technical rendering.

**E) Storyboard Layout Details**
The physical appearance of the storyboard sheet itself:
- Background material (beige storyboard paper, dark grey production board, white presentation sheet — match the tone)
- Professional film/animation production presentation style
- Numbered frames with timeline labels
- Shot descriptions and scene notes under each frame
- Clean typography
- Studio-quality aesthetic

**F) Scene Breakdown**
Each panel described as: *"Panel [N]: [Shot type] shot. [Scene description with character action, environment, and emotional beat]."*

Distribute character details across panels — mention hair and face in close-ups, full outfit in wide shots, signature accessories when they'd be visible. Don't front-load all character description into Panel 1.

Include dialogue/action notes where relevant, woven into the panel descriptions naturally.

**G) Art Direction Footer**
Technical rendering and quality cues: facial expression quality, camera angle variety, texture detail, environmental detail, atmospheric effects, composition principles. Tailor to the style.

**H) Rendering & Format Footer**
Final technical specs: render quality cues, aspect ratio, format declaration ("professional storyboard sheet"), quality tier ("masterpiece quality" / "production-ready").

### Step 5 — Deliver the storyboard prompt

Output the complete prompt in a **single fenced code block**. The user should be able to copy it directly into Nano Banana Pro or GPT Image 2.

Below the code block, add a **companion note** (3–5 sentences) covering:
- Style choices made for anything the user didn't specify
- Which character details were pulled from references vs inferred
- One or two refinement suggestions (e.g., "If the panels blend together, try adding 'strong black borders between each panel' to the layout section")
- A reminder: *"When you're happy with the storyboard, let me know and I'll generate the cinematic video prompt to match."*

### Prompt length guidance

Storyboard image prompts run longer than single-image prompts because they encode both the layout structure AND 9–20 individual scene descriptions. Target ranges:

- **9 panels:** 800–1,200 words
- **12 panels:** 1,000–1,500 words
- **15 panels (default):** 1,200–1,800 words
- **20 panels:** 1,500–2,000 words

Don't pad, but don't compress at the expense of panel clarity. Every panel description needs enough detail for the model to differentiate it from adjacent panels.

---

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

---

## Handling Variations

**User provides a full beat sheet:** Skip the story decomposition — map their beats directly to panels. Adjust panel count to match their beat count if it differs from 15.

**User provides only a logline:** Decompose it into a full beat sheet using three-act structure before building panels. Briefly show the user the beat breakdown before generating the prompt, so they can redirect.

**User wants to iterate on specific panels:** Allow targeted edits — regenerate just the affected panel descriptions without rebuilding the entire prompt.

**User wants a different panel count:** Adjust the grid layout and redistribute the narrative beats. Fewer panels (9) means each beat carries more narrative weight. More panels (20) allows for more transitional moments and reaction shots.

**User wants vertical format (9:16):** Flip the grid — a 15-panel vertical storyboard uses a 5×3 grid (5 rows, 3 columns) instead of 3×5. Adjust the layout description accordingly.

**User specifies a target video tool:** Tailor the video prompt's technical language to the tool's strengths. Seedance excels at character animation and lip sync. Kling handles dynamic camera. Sora handles cinematic composition. Veo handles long coherent sequences. Adjust camera direction complexity and shot duration ranges based on the tool's capabilities.

**Style is mixed or hybrid:** Some stories blend styles (e.g., "anime-influenced but rendered in 3D" or "live-action with animated elements"). Build the style block to explicitly call out the hybrid nature and establish which elements follow which visual rules.

---

## Example: Minimal Input

**User says:** "A lonely astronaut finds a flower growing on Mars" + uploads a character reference of an astronaut in a worn orange spacesuit.

**Phase 1 output would include:**

The storyboard prompt would:
- Open with: "15-second cinematic storyboard sheet for a sci-fi drama short film titled 'Bloom.' A complete professional storyboard presentation page featuring 15 sequential cinematic panels arranged in a clean 3×5 grid layout."
- Style: cinematic photorealism, Interstellar + The Martian aesthetic, desaturated Martian palette with isolated green accent
- Character: describe the astronaut from the uploaded reference — worn orange suit, specific helmet design, visor details, patches, physical build
- Panels: setup on barren Mars → discovery of green sprout → emotional close-up → astronaut kneels → careful examination → decides to protect it → builds shelter → tends to it → flower blooms → astronaut removes helmet → breathes → tears → wide shot of flower against vast landscape → astronaut sits beside it → final wide: tiny green dot on red planet
- Art direction: harsh Martian sunlight, volumetric dust, emotional isolation composition, single colour accent (green) against monochrome environment

Then Phase 2 would expand each panel into a full cinematic shot with camera, SFX, and emotional direction.
