import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import type { StyleProps } from "../lib/types";

export const TagLine: React.FC<StyleProps> = ({
  text, durMs, width, height, fps, accentColor, textColor, fontFamily,
}) => {
  const frame = useCurrentFrame();
  const { fps: vfps } = useVideoConfig();
  const totalFrames = Math.round((durMs / 1000) * (vfps || fps));

  const enterDur = Math.min(20, totalFrames * 0.35);
  const exitStart = totalFrames - Math.min(20, totalFrames * 0.3);
  const exitDur = totalFrames - exitStart;

  const enterOpacity = interpolate(frame, [0, enterDur], [0, 1], {
    extrapolateRight: "clamp",
  });
  const enterY = interpolate(frame, [0, enterDur], [12, 0], {
    extrapolateRight: "clamp",
  });

  const exitOpacity = frame < exitStart
    ? 1
    : interpolate(frame, [exitStart, exitStart + exitDur], [1, 0], { extrapolateRight: "clamp" });

  const opacity = enterOpacity * exitOpacity;

  const fontSize = Math.round(height * 0.034);
  const bottomOffset = Math.round(height * 0.085);

  return (
    <AbsoluteFill style={{ backgroundColor: "transparent" }}>
      <div
        style={{
          position: "absolute",
          bottom: bottomOffset,
          left: 0,
          right: 0,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 18,
          opacity,
          transform: `translateY(${enterY}px)`,
        }}
      >
        <div
          style={{
            width: Math.round(width * 0.06),
            height: 2,
            background: accentColor,
            borderRadius: 1,
          }}
        />
        <div
          style={{
            fontFamily: `${fontFamily}, sans-serif`,
            fontWeight: 300,
            fontSize,
            lineHeight: 1.3,
            color: textColor,
            letterSpacing: 4,
            textTransform: "uppercase",
            textAlign: "center",
            maxWidth: width * 0.85,
            textShadow: "0 2px 10px rgba(0,0,0,0.6)",
          }}
        >
          {text}
        </div>
      </div>
    </AbsoluteFill>
  );
};
