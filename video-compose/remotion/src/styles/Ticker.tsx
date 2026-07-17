import React from "react";
import { AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import type { StyleProps } from "../lib/types";

export const Ticker: React.FC<StyleProps> = ({
  text, durMs, width, height, fps, accentColor, textColor, fontFamily,
}) => {
  const frame = useCurrentFrame();
  const { fps: vfps } = useVideoConfig();
  const totalFrames = Math.round((durMs / 1000) * (vfps || fps));

  const enterDur = Math.min(8, totalFrames * 0.12);
  const exitStart = totalFrames - Math.min(8, totalFrames * 0.12);
  const exitDur = totalFrames - exitStart;

  const enterOpacity = interpolate(frame, [0, enterDur], [0, 1], { extrapolateRight: "clamp" });
  const exitOpacity = frame < exitStart
    ? 1
    : interpolate(frame, [exitStart, exitStart + exitDur], [1, 0], { extrapolateRight: "clamp" });
  const opacity = enterOpacity * exitOpacity;

  const repeatedText = ` ${text}  •  ${text}  •  ${text}  •  ${text}  •  ${text} `;

  const isVertical = height >= width;
  const refSide = isVertical ? height : width;
  const fontSize = Math.round(refSide * 0.024);
  const barHeight = Math.round(fontSize * 2.6);
  const bottomOffset = Math.round(height * (isVertical ? 0.04 : 0.035));

  const scrollDist = -width * 0.85;
  const x = interpolate(frame, [0, totalFrames], [0, scrollDist]);

  return (
    <AbsoluteFill style={{ backgroundColor: "transparent" }}>
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          bottom: bottomOffset,
          height: barHeight,
          background: "rgba(0, 0, 0, 0.7)",
          borderTop: `2px solid ${accentColor}`,
          borderBottom: `2px solid ${accentColor}`,
          overflow: "hidden",
          display: "flex",
          alignItems: "center",
          opacity,
        }}
      >
        <div
          style={{
            position: "absolute",
            left: 0,
            top: 0,
            bottom: 0,
            width: 80,
            background: `linear-gradient(to right, rgba(0,0,0,0.85), transparent)`,
            zIndex: 2,
          }}
        />
        <div
          style={{
            position: "absolute",
            right: 0,
            top: 0,
            bottom: 0,
            width: 80,
            background: `linear-gradient(to left, rgba(0,0,0,0.85), transparent)`,
            zIndex: 2,
          }}
        />
        <div
          style={{
            display: "flex",
            whiteSpace: "nowrap",
            transform: `translateX(${x}px)`,
            fontFamily: `${fontFamily}, sans-serif`,
            fontWeight: 700,
            fontSize,
            letterSpacing: 2,
            color: textColor,
            textTransform: "uppercase",
            paddingLeft: 40,
          }}
        >
          {repeatedText}
        </div>
      </div>
    </AbsoluteFill>
  );
};
