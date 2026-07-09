# Avatar Camera B-roll — reference

Prompt internals for the action frame, the `prunaai/p-video-avatar` schema, the audio-driven
workflow, and the seedance-2 start+end alternative.

## prunaai/p-video-avatar — input schema (verified)

The **same Pruna talking-avatar / lip-sync model our talking-heads use** — driven here from one
action start frame so the avatar's look is identical across talking and action shots.

| Input | Type | Default | Notes |
|---|---|---|---|
| `image` | string(file) | — | **required** — the action **start frame** (first frame). Output ratio follows it (feed 9:16). |
| `audio` | string(file) | — | Uploaded audio that **drives** the avatar: lip-sync (when the mouth is visible) **and sets the clip length**. Pass the beat's narration slice. Used instead of `voice_script` when present. |
| `video_prompt` | string | `The person is talking.` | **The ACTION** — "how the person appears/behaves while speaking". Put the gesture here: `"takes a book from a shelf while talking"`. |
| `negative_prompt` | string | `` (off when empty) | What to keep OUT (extra people, distorted hands, text/watermark, scene cuts…). The script sends an action-broll preset by default. |
| `strength_negative_prompt` | number | 0.5 | Negative-prompt strength (experimental). |
| `resolution` | enum | 720p | 720p / 1080p. |
| `disable_prompt_upsampling` | bool | false | When true, use `video_prompt` verbatim (skip auto visual-prompt enhancement). |
| `voice_script` | string | `` | Words to speak via the model's **built-in generic TTS** when **no `audio`** is given. Generic voice — **not** the avatar's clone. Scouting only. |
| `voice` / `voice_language` / `voice_prompt` | enum/str | Zephyr / English (US) / "Say the following." | Built-in-TTS voice settings (only matter with `voice_script`). |
| `seed` | int | — | Reproducible generation. |
| `disable_safety_filter` | bool | true | Skips prompt/image safety check. |

**No `last_frame_image`, no `duration`, no `fps`** — the audio sets the length, and there is no
target-frame steering (that's what the seedance-2 alternative below is for). Strengths: talking
avatars / lip-sync, close-up subjects, **coherent handling of foreground objects** (a held book
stays solid — unlike plain `p-video`, which can flip/warp it). Keep ONE shot, simple action.

## The action-frame prompt (build_frame.py)

Assembled from the scene profile + the action, in four locked blocks:

1. **Premise** — "another real frame of the same recording, but an ACTION shot, not a talking
   head" (kills the model's instinct to make a centered portrait).
2. **PRESERVE EXACTLY** — `subject` + `wardrobe` + `scene` + `light` from the profile, plus
   realistic-detail / no-text rules.
3. **FACE** — `--face out|partial|visible` controls how much face is in frame.
4. **THE SHOT** — your `--action` text (the composition) + a framing anchor.

`--face` presets for this skill:
- `visible` — face in frame doing the action → **the avatar lip-syncs** the beat (the sweet spot).
- `partial` — over-the-shoulder / chin/side; focus on the action, partial lip-sync.
- `out` — true hands-only POV / no face → **don't drive it with `p-video-avatar`** (no face to
  anchor). Use the seedance-2 start+end recipe instead.

Master at **2:3** (native, clean) → `--crop916` center-crops a **9:16** reel frame. Feed the 9:16
frame to the animator.

## Audio-driven animation (the standard path)

`p-video-avatar` is audio-driven. Pass the **exact narration slice** for the beat as `--audio`:
- The avatar **lip-syncs** to it where the mouth is visible, and the **clip length follows the
  audio** (so it matches the reel slot — no freeze, the composer trims).
- We still **mute** the output (ffmpeg `-an`); `avatar-reel-composer` re-lays the same master slice
  → in sync, no double audio.
- Get the per-beat slices from the reel's `scenes/chunk_sN.mp3` (or cut `narration.mp3`).
- **Put the ACTION in `--video-prompt`, short + positive.** Lip-sync is automatic from the audio,
  but if the prompt doesn't name a gesture the avatar will *just talk*. One short clause, positive,
  no static/negative phrasing: `"takes a book from a shelf and looks at it while talking"`.

## Worked example — El Antiguo, "takes a book from the shelf" (verified)

Scene profile: `antiguo/scene.json` (indigo linen robe, candlelit reading room).

```bash
# 1) action start frame — face visible (so it lip-syncs), three-quarter, upper body
build_frame.py --ref antiguo/refs/antiguo_hero.png --scene-file antiguo/scene.json \
  --face visible --crop916 -o antiguo/broll/camera/_frames/ --slug antiguo_shelf_reach \
  --action "three-quarter shot of the old mystic standing at his bookshelf, reaching up to \
pull a thick leather-bound tome from an upper shelf; upper body visible, indigo robe, candlelight"

# 2) animate — action in --video-prompt (short, positive), driven by the beat slice
make_broll_camera.py --avatar-dir antiguo \
  --image antiguo/broll/camera/_frames/antiguo_shelf_reach_916.png \
  --audio antiguo/reels/NNN_slug/scenes/chunk_s4.mp3 \
  --action "takes a book from a shelf and looks at it while talking" \
  --slug antiguo-shelf-book
```
Result (clip `007`): natural reach → take → lower → read; the held book stays **coherent** (no
flip/warp), identity matches the talking-heads, lip-sync to the beat, length = the audio (5.58s).

## Alternative — seedance-2 start+end (face-free or precise object move)

When there's **no face to anchor** (hands-only POV, back-to-camera) or you need an **exact start
AND end pose** for an object move, interpolate two real frames with **seedance-2** (via the
`higgsfield` CLI, or the seedance-2 skill / Higgsfield MCP). It keeps the object coherent because
it morphs between two given poses rather than free-generating motion.

```bash
# preflight cost, then create (9:16, 720p). --start-image/--end-image auto-upload local files.
higgsfield generate cost   seedance_2_0 --prompt "<action>" \
  --start-image start_916.png --end-image end_916.png --aspect_ratio 9:16 --resolution 720p --duration 6
higgsfield generate create seedance_2_0 --prompt "<action>" \
  --start-image start_916.png --end-image end_916.png --aspect_ratio 9:16 --resolution 720p \
  --duration 6 --wait
```
- Build both frames with `build_frame.py` (same identity), or extract a plausible end frame from a
  first pass. seedance generates audio natively → **mute** the result for the broll (ffmpeg `-an`).
- Cost ≈ 4.5 credits/sec at 720p (the shelf test cost 27 credits for 6s). Always preflight.

## Recipes / lessons

- **Action in `--video-prompt`, short + positive.** One clause, name what the avatar DOES; drop
  scene dressing/qualifiers; never write "hold still / static / no camera move" (confuses it).
  Lip-sync comes from the audio, not the prompt — but you must still name the gesture or it only talks.
- **Audio is the driver.** Length follows the audio; pass the exact beat slice so the clip matches
  its slot (no-freeze project rule). Lip-sync only shows where the mouth is visible — fine, the
  action is the point.
- **Held objects are coherent now.** `p-video-avatar` holds a book/prop far better than `p-video`
  (which flipped the book in the old `006`). A heavy/complex object move is still safer as a
  seedance-2 start+end interpolation.
- **Face-free POV → seedance-2, not this script.** A talking-avatar model with no face hallucinates;
  use start+end interpolation, or keep the face partially in frame.
- **Identity is locked** by using the same model as the talking-heads + a scene-profile frame; the
  start frame controls the look far more than the action prompt does.
- **9:16 in, 9:16 out.** Crop the start frame to 9:16 first.
- **Muted:** ffmpeg `-an`; the single master narration is laid on by avatar-reel-composer.
