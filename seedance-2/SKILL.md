---
name: seedance-2
description: Generate video with ByteDance Seedance 2.0 via the Higgsfield MCP (generate_video, model seedance_2_0). A unified multimodal model that turns a text prompt plus reference images, video clips, and audio into audio-synced video up to 15s, with strong physics, multi-shot camera planning, and lip-sync. Use to generate video from text, animate a still image (image-to-video), do motion transfer / character consistency / style reference / audio-driven generation from references, or animate a storyboard sheet into a movie. Reframes prompts with [Image1]/[Video1]/[Audio1] tokens for references. Trigger when the user mentions seedance, seedance-2, seedance 2.0, generating a video (of a given duration/resolution/ratio), animating a storyboard, or video with image/video/audio references.
---

# Seedance 2.0 (via Higgsfield MCP)

Generate audio-synced video with **ByteDance Seedance 2.0** through the **Higgsfield MCP** server (`generate_video`, model `seedance_2_0`). It accepts a text prompt plus reference **images, video clips, and audio**, producing video + synchronized audio up to **15 seconds**, with strong physics and multi-shot camera planning.

> **Backend = Higgsfield MCP, not Replicate.** Generation runs through MCP tools that the agent calls directly (`generate_video`, `media_upload`, `media_confirm`, `job_status`). There is no API key to manage and no Python SDK — auth and billing are handled by the Higgsfield MCP account (credits). The only local script is a text-only prompt helper.

## Prerequisites

- The **`plugin-higgsfield-higgsfield` MCP server** must be enabled (it is, in this workspace).
- The account needs credits. Check with the `balance` tool. Seedance costs **~4.5 credits/sec at 720p** (see cost table below).
- Read MCP tool schemas under `mcps/plugin-higgsfield-higgsfield/tools/` before calling if unsure.

## Defaults & cost

`duration 8`, `aspect_ratio 16:9`, `resolution 720p`, `count 1`.

| Resolution | Credits/sec | 8s | 15s |
|---|---|---|---|
| `480p` | 3 | 24 | 45 |
| **`720p` (default, recommended)** | **4.5** | **36** | **67.5** |
| `1080p` | 9 | 72 | 135 |

**720p is the recommended default** — great for almost everything and **half the cost of 1080p**. Only pass `resolution: "1080p"` when the user explicitly wants a final hero render. Cost scales linearly with duration. **Always preflight with `get_cost: true` and tell the user the credit cost before submitting** a real job.

## Workflow (what the agent does)

### 1. (Optional) Verify constraints + preflight cost
- `models_explore` (`action: "get"`, `model_id: "seedance_2_0"`) → authoritative `durations`, `aspect_ratios`, `parameters` (incl. `resolution`), and `medias[].roles` (the exact role strings for references). Do this when using references so you use the right roles.
- `generate_video` with `get_cost: true` and your intended params → returns credit cost, no job submitted.

### 2. Resolve reference media → values for `medias[]`
Each `medias[]` item is `{ "value": <...>, "role": <...> }` where `value` is:
- an **`https://` URL** → use directly, or
- a **`media_id`** from upload (local files), or
- a **`job_id`** from a prior generation (chain/extend).

For **local files**:
1. `media_upload` (`filename`, optional `content_type`) → returns `upload_url` + `media_id`.
2. PUT the bytes to `upload_url` (run the returned curl, or `curl -X PUT --data-binary @file "<upload_url>"`).
3. `media_confirm` (`type: "image"|"video"|"audio"`, `media_id` or `media_ids[]`).
4. Use the confirmed `media_id` as the `value`.

**Roles** vary by model — confirm via `models_explore get`. Typical mapping (the server auto-coerces when unambiguous and returns `adjustments`):
- reference image(s) → reference-image role → `[Image1]`, `[Image2]`, … (in order)
- first / last frame (image-to-video) → `start_image` / `end_image`
- reference video(s) → reference-video role → `[Video1]`, …
- reference audio → audio role → `[Audio1]`, … (Seedance accepts audio **via `medias` only**; **requires** at least one image or video reference)

### 3. Build the prompt (with reference tokens)
Reference each provided asset by token and describe how they combine. Use the helper to guarantee exact text:
```bash
# Wire tokens into a base prompt
python3 ~/.cursor/skills/seedance-2/scripts/prompt_tools.py reframe \
  "A hero performs the dance" --images 1 --videos 1 --audios 1 \
  --audio-transcript "It's not just a pretzel, Arthur!"
```
Prefer writing tokens yourself for semantic precision, e.g. `"[Image2] stands in the interior of [Image1]. He says [Audio1]."`

### 4. Submit `generate_video`
```jsonc
{
  "params": {
    "model": "seedance_2_0",
    "prompt": "<prompt with [Image1]/[Video1]/[Audio1] tokens>",
    "duration": 8,
    "aspect_ratio": "16:9",
    "resolution": "720p",          // omit to use 720p default; "1080p" = 2x cost
    "count": 1,
    "medias": [
      { "value": "<media_id|url|job_id>", "role": "<role>" }
    ]
  }
}
```
The call returns `results[]` with an `id` and a non-terminal `status` (`queued`/`in_progress`).

### 5. Poll for the result
`job_status` (`jobId: <results[].id>`, `sync: true` to wait up to ~25s). Respect `poll_after_seconds`; video typically takes **~60–180s**. When `generation.status == "completed"`, the video URL is `generation.results.rawUrl` (`minUrl`/`thumbnailUrl` also available).

### 6. Deliver / download
Show the `rawUrl`. To save locally: `curl -L -o out.mp4 "<rawUrl>"`. Embed thumbnails with `![](thumbnailUrl)` when useful.

## Workflow: Storyboard → Movie

Animate a storyboard sheet (e.g. one made with the `gpt-image-2` skill) into a movie. This is **Phase 2** of the shared storyboard guide. Pick the prompt by how the storyboard was made (full details in [prompts/storyboard_video_framework.md](prompts/storyboard_video_framework.md)):

- **Storyboard built via the guide's Phase 1** (you have the panel breakdown — beats, timecodes, shot types, scene descriptions): author the **per-shot cinematic video prompt** by following Phase 2 of the framework (a production header + one timed shot per panel, ending with the fixed `Audio:` line). This is preferred — it gives full directorial control.
- **Any other storyboard sheet** (no structured breakdown): fall back to the **simple one-liner**. `prompt_tools.py storyboard [--panels 4-6]` prints it:

```bash
# Whole board
python3 ~/.cursor/skills/seedance-2/scripts/prompt_tools.py storyboard
# A range of panels (4 to 6)
python3 ~/.cursor/skills/seedance-2/scripts/prompt_tools.py storyboard --panels 4-6
```
These print, respectively:
- `Use the reference storyboard to make a full animation movie from panels. Audio: Diegetic sound only — natural ambience, environmental foley, and subject-driven sound.`
- `Use the reference storyboard to make a full animation movie from panels 4 to 6. Audio: Diegetic sound only — natural ambience, environmental foley, and subject-driven sound.`

Both paths end with the guide's fixed `Audio:` line, exactly. Either way: upload the storyboard (`media_upload` → `media_confirm type=image`), then call `generate_video` with that media (reference-image role) and the prompt. Use `duration 15` for a full board, or match the storyboard's specified length.

## Workflow: storyboard reels with on-screen text + voiced audio (e.g. `audio-theater` soundtracks)

For social reels (TikTok/Reels) animated from a storyboard that has **readable UI text on screens** (chat windows, clocks, cards, logos, end-cards) and a **voiced soundtrack with lip-sync** (e.g. produced by the `audio-theater` skill), use this **single-pass recipe**. It is the only approach validated to keep both lip-sync *and* on-screen text correct.

**The recipe (one generation per clip):**
1. **Keep each clip ≤ 8s** (8s is also the recommended TikTok length). Voiced lip-sync degrades or outright fails past ~10–14s — split longer stories into multiple ≤8s clips and concatenate with FFmpeg.
2. **Pass the full storyboard sheet directly as `[Image1]`** — do *not* trim, montage, or rebuild it from panel crops (that adds no value and wastes effort). A standard 3×3 / 3×5 sheet animates fine. In the prompt, tell Seedance the panel order and that **the storyboard caption labels / panel numbers in the gutters are NOT part of the scene — do not render them as text.**
3. **Pass small, tight, FACE-FREE crops of *only the text region* of each text panel** as complementary refs in the *same* call: `[Image1]` = the full board, `[Image2]`, `[Image3]`, … = a zoomed-in crop of just the screen text (e.g. the chat bubble), **not the whole panel**. In the prompt say e.g. *"keep the on-screen message text crisp and correct, reading exactly 'Hacen envios?' exactly as shown in [Image2]; do not add captions, subtitles or extra text."* **This is what fixes garbled UI text** — describing the text in words alone does not. Keep these crops **small** (a few hundred px) and **exclude human faces** (see NSFW note below).
   - **Locate the text region with OCR** rather than eyeballing: `tesseract <panel>.png stdout --psm 11 tsv` returns per-word `left top width height conf text`; take the box(es) of the words you care about, pad a little, and crop with `ffmpeg -i panel.png -vf "crop=W:H:X:Y" out.png`. (Deterministic, cheap, and naturally tight.) A `gpt-image-2` zoom of just the text section also works but is slower/costlier and can re-introduce faces.
4. **Feed the full *mixed* audio (narration audible), not a muted/feed track.** Continuous speech anchors how Seedance paces the panels. Cut the audio so it is **slightly shorter than the requested `duration`** (e.g. 7.8s audio for an 8s clip) to leave tail room so the ending isn't clipped.
5. For lip-sync, **only the on-camera speaker should move their mouth** — state explicitly e.g. *"only the monster moves its mouth; the sleeping/waking woman and the narrator are off-screen voiceover and never lip-sync."*
6. **Don't pack many panels into one clip if you need tight panel↔audio timing.** Seedance distributes a board's panels *roughly evenly* across the clip duration, and timecodes in the prompt only nudge this. If one panel must align to a specific line (e.g. a brand end-card carrying the longest line), give it its **own** clip or make it dominate the board, rather than relying on `[t–t]` timecodes.

**NSFW / "public figure" (`ip_detected`) on reference images — keep refs text/UI-only and face-free.** Realistic human faces in *reference* images — especially close-up photographic avatars (a customer headshot, a zoomed-in face) — trip Seedance's *"input image may contain a public figure"* block. Stylized 3D faces *inside the full board* are generally fine; the trigger is a prominent photoreal face in a dedicated reference crop. So when extracting text crops, **crop tightly to just the text and leave faces out** (the OCR-box crop in step 3 does this automatically). If a clip is still blocked, reduce face prominence in the refs (or the board) and resubmit.

**Anti-pattern — do NOT use a second "video-edit" pass to repair text.** Passing a finished clip back as `[Video1]` plus text crops and asking Seedance to "fix the UI screens" **does not work**: it re-renders the clip (~25dB PSNR, introduces motion/identity drift) but leaves the text just as garbled, wasting credits. Fix text in the first pass via image-ref crops (step 3) instead.

**Validated example (okidoki Doki reel):** full 3×3 storyboard sheet as `[Image1]` + one 470×130 OCR-cropped `"Hacen envios?"` chat bubble (face-free) as `[Image2]` + a 7.8s `audio-theater` mix → 8s 9:16 clip with all 9 panels in order, crisp on-screen text, correct logo end-card, and Doki lip-syncing on the two speaking panels. Earlier attempts that passed full-panel `gpt-image-2` extractions (which included the customer's photoreal avatar face) were blocked as `ip_detected`; the tight face-free OCR crop cleared it.

## Time-coded multi-shot prompting

Direct individual shots inside one ≤15s generation with timestamps; escalate wide → medium → close-up → extreme close-up:
```
[0-4s]: wide establishing shot, static camera, misty bamboo forest at dawn, low wind
[4-9s]: medium shot, slow push-in, the fighter steps forward, drums building
[9-15s]: close-up, orbit shot, the fighter strikes in slow motion, blade ringing
```
Give each shot a camera position, subject action, lighting, and transition language ("hard cut to", "seamless morph into").

## Prompting tips (from the model's guidance)

1. **Overdescribe** — pack in detail.
2. **Describe the audio**, not just visuals (audio is generated natively). Put **dialogue in double quotes**.
3. Use **"hyper-realistic, 8k"** as quality anchors.
4. **Describe the camera** ("mounted on the hood", "slow dolly zoom", "ground level").
5. **Combine reference types** — image for appearance, video for motion, audio for rhythm/voice.

## Handling billing / errors

- If a tool returns `recovery_tool: "show_plans_and_credits"`, immediately call that tool with `recovery_tool_args` (do not explain first), and surface any `upgrade_url`/checkout links verbatim.
- Invalid declared-param values return a structured error; the server returns `adjustments` (`requested`/`used`/`reason`) for fallbacks (e.g. unsupported duration clamped) — report those to the user.
- `status: "nsfw"`/`"ip_detected"` → generation was blocked; adjust the prompt/references.

## prompt_tools.py (local helper, text-only)

| Command | Purpose |
|---|---|
| `prompt_tools.py storyboard [--panels 4-6] [--extra "..."]` | Print the simple one-liner storyboard→video prompt (fallback for boards not built via the guide's Phase 1) |
| `prompt_tools.py reframe "<prompt>" --images N --videos N --audios N [--audio-transcript "..."]` | Wire `[Image1]/[Video1]/[Audio1]` tokens into a prompt |

## Additional resources

- Storyboard→video framework (verbatim): [prompts/storyboard_video_framework.md](prompts/storyboard_video_framework.md)
- MCP tools, params, cost, roles, polling details: [REFERENCE.md](REFERENCE.md)
