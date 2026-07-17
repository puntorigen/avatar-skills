import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import type { StyleProps } from "../lib/types";

export const KineticBurst: React.FC<StyleProps> = ({
  text, durMs, width, height, fps, accentColor, textColor, fontFamily,
}) => {
  const frame = useCurrentFrame();
  const { fps: vfps } = useVideoConfig();
  const totalFrames = Math.round((durMs / 1000) * (vfps || fps));

  const words = text.trim().split(/\s+/).filter(Boolean);
  const wordStaggerFrames = 4;
  const wordEnterFrames = 14;
  const exitStart = totalFrames - Math.min(12, totalFrames * 0.22);
  const exitDur = totalFrames - exitStart;

  const overallExit = frame < exitStart
    ? 1
    : interpolate(frame, [exitStart, exitStart + exitDur], [1, 0], { extrapolateRight: "clamp" });
  const exitScale = frame < exitStart
    ? 1
    : interpolate(frame, [exitStart, exitStart + exitDur], [1, 0.85], { extrapolateRight: "clamp" });

  // Centered burst: in landscape (16:9) size off the LONGER side so the words
  // don't shrink with the short frame height.
  const isVertical = height >= width;
  const refSide = isVertical ? height : width;
  const fontSize = Math.round(refSide * (isVertical ? 0.075 : 0.06));
  const lineHeight = 1.05;

  const accentIndices = words.length >= 4 ? [Math.floor(words.length / 2)] :
                        words.length >= 2 ? [words.length - 1] : [0];

  return (
    <AbsoluteFill
      style={{
        backgroundColor: "transparent",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        opacity: overallExit,
        transform: `scale(${exitScale})`,
      }}
    >
      <div
        style={{
          maxWidth: width * 0.85,
          textAlign: "center",
          display: "flex",
          flexWrap: "wrap",
          justifyContent: "center",
          gap: `${fontSize * 0.18}px ${fontSize * 0.32}px`,
        }}
      >
        {words.map((word, i) => {
          const wordStart = i * wordStaggerFrames;
          const t = spring({
            frame: Math.max(0, frame - wordStart),
            fps: vfps,
            config: { damping: 11, stiffness: 200, mass: 0.7 },
            durationInFrames: wordEnterFrames,
          });
          const translateY = interpolate(t, [0, 1], [60, 0]);
          const scale = interpolate(t, [0, 1], [0.6, 1]);
          const rot = interpolate(t, [0, 1], [(i % 2 === 0 ? -8 : 8), 0]);
          const opacity = t;
          const isAccent = accentIndices.includes(i);

          return (
            <span
              key={i}
              style={{
                display: "inline-block",
                fontFamily: `${fontFamily}, sans-serif`,
                fontWeight: 900,
                fontSize,
                lineHeight,
                color: isAccent ? accentColor : textColor,
                letterSpacing: -1,
                textTransform: "uppercase",
                transform: `translateY(${translateY}px) scale(${scale}) rotate(${rot}deg)`,
                opacity,
                textShadow: "0 4px 14px rgba(0,0,0,0.6), 0 0 2px rgba(0,0,0,0.9)",
                WebkitTextStroke: "1px rgba(0,0,0,0.3)",
              }}
            >
              {word}
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
