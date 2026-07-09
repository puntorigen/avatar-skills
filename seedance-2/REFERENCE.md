# Seedance 2.0 (Higgsfield MCP) — Reference

Technical notes for the `seedance-2` skill. Backend: the **`plugin-higgsfield-higgsfield`** MCP server, model **`seedance_2_0`** (ByteDance Seedance 2.0). Generation is async and agent-driven via MCP tools — there is no Replicate SDK or API key here.

## Tools used

| Tool | Purpose |
|---|---|
| `balance` | Check available credits / plan. |
| `models_explore` (`action: get`, `model_id: seedance_2_0`) | Authoritative `durations`, `aspect_ratios`, `parameters`, and `medias[].roles`. |
| `generate_video` | Submit a generation (or preflight with `get_cost: true`). |
| `media_upload` → `media_confirm` | Upload local reference files, get a `media_id`. |
| `job_status` | Poll an async job by `jobId`; final URL when completed. |
| `job_display` / `reveal_generation` / `show_generations` | Inspect / list prior generations. |
| `upscale_video` / `reframe` | Post-process an existing video (optional). |
| `show_plans_and_credits` | Billing recovery (out-of-credits). |

## `generate_video` params (inside `params`)

| Field | Type | Notes |
|---|---|---|
| `model` | string (required) | `"seedance_2_0"`. |
| `prompt` | string | Scene + camera + audio description; reference tokens `[Image1]`/`[Video1]`/`[Audio1]`. Dialogue in double quotes. |
| `duration` | integer | Seconds. Default ~5; supports up to **15**. Unsupported values clamp to nearest (see `adjustments`). |
| `aspect_ratio` | string | `16:9` (default), `9:16`, `1:1`, `4:3`, `3:4`, … (confirm via `models_explore`). |
| `resolution` | string | `480p` / `720p` (default) / `1080p`. **720p recommended.** |
| `count` | integer | 1–4 results. |
| `medias` | array | Reference inputs: `{ "value": <media_id\|https URL\|job_id>, "role": <role> }`. |
| `get_cost` | boolean | If true, returns `cost.credits` and submits **no** job. Always preflight. |
| `seed` | integer | (If declared) reproducibility. |

Pass model-specific params as **top-level fields inside `params`** (not nested). Don't pass `generate_audio` — Seedance produces audio natively and takes audio **via `medias` only**.

## Measured cost (credits)

Linear in duration; resolution is the multiplier:

| Resolution | Credits/sec | 5s | 8s | 15s |
|---|---|---|---|---|
| `480p` | 3.0 | 15 | 24 | 45 |
| `720p` (default) | 4.5 | 22.5 | 36 | 67.5 |
| `1080p` | 9.0 | 45 | 72 | 135 |

(Whole-credit cost is `max(1, floor(exact))`.) **Prefer 720p**; reserve 1080p for finals.

## Reference media

- **Up to** (per the Seedance model) **9 images, 3 videos, 3 audios**; reference them by token in the prompt. The order of same-type medias maps to `[Image1]`, `[Image2]`, …
- **Roles** vary by model — read `medias[].roles` from `models_explore get seedance_2_0`. Typical:
  - reference image → reference-image role (`[ImageN]`)
  - first / last frame (image-to-video) → `start_image` / `end_image`
  - reference video → reference-video role (`[VideoN]`)
  - reference audio → audio role (`[AudioN]`)
- **Audio requires at least one image or video reference.** For lip-sync, type the spoken line into the prompt and set `duration` ≈ the audio length.
- The server auto-coerces unambiguous roles and reports `adjustments` (`requested`/`used`/`reason`).

### Local file upload flow
1. `media_upload` `{ "filename": "ref.png" }` → `{ upload_url, media_id, ... }`.
2. PUT bytes: `curl -X PUT --data-binary @ref.png "<upload_url>"` (or run the returned curl).
3. `media_confirm` `{ "type": "image", "media_id": "<media_id>" }` (or `media_ids[]`).
4. Use `media_id` as the `medias[].value`.

URLs and prior `job_id`s can be passed directly as `value` (no upload step).

## Async output / polling

- `generate_video` returns `results[]`, each with `id`, `status` (`pending`/`queued`/`in_progress`/`completed`/`failed`/`nsfw`/`ip_detected`/…), `model`, `params`.
- Poll `job_status` `{ "jobId": "<results[].id>", "sync": true }`. Honor `poll_after_seconds`. Video typically completes in **~60–180s**.
- On `completed`: `generation.results.rawUrl` (full quality), `minUrl` (compressed), `thumbnailUrl`.
- Download: `curl -L -o out.mp4 "<rawUrl>"`.

## Billing recovery

If any tool returns `recovery_tool: "show_plans_and_credits"`, call it immediately with `structuredContent.recovery_tool_args` — don't explain or ask first. Show `upgrade_url` / `checkout_url` / purchase links verbatim to the user.

## Recipes

| Goal | How |
|---|---|
| Text → clip | `generate_video` with `prompt`, `duration`, `aspect_ratio` (720p default) |
| Animate a still | upload image → `medias: [{value, role: start_image}]`, prompt "Animate this…" |
| First→last frame | `start_image` + `end_image` medias |
| Character consistency | reference image(s) → `[Image1]…`, prompt describes the character |
| Motion transfer | reference video → `[Video1]`, prompt "…the move from [Video1]" |
| Lip-sync | image/video + audio media → `[Audio1]`; transcript in prompt; `duration` ≈ audio length |
| Vertical social | `aspect_ratio: "9:16"` |
| Time-coded multi-shot | prompt with `[0-4s]: … [4-9s]: … [9-15s]: …`, `duration: 15` |
| Storyboard → movie | Phase 2 of the guide. If the board came from the guide's Phase 1: author the per-shot cinematic video prompt. Else: `prompt_tools.py storyboard [--panels 4-6]`. Pass the sheet as a reference image. See `prompts/storyboard_video_framework.md`. |

## Troubleshooting

- **Out of credits / plan limit** → handle `recovery_tool`; check `balance`.
- **Duration/aspect/resolution changed silently** → read `adjustments` (server clamped to a supported value).
- **`nsfw` / `ip_detected` status** → blocked; revise prompt/references.
- **`ip_detected` / "input image may contain a public figure"** → a *reference* image has a prominent photoreal human face (e.g. a close-up customer avatar in a text-panel crop). Crop references tightly to just the text/UI so faces are excluded (OCR-box crop), or reduce face prominence, then resubmit. Stylized 3D faces inside the full board are usually fine.
- **Wrong role error** → run `models_explore get seedance_2_0` and use a declared `medias[].roles` value.
- **Audio ignored** → ensure at least one image/video reference accompanies the audio media.
- **Garbled on-screen UI text** → describing the text in the prompt does NOT keep it correct. Pass small, tight, **face-free** crops of *only the text region* of each screen as complementary image references (`[Image2]`, `[Image3]`…) in the **same** generation and instruct "keep text exactly as in [ImageN], add no captions". Locate the region with OCR (`tesseract panel.png stdout --psm 11 tsv` → crop the word box with `ffmpeg -vf crop=W:H:X:Y`) for a tight, deterministic crop. A second video-edit pass (`[Video1]` + crops) does **not** repair text — it re-renders with drift but keeps the garble; fix it in the first pass.
- **Storyboard caption labels appear in the video** → tell Seedance the panel numbers / timecode captions in the board gutters are not part of the scene and must not be rendered.
- **Lip-sync fails/degrades on long clips** → keep voiced lip-sync clips ≤ ~8s (fails past ~10–14s); split and concatenate. Feed the full mixed audio (speech anchors pacing), cut slightly shorter than `duration`.
- **Board won't animate** → a standard full sheet (3×3 / 3×5) animates fine as `[Image1]` — no need to trim or rebuild it. Only *extreme* strips (very wide 1×N or very tall N×1) silently fail; if you must use one, keep it near-square / ~9:16.
- **Panel timing won't match audio** → Seedance spreads a board's panels roughly evenly; timecodes only nudge it. Give a timing-critical panel its own clip instead of relying on `[t–t]` ranges.
- **Slow** → normal; video is ~60–180s. Use `job_status` with `sync: true` and back off via `poll_after_seconds`.
