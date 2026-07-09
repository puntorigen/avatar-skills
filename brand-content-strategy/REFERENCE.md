# Brand Content Strategy — reference

Detailed playbook for the workflow in [SKILL.md](SKILL.md). Read the relevant
section when you reach that step.

---

## 1. Brand-profiling checklist (step 1)

Fetch the site (WebFetch) and extract, verbatim where possible:

- **Positioning line** — the one-sentence "who/what" (hero headline).
- **Credentials / proof** — titles, scale numbers (users, revenue, team),
  notable employers/clients, certifications, "first/before X" claims. These are
  the *credential shortcut* (Principle 1) — the single biggest growth lever.
- **Products / open source / IP** — anything demonstrable on camera.
- **Services + business goal** — what they sell and to whom (the funnel target).
- **Existing CTA** — what the site already asks for (book a call, signup…).
- **Tone / philosophy** — to keep the content voice consistent.

Write a 3-bullet "unfair advantages" summary; every content pillar should lean
on at least one.

---

## 2. Query + geo design (step 2)

Derive 3–6 reel-discovery queries. Cover these archetypes:

| Archetype | Purpose | Example |
|---|---|---|
| Core niche | The real differentiator (winnable) | "ai coding agents" |
| Adjacent hot | Ride a nearby wave | "vibe coding" |
| Broad authority | Map the saturated top | "ai agents" |
| News / trend | Recency angle (usually secondary) | "ai news" |
| Per language | Language arbitrage | "agentes de inteligencia artificial" (es, CL) |

Heuristics:
- One query per target language, with matching `--region/--lang`.
- Prefer **velocity** sort + `--since 60..120` to catch current breakouts.
- `--max-duration 240` keeps it short-form + short explainers.
- Add competitor research with `--business <name|@handle>` when handles are known.

---

## 3. Creator footprint prompt (step 5)

For each top individual creator, send `perplexity_ask` a prompt of this shape
(adapt language to the creator's audience):

> I'm researching the content distribution strategy of `<creator + @handle +
> niche>`. Map their FULL cross-platform footprint and growth strategy:
> (1) every platform (TikTok, YouTube, Instagram, X, LinkedIn, newsletter,
> Skool/Discord community, website/product) with follower counts if findable;
> (2) what they monetize (course, community, SaaS, agency, consulting,
> affiliate); (3) their repeatable hook/format; (4) how they cross-promote into
> a funnel. Concrete handles and URLs. **Flag anything you cannot verify.**

Tips:
- One focused creator (or a tight 2–3 cluster) per call; batch calls in parallel.
- Always demand the "flag unverifiable" clause — small creators have thin data.
- Capture into a table: creator | platforms+followers | monetizes | signature hook.

---

## 4. The distribution playbook (full)

What the winning individual creators consistently do (synthesize, then map onto
the brand's advantages):

1. **Credential first.** Bio + first 2s lead with authority (e.g. ray_fu: "Ex
   Meta senior SWE | Duke | NYC"). Beat the product flag.
2. **Outcome hook formula:** `"How I built [result in $/time] with [tool/agents]"`
   — number + tool + team framing. Never the product first.
3. **TikTok/Reels/Shorts = discovery; YouTube long-form = proof + SEO; link-in-bio
   = funnel.** Near-universal architecture.
4. **Content engine:** one core asset → blog + social + clips + podcast. Top
   creators *build AI* to do this (Duncan's "7-skill pipeline", Vaibhav's
   "Content OS + Eva", Matt Wolfe's long-form→blog→social→podcast).
5. **Monetization ladder:** free workshop/lead-magnet (tripwire) → course/cohort
   → community subscription → **high-ticket consulting/agency** (back-end).
   (Vaibhav ₹299 → cohorts; Pau Berenguer "AI Agency Accelerator".)
6. **Borrowed authority:** guesting on podcasts + press features (raises pricing).
7. **Language arbitrage:** the ES/LatAm niche is dominated by Spaniards doing
   no-code content; a credible engineer can own Chile/LatAm with the same topics.

**Key differentiation insight:** most viral "AI agent" creators are *no-code /
"sin programar"* marketers selling "replace your team." The few with real
engineering cred (ex-FAANG, shipped-at-scale) get the highest velocity. A genuine
senior architect wins the "what actually works in production, no hype" lane the
hype crowd can't occupy — while still **stealing their proven formats**.

---

## 5. 30-day strategy template (step 7)

Write `<brand>-30dias.md` with these sections (fill from the research):

```markdown
# Estrategia de contenido — 30 días

**Objetivo:** <goal: authority + leads + geos>.
> Base: reel-discovery (<N niches>) + ingeniería inversa de <N> referentes.

## 1. Posicionamiento
- Una frase / 3 ventajas injustas (de la credencial del sitio).
- Persona + diferenciador (anti-hype / production-grade).

## 2. Público y plataformas
- Tabla: pista de idioma → geo → objetivo → plataforma foco.
- Prioridad de plataformas por ROI (incl. LinkedIn para B2B).

## 3. El playbook de viralización (los 7 principios, condensados)

## 4. Pilares de contenido
- Tabla: pilar | % mezcla | objetivo | formatos.
- Bio (idéntica en las 4 redes) + hashtags base EN/ES.

## 5. Pre-requisitos de producción
- Avatar (avatar-frames) + voz (voice-clone), link-in-bio, lead magnet,
  plantillas de estilo (reel-discovery --download-top → reel-restyle).

## 6. Calendario de 30 días
- 4 semanas × ~4 piezas: día | pieza | hook | plataformas | skill.
  (Semana 1 credencial/origen; 2 mostrar el motor; 3 opinión/noticia; 4 casos/cierre.)

## 7. Embudo y monetización
- Diagrama reel → link-in-bio → sitio → lead magnet → comunidad → consultoría.

## 8. Cambios al sitio (P0/P1/P2)
- Punch-list aditivo para volver el sitio el destino del embudo (ver §9 abajo).
  P0 lead magnet + CTA único + analytics/UTMs; P1 hub de contenido + JSON-LD/sameAs
  + backlinks + hook al hero; P2 locales/idiomas + links a canales + handle=dominio.

## 9. Métricas (Día 15 y 30)
- velocity, saves/shares, CTR a sitio, leads, (followers = vanidad).

## 10. Producción con el repo (orden de skills)
- reel-discovery → video-scene-analysis → reel-restyle → viral-video-script →
  voice-clone → avatar-reel-composer → broll-* + bg-music → video-compose.

## 11. Capa de audio / podcast (opcional — ver §6 abajo)

## 12. Apéndice — referentes a restylar (tabla del shortlist humano)
```

Cadence default: 4 pieces/week (scalable to 3); produce vertical once, distribute
to all 4 networks; 2 ES versions/week.

---

## 6. Audio / podcast layer (optional)

**Role:** depth + trust (sells high-ticket), **not** discovery. Phase it in
month 2+, never the month-1 priority.

**Stack:**
- `voice-clone` (MiniMax) → the person's *own* cloned voice, EN + ES, **declared
  as AI**. (Not audio-theater's generic Gemini voices — authenticity matters.)
- `audio-theater` → SFX + music + spatial stage + mix. Its mixer is
  voice-agnostic: feed `mix.py --dialogue dialogue.wav --cues cues.json` a
  dialogue track built from voice-clone clips. For L/R interview panning with
  `mix_spatial.py`, build a `lines.json` (timecodes per clip) — small glue, once.
- Research/script: `reel-discovery` + `perplexity_ask` → `viral-video-script`.

**Automated pipeline (keep a human approval step):**
`reel-discovery + perplexity_ask` → script (EN/ES) → `voice-clone` → `audio-theater`
(cues → mix) → **[human approves]** → publish.

**Caveats:** never clone a real person's voice to fake an interview
(impersonation); simulated guests must be fictional + declared. Quality > volume.

**Where to publish:** a podcast is an RSS feed registered once per directory.
- Hosting (owns the feed): self-host (RSS XML + MP3 on object storage; most
  automatable) | Transistor/Buzzsprout (API + portable) | Spotify for Creators
  (free, easiest).
- Surface priority for authority+leads: **YouTube (video) = discovery+SEO** >
  Spotify + Apple (subscription/credibility) > site `/podcast` (owned + funnel) >
  clips → TikTok/Reels/Shorts (reach). One asset → 3 surfaces + clips.
- Disclose AI/synthetic content (YouTube requires it; Spotify/Apple tolerate it
  when declared).

---

## 7. Production specs — reel length + scene types

**Reel length** — derive it empirically from the discovery data (don't guess):
`results.json` records carry `duration_s`. Compute median + p25/p75 per platform,
and again for the **top ~50% by velocity** (the videos that actually scale). In
the AI/coding niche this yielded:

| Format | Target length | Evidence |
|---|---|---|
| Short-form (TikTok/Reels/Shorts) | **30–60s** (~45s) | Top-velocity cluster p25–p75 = 26–63s |
| Reel with a demo | up to **60–90s** | A demo retains attention → can stretch |
| YouTube explainer (proof layer) | **60–150s** | Long-form median ~97s |

Cross-cutting: hook in the first **~2s**, burned-in captions, avoid >3 min. The
winners are NOT the longest — top-velocity p75 is *lower* than the overall p75.

**Scene types for technical content** (beyond talking-head + generic B-roll).
Two-layer architecture: a **base layer** (proof visual) + an optional **avatar PiP
overlay**. A real demo (cause→effect app walkthrough) doesn't fit a 40–60s reel — it
needs context and eats the runtime; reserve real demos for **YouTube long-form**. In
short-form the base layer is **complementary B-roll**: animated captures that illustrate
while the narration/avatar carries the message.

All three share **`broll-core`** (geometry, ffmpeg, manifest, and the avatar-PiP
compositor — one source of truth).

| Scene | Layer | What | How | Status |
|---|---|---|---|---|
| `broll-web-capture` | base | Websites + GitHub repos with zoom-in/pan (Ken Burns), scroll-reveal, or a spotlight on a region | Playwright (high-DPI, full-page) → motion with `ffmpeg`. Output 3–6s clips, 9:16 overlay or full-frame. **`github` preset**: header pan/zoom, animated star counter (API), README/contrib money-shots. Presets `landing` / `producthunt` / `generic` | **built** |
| `broll-terminal` | base | Realistic animated terminal (human typing jitter, typo+backspace, output that streams with spinners, Warp/iTerm theme) | Declarative `session.json` → HTML/CSS + Playwright (**deterministic** frame capture, **never runs a real shell**) → mp4. 9:16/16:9. Optional avatar PiP | **built** |
| `broll-demo-avatar` | overlay | Compositor: avatar narrating in PiP **over any base layer** (web-capture, terminal, or Loom) | Today the PiP lives in `broll-core` (`pip_overlay`) and is exposed via `--avatar` on the base skills. A dedicated skill (matte with `video-bg-replace` + composite an external Loom) is still to build | shortcut built; dedicated skill pending |

Rule of thumb: **real demos → long-form; capture B-roll → 40–60s reels.**

**Material the avatar-PiP scene needs** (prep it when producing the reel — it's
different material from a full-frame talking head): a **face-focused, LOCKED**
avatar clip — generate a dedicated badge shot with the **`pip`** move of
`avatar-camera-angles` at `1:1` (centered, even-margin close-up), on-demand if it
doesn't exist (don't reuse `push_in`), then lip-sync with a **locked camera** (no
push-in/out, zoom or dolly — the face stays put, only the mouth moves). **No
burned-in subtitles in the avatar clip** — the segment's subtitles go on the
**whole reel frame** (burned by `avatar-reel-composer`'s finish pass, not inside
the circle) — and ideally a **matted** avatar (`video-bg-replace`) for a clean
cut-out. The `broll-web-capture` PiP compositor never zooms the avatar (motion
comes from the base layer); it documents this and exposes `--face-bias`.

---

## 8. Credentials / setup

- `YT_API_KEY` (reel-discovery `config.json` or env) — exact YouTube counts.
- `APIFY_TOKEN` (optional) — robust TikTok/IG keyword + all Facebook discovery.
- `perplexity_ask` MCP — creator footprint research.
- `discovery/` is gitignored (raw research + media); commit only the final
  `<brand>-30dias.md` if desired.

---

## 9. Website / destination audit (ALWAYS include in the report)

The site is where short-form traffic converts, so every report MUST include a
**website punch list**. First audit the live site (WebFetch): does it cover
top/mid/bottom of funnel, what's the existing CTA, is it multilingual, and is
there analytics? Then write the punch list, prioritized. Keep it **additive** —
do not propose a redesign or a tone change; most personal sites convert because
they are clean and credible.

| Tier | Item | Why |
|---|---|---|
| **P0** | Lead magnet + email capture (top-of-funnel opt-in) | The link-in-bio destination for viewers not ready to book |
| **P0** | Single, obvious primary CTA matching the reel's promise | Don't make arrivals read the whole CV first |
| **P0** | Analytics + conversion tracking + UTMs | Without it, the strategy's CTR/leads metrics are unmeasurable |
| **P1** | Content hub (`/blog` \| `/videos` \| `/podcast`) embedding reels + transcripts | Fresh indexable pages (one per video/keyword) + dwell time |
| **P1** | JSON-LD `Person` + `sameAs` + OpenGraph + bidirectional channel links | Consolidates the entity in Google |
| **P1** | Surface the strongest credential hook in the hero | Authority shortcut on the highest-traffic page |
| **P2** | Localize per target language/market (reuse existing locales if multilingual) | Language arbitrage — localize the message, don't rebuild |
| **P2** | Visible channel links + embed latest content; handle = name/domain | Trust + cross-pollination |

Adapt to the site's reality: if it's already multilingual, P2 becomes "leverage
the existing `/es` (etc.) locale for the underserved market", not "build one".
