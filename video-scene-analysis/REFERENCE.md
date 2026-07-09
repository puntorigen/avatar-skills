# Video Scene Analysis — Reference

## JSON top-level fields

```json
{
  "version": 1,
  "video_name": "clip.mp4",
  "video_path": "/abs/path/clip.mp4",
  "analyzed_at": "ISO-8601 UTC",
  "video_info": {
    "duration": 124.572,
    "duration_fmt": "00:02:04.57",
    "fps": 30.0,
    "width": 480,
    "height": 854,
    "has_audio": true
  },
  "scene_detection": {
    "mode": "detect | interval | interval_fallback",
    "interval_sec": 6.0,
    "min_scene_duration_sec": 2.5,
    "adaptive_threshold": 3.0
  },
  "transcript": {
    "language": "es",
    "duration": 124.484,
    "segments": [{ "start": 0.0, "end": 8.72, "text": "...", "words": [...] }],
    "words": [{ "word": "hola", "start": 0.0, "end": 0.4 }]
  },
  "overview": "One-line summary string",
  "avatar_profile": {
    "mannerisms_summary": "Recurring facial behavior across talking-head scenes",
    "video_prompt": "Concise p-video-avatar prompt (identity-consistent)",
    "negative_prompt": "brief, comma-separated failure modes to avoid"
  },
  "frames_dir": "clip_frames",
  "scenes": [ ... ]
}
```

`avatar_profile` is `null` after `analyze_video.py`; the agent synthesizes it
from the talking-head scenes' `mannerisms`. Export it to the avatar folder with
`export_talking_profile.py` → `<avatar>/talking_profile.json` (consumed by the
**avatar-talking-video** skill).

## Scene object

```json
{
  "index": 0,
  "start": 0.0,
  "end": 2.97,
  "duration": 2.97,
  "scene_type": "main_character_solo",
  "zoom_from_previous": {
    "type": "none | zoom_in | zoom_out | hard_cut",
    "confidence": 0.75,
    "scale": 1.583
  },
  "visual": {
    "face_count": 1,
    "faces": [{ "confidence": 0.93, "area_ratio": 0.18, "bbox": [x, y, w, h] }],
    "motion_score": 0.42,
    "blur_score": 0.61,
    "edge_ratio": 0.08,
    "brightness": 0.55
  },
  "representative_frame": {
    "file": "clip_frames/scene_01.jpg",
    "timestamp": 1.485,
    "timestamp_fmt": "00:00:01.48",
    "sharpness": 842.5
  },
  "camera": {
    "angle": "high_angle",
    "framing": "medium_close_up",
    "description": "Selfie vertical frontal, encuadre pecho arriba"
  },
  "layout": {
    "type": "fullscreen | split_horizontal | split_vertical | pip | overlay_graphics",
    "regions": [
      { "position": "top | bottom | left | right | inset",
        "content": "broll | main_character | screen | graphics",
        "description": "qué se ve en esa región" }
    ],
    "hint": "fullscreen | possible_split_horizontal | possible_split_vertical",
    "notes": "agent-written, optional"
  },
  "broll_kind": "archival_known_person | archival_footage | stock_generic | screen_recording | graphics_animation | other | null",
  "known_people": ["Anthony Bourdain"],
  "background": {
    "type": "real_set | animated | mixed | plain | virtual | unknown",
    "elements": "qué hay detrás del personaje (real o animado)",
    "notes": "optional"
  },
  "transcript": "Text spoken during this scene window",
  "audio": {
    "audio_profile": "speech_with_sfx",
    "has_speech": true,
    "has_sfx": true,
    "has_music_bed": false,
    "non_speech_ratio": 0.42,
    "sfx_event_count": 2,
    "sfx_events": [{ "start": 12.4, "end": 12.65, "strength": 0.08 }],
    "levels": { "full_rms": 0.05, "speech_rms": 0.04, "non_speech_rms": 0.03 }
  },
  "summary": {
    "focus": "Motivation / purpose — written by the Cursor agent",
    "emotion": "curiosidad"
  },
  "mannerisms": "Talking-head only: how the face/head moves (agent-written); null for B-roll"
}
```

`summary`, `camera`, `mannerisms`, `broll_kind`, `known_people`, `background`
(and top-level `avatar_profile`) are `null` right after `analyze_video.py`;
`layout` has only its script-written `hint` (`type`/`regions` are `null`/empty).
The **active session agent** must fill them before delivery by viewing the
frames (`mannerisms`/`avatar_profile`/`background` only when talking-head scenes
exist; `broll_kind`/`known_people` only on B-roll or split B-roll regions).

### Composition fields (agent-written)

- **`layout`** — screen composition. `type: "fullscreen"` for an ordinary single
  shot; `split_horizontal`/`split_vertical` when ONE scene shows B-roll in one
  band and the presenter in another; `pip` for a small inset; `overlay_graphics`
  for graphics over the shot. `regions[]` lists each band's `position`+`content`.
  The script pre-fills a conservative `hint` (seam + half-histogram heuristic).
- **`broll_kind`** — for B-roll / supplementary scenes (and a split's B-roll
  region): `archival_known_person` (pre-recorded footage of a recognizable
  person), `archival_footage`, `stock_generic`, `screen_recording`,
  `graphics_animation`, `other`. Pairs with **`known_people`** (array of names /
  short descriptions). These flag footage best sourced via the `broll-finder`
  skill rather than synthesized.
- **`background`** — presenter scenes only: is the backdrop a `real_set` or
  `animated` (drawings/cartoons/motion graphics), `mixed`, `plain`, `virtual`,
  or `unknown`, with an `elements` description.

## Downstream use cases

- **Avatar reel pipeline**: map `main_character_solo` scenes to talking-head segments; `supplementary_material` to B-roll slots.
- **EDL / edit decision list**: use `start`/`end` + `zoom_from_previous` for Ken Burns presets (`push_in`, `push_out`, cut).
- **Script alignment**: join `transcript.segments` with scene windows for caption burn-in.

## Limitations

- Zoom detection compares **midpoint keyframes** between scenes; slow Ken Burns within one scene is not tracked.
- `hard_cut` means a strong visual discontinuity, not necessarily an editorial mistake.
- Whisper quality depends on model size and background noise.
