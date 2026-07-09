import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import type { StyleProps } from "../lib/types";

export const Fullscreen: React.FC<StyleProps> = ({
  text, durMs, width, height, fps, accentColor, textColor, fontFamily, subtitle,
}) => {
  const frame = useCurrentFrame();
  const { fps: vfps } = useVideoConfig();
  const totalFrames = Math.round((durMs / 1000) * (vfps || fps));

  const enterDur = Math.min(18, totalFrames * 0.3);
  const exitStart = totalFrames - Math.min(14, totalFrames * 0.25);
  const exitDur = totalFrames - exitStart;

  const enterT = spring({
    frame,
    fps: vfps,
    config: { damping: 14, stiffness: 100, mass: 1 },
    durationInFrames: enterDur,
  });
  const enterScale = interpolate(enterT, [0, 1], [1.08, 1]);
  const enterOpacity = enterT;

  const exitOpacity = frame < exitStart
    ? 1
    : interpolate(frame, [exitStart, exitStart + exitDur], [1, 0], { extrapolateRight: "clamp" });
  const exitScale = frame < exitStart
    ? 1
    : interpolate(frame, [exitStart, exitStart + exitDur], [1, 1.08], { extrapolateRight: "clamp" });

  const opacity = enterOpacity * exitOpacity;
  const scale = enterScale * exitScale;

  const fontSize = Math.round(height * 0.085);
  const subFontSize = Math.round(height * 0.024);
  const isVertical = height >= width;
  const accentBarWidth = Math.min(width * 0.18, 260);
  const accentBarHeight = Math.max(4, Math.round(height * 0.005));

  return (
    <AbsoluteFill
      style={{
        backgroundColor: "transparent",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        opacity,
      }}
    >
      <div
        style={{
          textAlign: "center",
          maxWidth: width * 0.9,
          padding: `0 ${Math.round(width * 0.05)}px`,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: 24,
          transform: `scale(${scale})`,
        }}
      >
        <div
          style={{
            width: accentBarWidth,
            height: accentBarHeight,
            background: accentColor,
            borderRadius: accentBarHeight / 2,
            transform: `scaleX(${enterT})`,
            transformOrigin: "center",
          }}
        />
        <div
          style={{
            fontFamily: `${fontFamily}, sans-serif`,
            fontWeight: 900,
            fontSize: isVertical ? fontSize : Math.round(fontSize * 0.85),
            lineHeight: 1.05,
            letterSpacing: -1.5,
            color: textColor,
            textShadow: "0 6px 24px rgba(0,0,0,0.5), 0 0 1px rgba(0,0,0,0.8)",
            textTransform: "uppercase",
          }}
        >
          {text}
        </div>
        {subtitle ? (
          <div
            style={{
              fontFamily: `${fontFamily}, sans-serif`,
              fontWeight: 500,
              fontSize: subFontSize,
              color: "rgba(255,255,255,0.85)",
              letterSpacing: 1.5,
              textTransform: "uppercase",
              textShadow: "0 2px 6px rgba(0,0,0,0.4)",
            }}
          >
            {subtitle}
          </div>
        ) : null}
      </div>
    </AbsoluteFill>
  );
};
