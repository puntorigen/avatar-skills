<p align="center">
  <img src="https://raw.githubusercontent.com/puntorigen/avatar-skills/main/assets/banner.png" alt="avatar-skills" width="820" />
</p>

# puntorigen/avatar-skills

Agent skills for creating **AI avatar talking-head videos and short-form reels**
end to end — invent or clone a presenter, give it a cloned voice, generate
lip-synced talking-head and B-roll scenes, and assemble finished vertical reels.

Unlike the local-first [`puntorigen/skills`](https://github.com/puntorigen/skills),
these skills are **cloud-based**: they orchestrate hosted models (Replicate —
`prunaai/p-video-avatar`, MiniMax, Stable Audio; ElevenLabs; Google Gemini;
Higgsfield / seedance-2). No API keys are bundled — each skill reads its token at
runtime from an environment variable or a git-ignored `config.json` written by
its `scripts/setup_key.py` (see [Credentials](#credentials)).

Install with the [skills CLI](https://skills.sh/):

```bash
npx skills add puntorigen/avatar-skills                    # install all
npx skills add puntorigen/avatar-skills@avatar-reel-composer  # one skill
npx skills add puntorigen/avatar-skills -g -y              # global install, skip prompts
```

Browse: [skills.sh/puntorigen/avatar-skills](https://skills.sh/puntorigen/avatar-skills)

## Demo — the reel is the proof

https://github.com/user-attachments/assets/0e762719-62e3-4c9d-bf6f-314a899dcb49

A ~24s vertical reel in which a Victorian detective takes on his toughest case —
the mystery of **his own origin**. Every layer of him was produced by these
skills from **a single prompt**:

- [`broll-cursor`](broll-cursor) — the opening Cursor agent-chat (*"invent a Sherlock detective for a demo about avatar-skills"*) that streams the skill calls
- [`viral-video-script`](viral-video-script) — the "I'm not real" AI-reveal script + narration track
- [`avatar-invent`](avatar-invent) — invents the detective (hero still + camera angles) and **designs his voice**
- [`voice-clone`](voice-clone) — the cloned voice that narrates every line
- [`avatar-talking-video`](avatar-talking-video) — the lip-synced talking-head scenes
- [`broll-avatar-camera`](broll-avatar-camera) — the action B-roll (inspecting a clue with a magnifying glass)
- [`avatar-reel-composer`](avatar-reel-composer) — narrates, aligns, cuts, captions and scores the whole thing
- [`bg-music-hq`](bg-music-hq) + [`avatar-ambient-sfx`](avatar-ambient-sfx) — the music bed and the **spatial** sound design (fireplace to the left, a pipe puff before the closing line)

No camera, no actor, no studio — just the toolkit.

## Seen in the wild

These skills power real published content. For example, the TikTok channel
[**El Rincón del Alma**](https://www.tiktok.com/@elrincondelalma_com) publishes
narrated *cuento* (short-story) reels whose presenters, voices and edits are
produced with [`cuento-reel`](cuento-reel) and
[`avatar-reel-composer`](avatar-reel-composer) — backed by
[`avatar-invent`](avatar-invent) (invented presenters + designed voices),
[`voice-clone`](voice-clone) (narrator voice) and
[`bg-music-hq`](bg-music-hq) (music beds).

## Conventions

- **Generated avatars live under `./avatares/`.** The creator skills
  (`avatar-invent`, `avatar-reel-composer`'s `create_avatar.py`,
  `reel-restyle`'s `scaffold_avatar.py`) route a **bare name** to
  `./avatares/<name>/` so generated avatars never clutter the project root. Pass
  an explicit path (e.g. `path/to/nora`) to override, or set `AVATARES_ROOT`.
  Downstream skills then reference the avatar by that path (e.g. `avatares/lolo`).
- **Support models live outside the repo.** Weights (e.g. MediaPipe
  `blaze_face`) are downloaded by each skill's setup script into
  `~/.avatar-skills/models/` (override with `AVATAR_SKILLS_HOME`) — they are
  never committed.
- **Outputs and media are git-ignored** (`avatares/`, `*.mp4`, `*.png`, …); only
  instructions, scripts and small JSON/MD examples are versioned.

## Credentials

Skills auto-discover credentials from your environment first, then from a
git-ignored `config.json` in the skill (or a sibling skill), written by
`python3 <skill>/scripts/setup_key.py ...`:

| Variable | Used by |
|---|---|
| `REPLICATE_API_TOKEN` | talking-head, B-roll, voice-clone, bg-music-hq, bg-music, sound-effects, video-bg-replace, reel-composer, gpt-image-2, audio-theater (WhisperX), … |
| `ELEVENLABS_API_KEY` | avatar-invent (voice design), avatar-ambient-sfx, audio-theater (SFX) |
| `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) | asset-generator (image gen), audio-theater (Gemini TTS), video-compose vision |
| `YT_API_KEY` | reel-discovery, broll-finder (YouTube Data API) |
| `APIFY_TOKEN` | optional paid upgrade for reel-discovery (TikTok/IG/FB) |

> `seedance-2` needs **no API key** — it runs through the Higgsfield MCP (billed
> via Higgsfield credits, handled by the MCP account).

## Available skills

### Avatar creation & identity

- **avatar-invent** — invent a brand-new fictional presenter from a text
  description (hero still + camera angles + designed & cloned voice).
- **avatar-camera-angles** — generate realistic camera-angle variations of a
  talking-head from one reference frame (same person/outfit/room).
- **avatar-location** — give an existing avatar a new look (wardrobe +
  environment + light) while keeping its identity and voice.
- **avatar-frames** — extract clean avatar reference frames from talking-head
  videos (single face, sharp, no burned-in subtitles).

### Talking-head & reels

- **avatar-talking-video** — turn a line of text into a lip-synced talking-head
  MP4 in the avatar's cloned voice (`prunaai/p-video-avatar`).
- **avatar-reel-composer** — turn a script + an existing avatar into a finished
  vertical reel (narration, per-scene cuts, talking-head + B-roll, music).
- **reel-restyle** — distill one avatar's reel style into a template and re-apply
  it to a different avatar.
- **cuento-reel** — narrated "story" reels where invented avatars act as
  characters over a narrator voice.
- **avatar-ambient-sfx** — add a spatial ambient SFX layer to a finished reel.

### B-roll

- **broll-generator** — generate hyper-realistic complementary B-roll clips from
  a scene description.
- **broll-story** — silent B-roll of an existing avatar doing a demonstrative
  activity (storyboard → seedance-2).
- **broll-avatar-camera** — action B-roll of our own avatar (same
  `p-video-avatar` model, consistent face/wardrobe/room).
- **broll-finder** — find real public YouTube footage about a topic or person.
- **broll-web-capture** — turn a website or GitHub repo into a polished B-roll
  clip (with optional avatar PiP).
- **broll-terminal** — turn a session JSON into an animated-terminal B-roll clip.
- **broll-cursor** — turn a session JSON into an animated IDE agent-chat B-roll
  clip (a Cursor-style "Agent" panel): a typed prompt + a streaming assistant
  turn with tool-call rows. Sibling of `broll-terminal` (shell) for the
  IDE/agent register.
- **broll-core** — internal shared library for the `broll-*` skills.

### Voice & audio

- **voice-clone** — clone a narrator's voice (MiniMax on Replicate) and generate
  expressive TTS in that voice.
- **voice-isolate** — extract clean voice samples from a video (Demucs + whisper).
- **bg-music-hq** — high-quality background music & jingles (MiniMax Music 2.5).
- **sound-effects** — generate SFX / short audio assets (Stable Audio 2.5).

### Video editing & analysis

- **video-compose** — compose a polished reel from a folder of clips + images
  (FFmpeg + Remotion titles, beat-synced EDL).
- **video-scene-analysis** — analyze a local video into a structured scene
  sequence (cuts, type, transcript, SFX, camera).
- **video-bg-replace** — matte a speaker and composite them over a new
  background (Robust Video Matting).
- **video-transcribe** — download & transcribe a video (yt-dlp + faster-whisper)
  to text / SRT / JSON.

### Discovery & downloaders

- **reel-discovery** — find top/trending public reels by topic or business
  across YouTube, TikTok, Instagram and Facebook.
- **youtube-videos** / **tiktok-videos** / **instagram-videos** /
  **facebook-videos** — batch-download public videos from a profile / channel /
  link, named by upload datetime.

### Strategy & scripting

- **brand-content-strategy** — turn a website or personal brand into a
  research-backed content + channel strategy.
- **viral-video-script** — write short-form scripts/dialogue following a viral
  content formula (beat sheet + shooting script + narration track).
- **onboarding-script** — generate an ordered series of onboarding reel scripts
  for a new team member (welcome, tools, best practices, create a project,
  deploy), auto-discovering the company from the connected tools (gh org/CI,
  `az`/`gcloud`/`vercel`, Notion/Linear MCP, chat transcripts). Company-agnostic;
  outputs feed `avatar-video-reel` / `avatar-reel-composer`.

### Generation engines (shared)

The shared model backends the pipeline skills call under the hood — bundled here
so the set is self-contained (they read their own token; no keys are committed):

- **gpt-image-2** — generate/edit images with OpenAI GPT Image 2 on Replicate
  (character sheets, product sheets, storyboard sheets, precise in-image text).
  Called by `avatar-invent`, `avatar-camera-angles`, `broll-avatar-camera` and
  `broll-story`.
- **seedance-2** — generate audio-synced video with ByteDance Seedance 2.0 via
  the **Higgsfield MCP** (no API key — uses Higgsfield credits). Animates the
  storyboard from `broll-story` and lip-syncs `audio-theater` clips.
- **audio-theater** — multi-character audio (dramatized radio play / lipsync
  clips / podcast) with Gemini TTS, realistic SFX and instrumental score. Powers
  `avatar-ambient-sfx` and produces lipsync/voiceover tracks for the reel skills.
- **asset-generator** — generate and edit image assets with Google Gemini
  (styles, transparent PNGs via background removal, resizing). Used as the
  optional Gemini image generator and by the `repo-banner` header art.
- **bg-music** — quick instrumental background-music tracks (MiniMax on
  Replicate). The lighter "fast" music backend for `audio-theater`
  (`audio-theater`'s default `hq` backend also reuses its mood library).

## Skill composition

The avatar pipeline chains these skills:

```
avatar-invent | create_avatar (Instagram)  →  avatares/<name>/ (scene, angles, voice)
viral-video-script                          →  script + narration track
avatar-reel-composer                        →  narrate → talking-head + B-roll → final reel
   ├─ avatar-talking-video / broll-*         (per-scene clips)
   ├─ voice-clone                            (cloned narration)
   └─ bg-music-hq / avatar-ambient-sfx       (music + spatial SFX)
```

All the shared generation engines these skills call — `gpt-image-2`, `seedance-2`,
`audio-theater`, `asset-generator` and `bg-music` — are **bundled** in this repo
(see *Generation engines* above), so the set is fully self-contained. Skills still
auto-discover any matching skill already installed globally, but nothing here
depends on a skill that isn't in the repo.

## Repo layout

```
avatar-skills/
├── README.md
├── skills.sh.json          # grouping for the skills.sh repo page
├── <skill>/
│   ├── SKILL.md            # required — agent instructions + frontmatter
│   ├── REFERENCE.md        # optional deep reference
│   ├── scripts/            # setup_key.py, setup scripts, pipeline scripts
│   └── examples/           # small JSON/MD schema examples
└── ...
```

## Verify locally before publishing

```bash
npx skills add . --list
npx skills add .@avatar-reel-composer -g -y   # dry-run one skill
```

## License

MIT — see [LICENSE](LICENSE). Skill instructions and scripts are MIT unless noted
otherwise. The hosted models each skill calls (Replicate, ElevenLabs, MiniMax,
Google, Higgsfield) are subject to their own terms and pricing.
