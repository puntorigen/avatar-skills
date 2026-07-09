#!/usr/bin/env python3
"""Prompt helpers for the seedance-2 skill (Higgsfield MCP backend).

Generation itself runs through the Higgsfield MCP `generate_video` tool
(model `seedance_2_0`), which the agent calls directly. This script is a
pure-text helper (no network, no deps) that guarantees the exact prompts:

  storyboard  -> the SIMPLE one-liner storyboard->video prompt (FALLBACK). Use
                 this only when the storyboard was NOT built via the guide's
                 Phase 1. If it was, author the Phase 2 per-shot cinematic video
                 prompt instead, following prompts/storyboard_video_framework.md.
  reframe     -> wire reference tokens ([Image1]/[Video1]/[Audio1]) into a prompt

Examples:
  python3 prompt_tools.py storyboard
  python3 prompt_tools.py storyboard --panels 4-6
  python3 prompt_tools.py reframe "A hero walks in" --images 2 --videos 1 \
      --audios 1 --audio-transcript "It's not just a pretzel, Arthur!"
"""

import argparse
import re
import sys

# The storyboard guide's fixed audio line, kept verbatim (em-dash, capital "Diegetic").
AUDIO_LINE = ("Audio: Diegetic sound only — natural ambience, environmental foley, "
              "and subject-driven sound.")


def parse_panel_range(spec):
    """Parse '4-6', '4 to 6', '4', '4,6' into (start, end|None); None -> whole board."""
    if spec is None:
        return None
    nums = [int(n) for n in re.findall(r"\d+", str(spec))]
    if not nums:
        return None
    if len(nums) == 1:
        return (nums[0], None)
    return (nums[0], nums[1])


def build_storyboard_prompt(panel_range, extra=None):
    if panel_range is None:
        scope = "from panels"
    else:
        start, end = panel_range
        scope = f"from panel {start}" if end is None else f"from panels {start} to {end}"
    prompt = (f"Use the reference storyboard to make a full animation movie {scope}. "
              f"{AUDIO_LINE}")
    if extra:
        prompt += f" {extra.strip()}"
    return prompt


def reframe_prompt_with_references(prompt, n_images, n_videos, n_audios,
                                   audio_transcript=None):
    """Ensure each provided reference asset is wired into the prompt by token.

    Seedance 2.0 references assets via tokens: [Image1], [Video1], [Audio1],
    mapped in order to the same-type medias passed to generate_video. Tokens
    already present in the prompt are left untouched; missing ones get a
    neutral reference clause appended. Prefer writing tokens yourself for
    precise semantic control (e.g. "[Image2] stands in the room of [Image1]").
    """
    clauses = []
    missing_imgs = [f"[Image{i}]" for i in range(1, n_images + 1)
                    if f"[Image{i}]" not in prompt]
    if missing_imgs:
        clauses.append(
            f"Use {', '.join(missing_imgs)} as references for character appearance, "
            f"style, and composition.")

    missing_vids = [f"[Video{i}]" for i in range(1, n_videos + 1)
                    if f"[Video{i}]" not in prompt]
    if missing_vids:
        clauses.append(
            f"Use {', '.join(missing_vids)} as references for motion and camera style.")

    missing_auds = [f"[Audio{i}]" for i in range(1, n_audios + 1)
                    if f"[Audio{i}]" not in prompt]
    if missing_auds:
        if audio_transcript:
            clauses.append(f'The subject says {missing_auds[0]}: "{audio_transcript.strip()}".')
        else:
            clauses.append(f"Sync the dialogue/audio from {', '.join(missing_auds)}.")

    if not clauses:
        return prompt
    return prompt.rstrip() + "\n\n" + " ".join(clauses)


def main():
    parser = argparse.ArgumentParser(
        description="Prompt builders for the seedance-2 (Higgsfield) skill.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sb = sub.add_parser(
        "storyboard",
        help="Build the SIMPLE one-liner storyboard->video prompt (fallback; author "
             "the Phase 2 cinematic prompt instead when the board came from Phase 1)")
    sb.add_argument(
        "--panels", "-p", default=None,
        help="Panel range, e.g. '4-6', '4 to 6', or a single '4'. Omit for the full board.")
    sb.add_argument("--extra", default=None,
                    help="Optional extra direction appended after the one-liner")

    rf = sub.add_parser("reframe", help="Wire reference tokens into a prompt")
    rf.add_argument("prompt", nargs="?", help="Base prompt text (or use --prompt-file)")
    rf.add_argument("--prompt-file", help="Read the base prompt from a file")
    rf.add_argument("--images", type=int, default=0, help="Number of reference images")
    rf.add_argument("--videos", type=int, default=0, help="Number of reference videos")
    rf.add_argument("--audios", type=int, default=0, help="Number of reference audios")
    rf.add_argument("--audio-transcript", help="Spoken line woven in for lip-sync")

    args = parser.parse_args()

    if args.command == "storyboard":
        print(build_storyboard_prompt(parse_panel_range(args.panels), extra=args.extra))
        return

    if args.command == "reframe":
        if args.prompt_file:
            import pathlib
            pf = pathlib.Path(args.prompt_file)
            if not pf.exists():
                parser.error(f"--prompt-file not found: {pf}")
            prompt = pf.read_text(encoding="utf-8").strip()
        elif args.prompt:
            prompt = args.prompt
        else:
            parser.error("Provide a prompt or --prompt-file")
        if args.audios and not (args.images or args.videos):
            print("Note: seedance audio references require at least one image or video reference.",
                  file=sys.stderr)
        print(reframe_prompt_with_references(
            prompt, args.images, args.videos, args.audios,
            audio_transcript=args.audio_transcript))
        return


if __name__ == "__main__":
    main()
