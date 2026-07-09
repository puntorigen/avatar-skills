---
name: voice-clone
description: >-
  Clone a narrator's voice from a clean voice audio file using MiniMax
  voice-cloning on Replicate, then generate new speech (TTS) in that cloned voice
  with MiniMax speech-2.8-hd. Cloning takes the clean voice MP3/WAV (e.g.
  voice_concat.mp3 from the voice-isolate skill), trains a voice (default
  speech-2.6-hd) and saves voice_id + a preview under <avatar>/voices/<name>.json.
  Generation reuses the avatar's trained voice (or trains one if missing),
  auto-detects the text language for MiniMax's language_boost, supports per-line
  emotion and expressive interjections ((laughs), (sighs), …) plus manual <#x#>
  pauses, and saves audio under <avatar>/generated-audios/ with a manifest.json.
  Use when the user wants to clone a voice, create/train a TTS voice, get a
  voice_id, or GENERATE speech / narration / audio in a cloned voice, or mentions
  "clonar la voz", "voice clone", "voice_id", "entrenar la voz", "generar audio",
  "text to speech", or "TTS con la voz".
---

# Voice Clone

Two capabilities, one skill:

1. **Clone** a narrator's voice with **MiniMax voice-cloning** → a reusable
   **`voice_id`** saved in the avatar folder.
2. **Generate** new speech in that cloned voice with **MiniMax `speech-2.8-hd`**,
   saved under `<avatar>/generated-audios/` with a manifest.

The clone input is a clean voice file — ideally `voice_concat.mp3` produced by the
`voice-isolate` skill.

## Requirements

- `pip3 install -r requirements.txt` (`replicate` client + `langid` for language
  detection).
- A Replicate API token. It is **shared** with the other Replicate skills
  (avatar-video-reel, gpt-image-2, bg-music, …) and discovered automatically.
  To set/refresh it: `python3 scripts/setup_key.py YOUR_REPLICATE_API_TOKEN`.
- The voice file must be **MP3/M4A/WAV, 10s–5min, <20MB**.
- A local tunnel — **`cloudflared`** (preferred) or **`ngrok`** — installed on
  PATH (**only for cloning**, not for generation). `brew install cloudflared`
  (no account needed) or `ngrok config add-authtoken <token>` once. See *How the
  upload works* below.

## How the upload works

`minimax/voice-cloning` re-fetches the audio from MiniMax's own servers, so it
needs a **public URL with a real extension** — a raw file object or Replicate's
auth-protected upload both fail with `invalid file ext`. To avoid uploading your
voice to a third party, the skill serves the file **straight from your machine**
over a short-lived tunnel that is torn down as soon as the clone finishes:

1. Prefer **cloudflared** quick tunnel (no account, ephemeral per-run URL), then
   fall back to **ngrok**, then — only if neither is installed — a temporary
   public host (`tmpfiles.org` / `catbox.moe`).
2. Reachability is verified the way MiniMax sees it: if the local resolver blocks
   the tunnel domain (some ISPs filter `*.trycloudflare.com`), it re-checks via
   public DNS (1.1.1.1 / 8.8.8.8) so a blocked *local* resolver is not mistaken
   for an unreachable URL.

## Clone a voice

```bash
python3 scripts/clone_voice.py <video>_voice/voice_concat.mp3
```

That's it — everything else is auto:

- **Model**: `speech-2.6-hd` by default (the current HD model; MiniMax may serve
  it on a newer HD engine). Override with `--model` (`speech-2.6-turbo`,
  `speech-02-hd`, `speech-02-turbo`).
- **Defaults** match the model: `--accuracy 0.7`, noise reduction off, volume
  normalization off (the input is already clean). Flags: `--noise-reduction`,
  `--volume-normalization`.
- **Where it saves** (auto-inferred):
  - Source `name`: if the file is `<stem>_voice/voice_concat.mp3` → `<stem>`;
    otherwise the file's own stem. Override with `--name`.
  - Avatar dir: the folder containing a `videos/` directory (e.g. `lolo/`).
    Override with `--avatar-dir`.

## Output (in `<avatar>/voices/`)

| File | What it is |
|------|------------|
| `<name>.json` | **The record**: `voice_id`, `model`, `source`, `preview_url`, `created_at` |
| `<name>_preview.mp3` | Preview clip of the cloned voice (skip with `--no-preview`) |
| `index.json` | Registry mapping every `name` → `voice_id` for this avatar |

The `voice_id` is what you pass to MiniMax text-to-speech to synthesize new
speech in this cloned voice — which is exactly what `generate_speech.py` does.

Report the `voice_id` and the path to `<name>.json` when done.

## Generate speech (TTS)

Synthesize new audio in the avatar's cloned voice with **`minimax/speech-2.8-hd`**.

```bash
# Reuse the avatar's trained voice (auto-detects language, here Spanish):
python3 scripts/generate_speech.py "Hola, soy Lolo" --avatar-dir lolo

# Train automatically first if the avatar has no voice yet:
python3 scripts/generate_speech.py "Hello!" --source lolo/videos/clip_voice/voice_concat.mp3

# Pick an emotion explicitly:
python3 scripts/generate_speech.py "Great news!" --avatar-dir lolo --emotion happy
```

Voice resolution (automatic):

1. `--voice-id` if given.
2. Else the avatar's **already-trained** voice (`<avatar>/voices/`). With one
   trained voice it's picked automatically; with several, pass `--name`.
3. Else, if `--source` is given, it **trains one first** (a clean voice file, or
   a video whose `<stem>_voice/voice_concat.mp3` exists), then generates.
4. Else it errors asking for `--source` or `--voice-id`.

Key options:

- **`--emotion`** (default `auto`): `auto`, `happy`, `sad`, `angry`, `fearful`,
  `disgusted`, `surprised`, `calm`, `fluent`, `neutral`. The agent should choose
  one that fits the line when appropriate.
- **`language_boost`** defaults to **`None`** (no boost) so the **cloned voice
  keeps its own accent**. Boosting a language nudges pronunciation toward a
  "standard"/regional accent that can fight the clone — e.g. a neutral or Chilean
  voice drifting into Argentinian *voseo*. Pass `--language-boost detect` to
  auto-detect from the text (Unicode script for CJK/Cyrillic/Arabic/… + `langid`
  for Latin scripts), or a locale (`Spanish`, `English`, …) only when you
  specifically need that pronunciation help.
- Audio: `--speed`, `--volume`, `--pitch`, `--audio-format` (mp3/wav/flac/pcm),
  `--sample-rate`, `--bitrate`, `--channel`, `--english-normalization`.
- Text: pass inline or via `--text-file script.txt`.

### Expressive interjections & pauses

`speech-2.8-hd` renders **expressive interjections** written inline in the text,
so the voice doesn't sound flat. Drop them right where they happen:

```bash
python3 scripts/generate_speech.py "Lo logramos (laughs softly)… (sighs) y por fin puedo soltar." --avatar-dir lolo
```

- Recognized (common, reliably-rendered) set: `(laughs)`, `(laughs softly)`,
  `(chuckles)`, `(giggles)`, `(sighs)`, `(gasps)`, `(coughs)`, `(clears throat)`,
  `(sneezes)`, `(sniffs)`, `(groans)`, `(yawns)`, `(whistles)`, `(humming)`,
  `(hums)`, `(exhales)`, `(inhales)`, `(breathes)`, `(gulps)`, `(crying)`,
  `(sobs)`, `(screams)`, `(applause)`. The model recognizes **20+**; run
  `python3 scripts/generate_speech.py --list-interjections` to print them.
- The script **logs** the interjections it detects and **warns** about any other
  parenthesized text (which may otherwise be read out literally). Detected
  interjections are recorded in `manifest.json` per clip.
- **Manual pauses:** `<#x#>` inserts `x` seconds of silence (0.01–99.99), e.g.
  `"Respira hondo <#0.6#> y continúa."` — useful for beats and emphasis.
- Use interjections **sparingly** — one or two per passage reads as natural;
  overusing them sounds theatrical. Pair with `--emotion` for the overall tone.

### Long narrations: synthesize per sentence

The model degrades on very long single takes (its own docs recommend short
sentences for smoother delivery). For multi-paragraph scripts, synthesize **one
sentence at a time and join the clips** rather than sending everything in one
call. The `avatar-reel-composer` skill's `narrate.py` does exactly this (one
MiniMax call per sentence + a small silence gap); reuse that flow for reels.

### Output (in `<avatar>/generated-audios/`)

| File | What it is |
|------|------------|
| `<NNN>_<slug>.<ext>` | The generated audio clip (auto-numbered) |
| `manifest.json` | `items[]` mapping each file → `text`, `voice_id`, `voice_name`, `emotion`, `language_boost`, and synth params |

Report the audio path, the `voice_id` used, and the detected `language_boost`.

## Notes

- One clone per source recording: re-running with the same `name` overwrites its
  record and updates `index.json`.
- The clone quality depends on the input. Use the clean, SFX-free
  `voice_concat.mp3` from `voice-isolate` for best results; keep
  `--noise-reduction` off when the audio is already clean.
- Generation never re-uploads the voice sample (it only sends the `voice_id` +
  text), so it needs **no tunnel** and is fast.
- A trained `voice_id` works across MiniMax speech models, so the voice trained
  with `speech-2.6-hd` is used for `speech-2.8-hd` generation.
