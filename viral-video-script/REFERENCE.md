# Viral Video Script — reference

The psychology behind each principle, the original case studies, and the editing
rules. Source: Tuan Le, *"What Getting 3 Billion Views Taught Me About Human
Psychology"* (3 billion views across "boring" brands: instant ramen, software,
phone plans). Read this when you want the *why* behind a writing choice.

## The core claim

Virality has little to do with the content itself and everything to do with how
the brain works. Every scroll/share/follow is driven by triggers firing in the
**first half-second**. Understand the triggers and almost anything goes viral —
even instant noodles.

The brain runs three rapid filters before you're conscious of it:
1. *Have I seen something like this before and enjoyed it?*
2. *Is something unexpected happening right now?*
3. *Does this have anything to do with me / my life?*

If all three are "no", you scroll. The six principles exist to turn each into a
"yes".

## 1. Familiarity beats originality — the mere-exposure effect

The more the brain has seen something, the more it likes it. A novel format reads
as **confusion**, and confusion is the fastest path to a scroll. So **never invent
a format — steal one** already pulling millions of views and pour your subject into
its structure ("the format steal"). Reaction videos, challenges, "walk up to a
stranger", office tours.

> **Case — Buldak (Korean instant ramen).** Stuck at ~300k followers, growth flat.
> They stopped inventing and plugged the brand into proven food-space formats
> (spicy-challenge reactions, etc.). Result: 1.8M TikTok followers and 900M+ views
> in 12 months. The product never changed — the stolen format did the work.

## 2. The curiosity-gap hook — information-gap theory

Curiosity is the discomfort between what you know and what you want to know — a
mental itch the brain won't let you scroll past until it's scratched. Most brands
**lead with the product**, so the brain instantly tags "ad" and scrolls before a
thought even forms. The loophole: open the gap in the **first two seconds** via
curiosity, disbelief, or identity recognition. The product shows up *naturally*
once the viewer is already committed.

> **Case — Stan (all-in-one creator platform).** First video didn't open with the
> software — it stole the viral "how much do you pay for rent?" street format as an
> *office tour* using the CEO's story as the location. 1M views on TikTok, 5M on
> LinkedIn, ~20M for his personal brand over months.

Balance: open the gap in the first ~2s and the viewer is neurologically committed
to finishing. **Close the gap too early and they leave.**

## 3. Sell identity, not the product — the Means-End Chain

Every product has three layers:
1. **Attributes** — what it *is*.
2. **Functional consequences** — what it *does*.
3. **Psychological value** — what it *means* to the person's identity & emotional life.

Most brands talk layer 1. The brain only cares about layer 3. Keep asking *"why
does someone actually care about this?"* until you reach identity.

> **Example — AG1 (supplement).** attribute (a supplement) → healthier body →
> better energy & mood → *"I feel in control of my body and my life."* Now you make
> content about sleep, stress, discipline, wellness — what the viewer actually
> cares about — and it bypasses the brain's ad-filter. They feel understood, not sold to.

## 4. The credential shortcut — authority bias

Social media is shallow by biological necessity: the brain can't deeply evaluate
every clip, so it takes shortcuts — the biggest is **authority**. A credential in
the first two seconds ("Thai chef", "Harvard student", "engineer who sold his
company") is accepted *without* critical thought: *this person has status, worth
watching.* We're hardwired to attend to people we look up to.

> **Case — a real Japanese restaurant.** Cinematic, food-network-quality videos got
> ~200–300 views. Switching to the viral "hey chef, can you make me something?"
> format, the chef's outfit + professional kitchen *became the credential*. Videos
> hit 1.8M then 2M views; +300k followers in 3 months. Same food, same restaurant —
> they just earned trust in the first two seconds.

## 5. Build in shareability — social currency

People don't share what they like — they share **what makes them look good** (smart,
funny, in-the-know) to their friends. You're the **wingman**: your job is to make
the sharer look like they have great taste / discovered something cool first.

- The premise must be **explainable in one sentence**. If they can't describe it
  fast, they won't share it.
- Emotions that spread: **humor, surprise, awe**. Sadness and anger can get views
  but don't travel the same way.
- Ask of every video: *"What does the person who shares this get to say about
  themselves by sharing it?"*

## 6. The story skeleton — narrative transportation

Inside a story, people stop arguing with what they hear: critical thinking slows,
emotional processing takes over — the ideal state for the brand to appear. Every
video follows the same skeleton:

```
Hook  ->  Problem  ->  Story  ->  Payoff
```

It mirrors how the brain processes information, creating full-brain engagement
instead of skeptical analysis.

**Editing rules (the words aren't enough):**
- Cut any frame that isn't delivering new information. Every millisecond counts;
  the brain tunes out the instant it stops getting something new, and **every cut
  resets that clock**. Keep clips a few seconds each.
- **Captions are not optional.** Processing visuals + audio simultaneously activates
  multiple neural pathways (dual processing) and boosts retention.
- **Zero dead space.** (The 2.2M-view Buldak timeline: every clip a few seconds,
  every one delivering new info.)

## North star

The product is almost irrelevant — what matters is whether you understand the
person watching: what catches their attention and what makes them share. Buldak
didn't hit 900M views because ramen is exciting; the restaurant didn't gain 300k
followers because the food improved; Stan didn't hit 20M because the software
changed. Each result came from understanding how people think. Brands that stop
treating social as a billboard and **put people first** win — because they
understand people. Understand people and you can make anything go viral.

## Mapping to this repo

A finished script is the *spoken layer* of a reel. Downstream:
- `voice-clone` → speak the `narration.txt` in a cloned/designed voice.
- `avatar-reel-composer` → talking-head + B-roll reel under one narration.
- `broll-generator` / `broll-finder` → the cutaways the Story beat calls for.
- `reel-discovery` → find the *proven format to steal* for principle #1.
