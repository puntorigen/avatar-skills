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
| `REPLICATE_API_TOKEN` | talking-head, B-roll, voice-clone, bg-music-hq, sound-effects, video-bg-replace, reel-composer, … |
| `ELEVENLABS_API_KEY` | avatar-invent (voice design), avatar-ambient-sfx |
| `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) | optional image generator, video-compose vision |
| `YT_API_KEY` | reel-discovery, broll-finder (YouTube Data API) |
| `APIFY_TOKEN` | optional paid upgrade for reel-discovery (TikTok/IG/FB) |

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

Some skills also compose with globally-installed skills that are not bundled here
(e.g. `gpt-image-2`, `asset-generator`, `audio-theater`); they are auto-discovered
when installed alongside these.

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
