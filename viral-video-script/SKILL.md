---
name: viral-video-script
description: Write short-form video scripts / dialogue that follow Tuan Le's "3 billion views" viral formula — the six psychological principles (familiarity / format-steal, curiosity-gap hook, identity over product via the Means-End Chain, the credential / authority shortcut, built-in shareability, and the Hook→Problem→Story→Payoff story skeleton with fast cuts + captions). Produces a beat sheet (JSON), a shooting script (Markdown) and a clean narration track (txt) ready to feed voice-clone / avatar-reel-composer. Use when the user wants to write a script, dialogue, hook, or voice-over for a reel / short / TikTok, make a brand or product go viral, repurpose a boring product into engaging content, or mentions "guion", "guión", "script para un reel", "diálogo", "hook viral", "voz en off", or the viral / psychology content formula.
---

# Viral Video Script

Write the **words** for a short-form video (reel / TikTok / Short) so the human
brain can't scroll past it. The formula is distilled from Tuan Le's talk *"What
Getting 3 Billion Views Taught Me About Human Psychology"* — six psychological
principles plus a story skeleton. It works for "boring" products (instant ramen,
SaaS, phone plans) precisely because it sells how brains work, not the product.

The deliverable is a script, not a video. Its outputs drop straight into this
repo's pipeline: the clean narration track feeds [`voice-clone`](../voice-clone/SKILL.md)
/ [`avatar-reel-composer`](../avatar-reel-composer/SKILL.md).

## The formula (six principles)

Apply ALL six. They are not a menu.

1. **Familiarity beats originality** *(mere-exposure effect)*. Don't invent a
   format — **steal a proven one** (reaction, challenge, "walk up to a stranger",
   office tour, "how much do you pay for rent", "hey chef, make me something").
   The brain watches what it already recognizes and has liked before. Originality
   reads as *confusion*, and confusion is the fastest path to a scroll.

2. **The curiosity gap hook**. The first ~2 seconds open a gap between what the
   viewer knows and what they want to know — an itch they can't leave unscratched.
   **Never lead with the product**; the instant a brain tags content as an ad, it
   scrolls. Trigger curiosity, disbelief, or identity recognition instead. The
   product appears *naturally* once they're already watching.

3. **Sell identity, not the product** *(Means-End Chain)*. Every product has three
   layers: (1) attributes = what it is, (2) functional consequences = what it does,
   (3) **psychological value = what it means to the viewer's identity/emotions**.
   Most brands talk layer 1. Talk layer 3. ("Supplement" → healthier body → energy
   & mood → *"I feel in control of my body and my life."*) When you speak to identity,
   the viewer feels understood, not sold to — and the brain stops flagging the ad.

4. **The credential shortcut** *(authority bias)*. The brain takes shortcuts; the
   biggest is authority. Put a credential in the first ~2 seconds ("Thai chef",
   "Harvard student", "engineer who sold his company", a real kitchen + chef's
   outfit). It buys instant trust *before* the viewer evaluates anything.

5. **Build in shareability** *(social currency)*. People don't share what they like
   — they share what makes **them** look good (smart, funny, in-the-know) to their
   friends. You are the **wingman**: make the sharer look like they have great taste.
   The premise must be explainable in **one sentence**; if they can't describe it
   fast, they won't share it. Drivers that spread: **humor, surprise, awe**. (Sadness
   and anger get views but don't spread the same way.)

6. **The story skeleton** *(narrative transportation)*. Inside a story, critical
   thinking slows and emotion takes over — the best state for the brand to appear.
   Every script follows: **Hook → Problem → Story → Payoff**. Editing rules: cut any
   frame that isn't delivering new info, keep clips a few seconds each (every cut
   resets the brain's attention clock), **always burn in captions** (dual
   audio+visual processing boosts retention), zero dead space.

> North star: the product is almost irrelevant. What matters is whether you
> understand the person watching — what catches their attention and what makes them
> share. Put **people first**.

## Inputs to gather (ask only what's missing)

| Input | Needed for | Example |
|---|---|---|
| Product / brand / topic | the subject | "Buldak instant ramen" |
| Audience | identity layer (#3), tone | "spice-loving Gen Z snackers" |
| Platform | pacing / length | `tiktok` \| `reels` \| `shorts` |
| Language | the spoken copy | `es` \| `en` (default: match the user) |
| Target length | beat budget | ~30s (default 25–40s) |
| Credential available | the authority hook (#4) | "Korean street-food chef" |
| A format to steal (optional) | #1 — else propose 2–3 | "spicy-challenge reaction" |

If a credential or stealable format is missing, **propose options** rather than
skipping the principle.

## Workflow

```
- [ ] 1. Gather inputs (above). Propose a format-to-steal + credential if absent.
- [ ] 2. Scaffold the beat sheet JSON.
- [ ] 3. Fill every field, writing the spoken copy beat-by-beat in the formula's voice.
- [ ] 4. Validate against the formula. Fix every FAIL, weigh each WARN.
- [ ] 5. Render the shooting script (.md) + narration track (.txt).
- [ ] 6. Hand off (read aloud / send to voice-clone / avatar-reel-composer).
```

**Step 2 — scaffold** (writes `<out>/<slug>.script.json` pre-structured with the formula):

```bash
python3 .cursor/skills/viral-video-script/scripts/scaffold.py buldak-spicy \
  --product "Buldak instant ramen" --language en --platform tiktok --seconds 32 \
  --out scripts_out/
```

**Step 3 — write.** Edit the JSON. The hard rules the validator enforces:
- `format_steal`, `credential`, `identity_value`, `shareable_premise` are all non-empty.
- `beats` contains `hook → problem → story → payoff` in that order.
- `hook.spoken` is ≤ ~14 words (≈2s) and **must not contain the product name**.
- `shareable_premise` is ONE sentence, ≤ ~20 words.
- `share_trigger` ∈ {humor, surprise, awe}.
- `captions: true`, `cut_every_seconds` ≤ 4, total spoken copy fits `target_seconds`.

**Step 4 — validate** (re-run until it passes; treat WARN as review notes):

```bash
python3 .cursor/skills/viral-video-script/scripts/check_script.py scripts_out/buldak-spicy.script.json
```

**Step 5 — render** (writes `<slug>.script.md` + `<slug>.narration.txt` next to the JSON):

```bash
python3 .cursor/skills/viral-video-script/scripts/render_script.py scripts_out/buldak-spicy.script.json
```

## Writing the spoken copy (per beat)

- **Hook (≈2s):** the curiosity gap + the credential, NOT the product. Use the
  stolen format's recognizable opener. One short line.
- **Problem (≈4–6s):** the tension the viewer already feels — framed at the
  identity layer, not the product layer.
- **Story (≈15–25s):** the recognizable format plays out; the product enters
  *naturally* as part of the story, never as a pitch.
- **Payoff (≈5–8s):** resolve the gap + the identity reward, then the lightest
  possible product/CTA. End on the feeling, not the feature.

Keep sentences short and spoken (this is read aloud / lip-synced). Mark on-screen
action and caption text per beat; assume a cut every 2–4s.

## Output files

```
<slug>.script.json   # the beat sheet (source of truth; edit this)
<slug>.script.md     # human shooting script: beats, timing, VO, on-screen, captions, notes
<slug>.narration.txt # clean spoken VO only — feed to voice-clone / narrate.py
```

## Handoff into this repo's pipeline

The narration track is what the avatar speaks:

```bash
# clone/say in an avatar's voice, or compose a full reel from the script
python3 .cursor/skills/voice-clone/scripts/...           # TTS the narration.txt
python3 .cursor/skills/avatar-reel-composer/scripts/compose_reel.py <storyboard.json> --finish
```

For B-roll-only or found-footage shots referenced in the script, see
[`broll-generator`](../broll-generator/SKILL.md) and [`broll-finder`](../broll-finder/SKILL.md).

## Anti-patterns

1. **Leading with the product** in the hook (instant ad-flag → scroll). #2.
2. **Inventing** a format instead of stealing a proven one. #1.
3. Selling **features** (layer 1) instead of **identity** (layer 3). #3.
4. A premise you can't say in one sentence → unshareable. #5.
5. Relying on sadness/anger for reach — gets views, doesn't spread. #5.
6. Long takes, no captions, dead space → the brain tunes out. #6.

## Additional resources

- The psychology behind each principle + the original case studies: [REFERENCE.md](REFERENCE.md)
- Full worked example scripts (EN + ES): [examples.md](examples.md)
