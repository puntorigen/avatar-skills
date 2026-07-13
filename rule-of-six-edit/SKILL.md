---
name: rule-of-six-edit
description: Evaluate and plan the CUTS / editing of a short-form video / reel using Walter Murch's "Rule of Six" — the priority hierarchy that defines an ideal cut: Emotion (51%) > Story (23%) > Rhythm (10%) > Eye-trace (7%) > 2D plane / photographic grammar (5%) > 3D spatial continuity (4%), with one doctrine — when a cut can't satisfy all six, sacrifice from the BOTTOM up and never sacrifice emotion. Produces a cut sheet (JSON), a human edit sheet (Markdown) and plain director notes (txt), and can seed itself from an avatar-reel-composer storyboard.json so every scene boundary is scored. This is the editing companion to viral-video-script (which writes the words). Use when deciding where/when to cut, evaluating or critiquing an edit, planning scene boundaries / pacing / transitions for a reel, building or reviewing a storyboard's cuts, or when the user mentions "edición", "montaje", "cortes", "dónde cortar", "ritmo", "eye-trace", "rule of six", "Walter Murch", or editing a virtual-avatar reel.
---

# Rule of Six — reel edit guide

Decide the **cuts** of a short-form video (reel / TikTok / Short) so every edit
earns its place. The framework is Walter Murch's **Rule of Six** (from *In the
Blink of an Eye*): not six rules, but a **hierarchy of six criteria** that ranks
what makes an ideal cut. A perfect cut satisfies all six; when you can't have
them all, the ones at the **top** win.

Where [`viral-video-script`](../viral-video-script/SKILL.md) writes the **words**
(the beat sheet → narration), this skill plans the **montage** — where, when and
why to cut. Its outputs annotate the cuts of a reel this repo assembles with
[`avatar-reel-composer`](../avatar-reel-composer/SKILL.md) (hard cuts at every
scene boundary).

## The hierarchy (six criteria, top = most important)

| # | Criterion | Weight | The question the cut must answer |
|---|---|---|---|
| 1 | **Emotion** | 51% | Does the cut convey / evoke the feeling the moment needs? Is this what the viewer will *remember*? |
| 2 | **Story** | 23% | Does the cut advance the plot / develop character / clarify the theme — does it deliver new info? |
| 3 | **Rhythm** | 10% | Is the cut at the *right moment*? Tempo, pacing, momentum, flow — does it feel satisfying (cut on the beat / the breath)? |
| 4 | **Eye-trace** | 7% | Does it respect where the viewer's eye is? Is the point of interest carried to the same part of the frame across the cut? |
| 5 | **2D plane of screen** | 5% | Photographic grammar: rule of thirds, eye-lines, the 180° line of action, screen direction. |
| 6 | **3D space of action** | 4% | Spatial continuity: the real geography of where people / props are in the space. |

**Emotion + Story = 74%.** Nail the top two and the cut mostly works; the bottom
four are the *details* that make it invisible. Viewers forget a technically
perfect, well-paced scene in months — they remember how it made them **feel**.

## The one doctrine: sacrifice from the bottom up

An ideal cut satisfies all six. When it can't (they conflict), **give them up
from the bottom** — 3D continuity first, then 2D grammar, then eye-trace, then
rhythm — and **never sacrifice emotion**, almost never story.

- The bottom criteria break constantly and *go unnoticed*: a viewer can't easily
  gauge 3D space on a flat screen, so as long as continuity isn't *egregiously*
  bad they won't notice. Films break 2D grammar (eye-lines, the 180° line) **on
  purpose** to create unease or an emotional jolt.
- So: if a cut lands the emotion but "breaks" the line of action — **take the
  cut**. If a spatially perfect cut kills the feeling — **throw it away**.

> North star: every cut is made to **convey and evoke emotion**. The way films
> move us is what makes them great; the rest is just the details we need to get
> there.

## Why cuts work — and where to cut

A cut is a **link between two focuses of attention**. It works because it mirrors
a **blink**: we blink when a thought is fully formed, to *separate and punctuate*
one idea from the next. A shot is an idea; the cut is the blink that ends it. So
the editor "**blinks for the viewer**" — cut where a thought **completes**, not
mid-thought. In a reel that's the end of a complete idea / on the breath / at
punctuation (exactly why `avatar-reel-composer` snaps every cut to a silence).
Find that beat and the whole audience blinks together.

Placement heuristics that follow:
- **Cut on the blink** — at thought completion, never mid-idea. (#1/#3)
- **Don't cut Dragnet-style** — mechanically after every single line reads like a
  machine, not a mind; honor where thoughts actually end. (#3)
- **Avoid the "2-yard jump"** — never cut between two *near-identical* shots (it's
  jarring, like a beehive moved a few yards: too similar to reorient). Change the
  angle by **≥30°** or the framing/zoom — this is the alternate-angle+zoom rule. (#4/#5)
- **Juxtaposition makes meaning** (the Kuleshov effect) — a B-roll placed next to a
  line creates a *third* meaning neither shot has alone; order the shots so the
  cut itself says what you mean. (#2)
- **Split the edit (L/J cut)** — let the soundtrack (the running voice, or a music
  phrase) spill **across** the picture cut; don't stop picture *and* sound on the
  same frame unless you *want* the jolt. (#1/#3)
- **Let the music do the cut** — open on an **intro**, hand off on an **outro**,
  **pivot** on a variation, and drop a hard **beat on the punch**; pick the track's
  section for the emotional job. (#1/#3)

Top-three are **bound together** (emotion + story + rhythm ≈ 84%): chase the
emotion of a cut and it tends to pull the story and rhythm along. And getting the
top items right **obscures** flaws in the lower ones — but never the reverse.

## Sound & the cut — the soundtrack rides its own track

A cut is **not one event on one track**. Picture, voice and music are **three
separate streams**, and *where the soundtrack changes relative to the picture cut*
is itself an editing choice — one that lives up at **Emotion (#1)** and **Rhythm
(#3)** (rhythm is "best exemplified by cutting to the beat of music"; emotion is
the editor's north star and music is its strongest single lever). Beginners fight
this: a timeline welds each clip's video+audio into one movable block, so they
**start and stop picture and sound on the same frame**. Don't. Treat the tracks as
independent elements that move on their own and only **occasionally meet at a sync
point** — most of editing is that sleight of hand: *change the picture while the
soundtrack holds, or change the soundtrack while the picture holds*, rarely both at
once. That overlap is the **split edit** (J-cut: sound leads the picture; L-cut:
sound lingers past it).

**Look at the music, don't just listen.** After choosing a track that carries the
right feeling, read its **structure** (the waveform) and place the right *section*
against the cut:

- **Intro** — crafted to ease a listener in → use it to **open** (a hook, a scene entrance).
- **Outro / ending** — a natural resolution → use it to **hand off** across a scene change.
- **Variation / shift** — a dynamic change mid-track (verse→chorus, quiet↔loud, visible in the waveform) → use it to **pivot the emotion**.

Three soundtrack-vs-cut moves (each is chosen for the feeling, so each serves #1/#3):

1. **Gentle handoff** *(outro, offset from the cut)* — start a musical resolution
   running *before / through* the picture cut. It "picks the viewer up in one scene
   and gently sets them down in the next." Music transition and picture cut
   deliberately **do not** land together — the score carries them over. (Film/TV's
   most common transition; listen for it in any score.)
2. **Emotional shift** *(variation, on the cut)* — land the frame where the music
   **shifts** exactly on the picture cut, so the *same* track carries into the next
   scene with a new feeling (lift or settle: fast→mellow, loud→quiet).
3. **Hard-cut punch** *(intro beat, on the cut)* — the exception where sound and
   picture **do** hit together: silence, then the music's first beat lands on the
   first frame of the new scene. Punchy, powerful, energetic — spend it on the one
   moment that earns it.

> Source: Austen Menges, *How a Pro Video Editor Uses Music* — the working-editor's
> companion to Murch. The through-line is the same: pick the sound for the **emotion**,
> then let the tracks move independently so the cut feels invisible.

## How it maps to a virtual-avatar reel

In this repo a reel is a chain of **hard cuts** at scene boundaries
(talking-head ⇄ B-roll, angle/zoom changes). Treat **every boundary as a cut**
and score it against the hierarchy:

- **Emotion (1):** does cutting *here* serve the feeling of the narration at this
  instant (a reveal, a punch, a breath of relief)? This is what picks the cut.
- **Story (2):** the cut should reveal **new info** — a new idea, a B-roll that
  shows what's being said, a reframe that re-focuses. If a shot delivers nothing
  new, let it hit the cutting-room floor (drop or shorten the scene).
- **Rhythm (3):** cut on the **breath / beat**, never let a shot linger. Mirrors
  the pacing rules `avatar-reel-composer` already enforces (hook ~2–3s, every
  shot ≤ ~6s, alternate angle+zoom on back-to-back talking-heads).
- **Eye-trace (4):** keep the subject's face / the point of interest in a
  consistent part of the 9:16 frame across a cut (talking-head → B-roll → back)
  so the eye doesn't hunt — this is what makes match cuts and montages glide.
- **2D plane (5):** framing / rule-of-thirds / eye-line direction between angle
  crops; keep screen direction unless you're breaking it deliberately.
- **3D space (6):** spatial continuity — least important for a talking-head reel;
  the first thing to sacrifice.
- **Sound (the axis across #1/#3):** our reel already runs **one continuous
  narration** that keeps talking *across* every B-roll / angle cut — a built-in
  **split edit**, so exploit it: cut the *picture* mid-thought over the running
  voice instead of resting picture **and** voice together at every sentence end.
  The music **bed** now follows a **volume envelope** when you give it a plan
  (`finish_reel.py`), so it does real editing work: mark in the cut sheet **where**
  each musical move belongs — an **intro beat** on the hook punch, a **variation**
  at the reel's emotional pivot, an **outro** under the CTA / close — and hand the
  cut sheet straight to the composer with `finish_reel.py --music-from-cutsheet
  <slug>.cutsheet.json` (it maps each cut's `sound` note to a move at that scene
  boundary), or author the precise `finish.music_plan`. SFX stingers + the golden
  flash already land *on* B-roll cuts (the punch move); keep those for the beats
  that earn them.

## Inputs to gather (ask only what's missing)

| Input | Needed for | Example |
|---|---|---|
| The reel's script / narration | the emotional + story spine | from `viral-video-script` |
| `storyboard.json` (optional) | seed one cut per scene boundary | `avatar-reel-composer` output |
| Emotional throughline | criterion #1 across the whole reel | "unease → recognition → relief" |
| Soundtrack / music | the sound axis (#1/#3) | narration voice-over (always) + optional music bed: mood + where it **enters / shifts / resolves** |
| Platform / length | rhythm budget | `reels` \| `tiktok` \| `shorts`, ~30s |
| Language | the notes' language | `es` \| `en` (default: match the user) |

If there's no storyboard yet, scaffold the cuts from scratch and hand the result
back as the plan for building one.

## Workflow

```
- [ ] 1. Gather inputs. If a storyboard.json exists, seed from it; else set cut count.
- [ ] 2. Scaffold the cut sheet JSON.
- [ ] 3. Fill every cut: emotion + story first, then rhythm/eye-trace/2D/3D. Mark sacrifices bottom-up.
- [ ] 4. Validate against the hierarchy. Fix every FAIL, weigh each WARN.
- [ ] 5. Render the edit sheet (.md) + director notes (.txt).
- [ ] 6. Hand off: build/adjust the storyboard, or use as an edit-review rubric.
```

**Step 2 — scaffold** (writes `<out>/<slug>.cutsheet.json`):

```bash
# from scratch (N cuts)
python3 .cursor/skills/rule-of-six-edit/scripts/scaffold.py my-reel \
  --cuts 6 --language es --out cuts_out/

# or seed one cut per scene boundary from a reel storyboard
python3 .cursor/skills/rule-of-six-edit/scripts/scaffold.py my-reel \
  --from-storyboard lolo/reels/001_my-reel/storyboard.json --language es --out cuts_out/
```

**Step 3 — write.** Edit the JSON. The hard rules the validator enforces:
- Every cut has a non-empty `emotion` (#1) and `story` (#2) — never TODO/blank.
- `sacrifices` never contains `emotion` or `story`, and is a valid **bottom-up
  suffix**: you may drop `space_3d`, then `plane_2d`, then `eye_trace`, then
  `rhythm` — in that order, no gaps (can't sacrifice eye-trace while keeping 3D).
- Each of the six criteria per cut is either **addressed** (a note) or listed in
  `sacrifices` — nothing left unconsidered.
- `emotional_throughline` is set (the feeling arc of the whole reel).

Optionally set a per-cut **`sound`** note (the soundtrack move — split vs hard sync,
which music edit) and a top-level **`soundtrack`** intent (the music bed's mood +
where it enters / shifts / resolves against the cuts). Neither is validated, but both
flow into the edit sheet + director notes — and `avatar-reel-composer`'s
`finish_reel.py --music-from-cutsheet <slug>.cutsheet.json` reads the `sound` notes
directly to build the music bed's **volume envelope** (entrance / lift / settle /
duck / resolve at each cut). So the `sound` axis is now *audible*, not just advisory.

**Step 4 — validate** (re-run until no FAIL; treat WARN as review notes):

```bash
python3 .cursor/skills/rule-of-six-edit/scripts/check_cuts.py cuts_out/my-reel.cutsheet.json
```

**Step 5 — render** (writes `<slug>.cutsheet.md` + `<slug>.cutnotes.txt` next to the JSON):

```bash
python3 .cursor/skills/rule-of-six-edit/scripts/render_cuts.py cuts_out/my-reel.cutsheet.json
```

## Writing each cut (per criterion)

Fill top-down; the top two decide the cut, the rest refine it.

- **emotion (#1):** the feeling this cut serves or evokes *right now* (e.g. "the
  turn from doubt to relief"). If you can't name it, the cut isn't motivated.
- **story (#2):** the new information the cut delivers (a reveal, a visual proof,
  a reframe). No new info → drop or shorten the shot.
- **rhythm (#3):** *why here* — on the breath / a comma / the beat; a pace note
  (keep it snappy, ≤ ~6s, hook ~2–3s).
- **eye_trace (#4):** where the eye is before and after; is the point of interest
  carried to the same region of the 9:16 frame?
- **plane_2d (#5):** framing / eye-line / 180° line / screen direction across the
  cut (or the intentional break).
- **space_3d (#6):** spatial continuity note (usually the first to sacrifice).
- **sound (extra axis, not one of the six weighted criteria — serves #1/#3):** the
  soundtrack move at this cut — a **split** (voice / music runs across the cut) vs a
  **hard sync** (beat on the frame); and which music edit if a bed is in play
  (handoff outro / variation shift / intro punch). Optional but high-leverage; leave
  blank for a pure picture cut.
- **sacrifices:** the criteria this cut deliberately gives up (bottom-up only).

## Output files

```
<slug>.cutsheet.json  # the cut sheet (source of truth; edit this)
<slug>.cutsheet.md    # human edit sheet: per-cut criteria table, sacrifices, coverage score
<slug>.cutnotes.txt   # plain director notes per cut (keep/sacrifice) for whoever assembles/reviews
```

## Handoff into this repo's pipeline

- **Building a reel:** use the filled cut sheet to write / adjust the
  `avatar-reel-composer` `storyboard.json` — set scene boundaries where a cut is
  emotionally + story-motivated, pick angle/zoom to honor eye-trace + 2D, and
  keep the rhythm (short hook, no lingering shots). Then compose:
  ```bash
  python3 .cursor/skills/avatar-reel-composer/scripts/compose_reel.py storyboard.json --finish
  ```
- **Reviewing an edit:** run it as a rubric — score each existing cut and flag any
  that lead with 3D/2D correctness at the expense of emotion or story. Two review
  laws from Murch: **judge only what's on screen** (not your intent or effort —
  what will the viewer actually see?), and when a cut *feels* wrong the cause is
  usually **upstream** — a setup the viewer needed was missing earlier, so fix the
  setup instead of deleting the flagged shot.

For the words that ride over these cuts, see
[`viral-video-script`](../viral-video-script/SKILL.md). For the cutaways a
Story-beat calls for, see [`broll-generator`](../broll-generator/SKILL.md) /
[`broll-finder`](../broll-finder/SKILL.md). For the music bed the **sound** axis
plans, see [`bg-music-hq`](../bg-music-hq/SKILL.md) and
[`avatar-reel-composer`](../avatar-reel-composer/SKILL.md) — its `finish_reel.py`
turns this cut sheet's `sound`/`soundtrack` into the bed's volume envelope
(`--music-from-cutsheet`, `finish.music_plan`, or `--music-structure auto`).

## Anti-patterns

1. **Cutting for correctness, not feeling** — a spatially perfect cut that kills
   the emotion. Emotion is 51%; take the emotional cut. (#1)
2. **Keeping a shot that adds nothing** — every cut must deliver new info; let
   dead footage hit the cutting-room floor. (#2)
3. **Lingering / no cuts** — a shot that overstays kills rhythm and attention. (#3)
4. **Sacrificing from the top** — never give up emotion; almost never story. Give
   up 3D/2D first. (doctrine)
5. **Making the eye hunt** — the subject jumps across the frame at a cut, adding
   friction the viewer feels but can't name. (#4)
6. **Treating the 180° line as sacred** — it's a low-priority rule you may break
   *on purpose* for unease; just don't break it by accident. (#5)
7. **Cutting mid-thought / Dragnet-style** — cutting mechanically or in the middle
   of an idea instead of on the blink (where the thought completes). (#3)
8. **The 2-yard jump** — cutting between two near-identical shots; change the angle
   ≥30° or the framing/zoom so the eye reorients. (#4/#5)
9. **The beginner's block — welding sound to picture** — starting/stopping the voice
   or music on the *same* frame as every picture cut. Use split edits: let the
   soundtrack run **across** the cut, meeting the picture only where you mean it. (#1/#3)
10. **Wallpaper music** — a bed that just plays under everything, doing no editing
    work. Choose the track's *section* and mark where it **enters / shifts /
    resolves** against the cuts (intro on the hook, variation on the pivot, outro on
    the close). (#1/#3)

## Additional resources

- The psychology / craft behind each criterion + Murch's reasoning: [reference.md](reference.md)
- Full worked cut sheets (EN + ES): [examples.md](examples.md)
