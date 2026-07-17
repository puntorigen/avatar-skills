import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import type { StyleProps } from "../lib/types";

export const Badge: React.FC<StyleProps> = ({
  text, durMs, width, height, fps, accentColor, textColor, fontFamily,
}) => {
  const frame = useCurrentFrame();
  const { fps: vfps } = useVideoConfig();
  const totalFrames = Math.round((durMs / 1000) * (vfps || fps));

  const enterDur = Math.min(14, totalFrames * 0.2);
  const exitStart = totalFrames - Math.min(10, totalFrames * 0.15);
  const exitDur = totalFrames - exitStart;

  const enterT = spring({
    frame,
    fps: vfps,
    config: { damping: 14, stiffness: 180, mass: 0.7 },
    durationInFrames: enterDur,
  });
  const enterY = interpolate(enterT, [0, 1], [-30, 0]);
  const enterOpacity = enterT;

  const exitOpacity = frame < exitStart
    ? 1
    : interpolate(frame, [exitStart, exitStart + exitDur], [1, 0], { extrapolateRight: "clamp" });

  const opacity = enterOpacity * exitOpacity;

  const isVertical = height >= width;
  const refSide = isVertical ? height : width;
  const fontSize = Math.round(refSide * 0.022);
  const padX = Math.round(fontSize * 1.2);
  const padY = Math.round(fontSize * 0.5);

  return (
    <AbsoluteFill style={{ backgroundColor: "transparent" }}>
      <div
        style={{
          position: "absolute",
          top: Math.round(height * (isVertical ? 0.05 : 0.06)),
          right: Math.round(width * 0.04),
          display: "flex",
          alignItems: "center",
          gap: 10,
          opacity,
          transform: `translateY(${enterY}px)`,
        }}
      >
        <div
          style={{
            background: "rgba(20, 20, 20, 0.78)",
            backdropFilter: "blur(10px)",
            borderRadius: 999,
            padding: `${padY}px ${padX}px`,
            display: "flex",
            alignItems: "center",
            gap: 10,
            border: `1.5px solid ${accentColor}66`,
          }}
        >
          <div
            style={{
              width: Math.round(fontSize * 0.6),
              height: Math.round(fontSize * 0.6),
              borderRadius: "50%",
              background: accentColor,
              boxShadow: `0 0 ${Math.round(fontSize * 0.6)}px ${accentColor}`,
            }}
          />
          <span
            style={{
              fontFamily: `${fontFamily}, sans-serif`,
              fontWeight: 700,
              fontSize,
              color: textColor,
              letterSpacing: 1.6,
              textTransform: "uppercase",
              whiteSpace: "nowrap",
            }}
          >
            {text}
          </span>
        </div>
      </div>
    </AbsoluteFill>
  );
};
