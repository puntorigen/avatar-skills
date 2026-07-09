import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import type { StyleProps } from "../lib/types";

export const LowerThird: React.FC<StyleProps> = ({
  text, durMs, width, height, fps, accentColor, textColor, fontFamily, subtitle,
}) => {
  const frame = useCurrentFrame();
  const { fps: vfps } = useVideoConfig();
  const totalFrames = Math.round((durMs / 1000) * (vfps || fps));

  const enterDur = Math.min(18, totalFrames * 0.25);
  const exitStart = totalFrames - Math.min(14, totalFrames * 0.2);
  const exitDur = totalFrames - exitStart;

  const enterX = spring({
    frame,
    fps: vfps,
    config: { damping: 18, stiffness: 140, mass: 0.9 },
    durationInFrames: enterDur,
  });

  const exitOpacity = frame < exitStart
    ? 1
    : interpolate(frame, [exitStart, exitStart + exitDur], [1, 0], { extrapolateRight: "clamp" });

  const slideX = interpolate(enterX, [0, 1], [-100, 0]);

  const baseFontSize = Math.round(height * 0.045);
  const subFontSize = Math.round(height * 0.026);
  const padX = Math.round(width * 0.04);
  const padY = Math.round(width * 0.025);
  const accentBarWidth = Math.round(width * 0.012);

  const bottomOffset = Math.round(height * 0.18);

  return (
    <AbsoluteFill style={{ backgroundColor: "transparent" }}>
      <div
        style={{
          position: "absolute",
          left: 0,
          bottom: bottomOffset,
          transform: `translateX(${slideX}%)`,
          opacity: exitOpacity,
          display: "flex",
          alignItems: "center",
          gap: padX * 0.6,
          paddingRight: padX * 1.5,
        }}
      >
        <div
          style={{
            width: accentBarWidth,
            height: baseFontSize * (subtitle ? 2.2 : 1.5),
            background: accentColor,
            borderRadius: accentBarWidth / 2,
            marginLeft: padX,
          }}
        />
        <div
          style={{
            background: "rgba(0, 0, 0, 0.55)",
            backdropFilter: "blur(12px)",
            padding: `${padY}px ${padX}px`,
            borderRadius: 12,
            display: "flex",
            flexDirection: "column",
            gap: subtitle ? 6 : 0,
          }}
        >
          <span
            style={{
              fontFamily: `${fontFamily}, sans-serif`,
              fontWeight: 800,
              fontSize: baseFontSize,
              color: textColor,
              lineHeight: 1.05,
              letterSpacing: -0.5,
              textShadow: "0 2px 8px rgba(0,0,0,0.45)",
              whiteSpace: "nowrap",
            }}
          >
            {text}
          </span>
          {subtitle ? (
            <span
              style={{
                fontFamily: `${fontFamily}, sans-serif`,
                fontWeight: 500,
                fontSize: subFontSize,
                color: "rgba(255,255,255,0.85)",
                lineHeight: 1.15,
                letterSpacing: 0.3,
                whiteSpace: "nowrap",
              }}
            >
              {subtitle}
            </span>
          ) : null}
        </div>
      </div>
    </AbsoluteFill>
  );
};
