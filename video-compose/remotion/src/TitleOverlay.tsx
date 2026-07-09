import React from "react";
import { AbsoluteFill } from "remotion";
import { LowerThird } from "./styles/LowerThird";
import { KineticBurst } from "./styles/KineticBurst";
import { Fullscreen } from "./styles/Fullscreen";
import { TagLine } from "./styles/TagLine";
import { Badge } from "./styles/Badge";
import { Ticker } from "./styles/Ticker";

export type TitleStyle =
  | "lower_third"
  | "kinetic_burst"
  | "fullscreen"
  | "tag_line"
  | "badge"
  | "ticker";

export interface TitleOverlayProps {
  text: string;
  style: TitleStyle;
  durMs: number;
  width: number;
  height: number;
  fps: number;
  accentColor?: string;
  textColor?: string;
  fontFamily?: string;
  subtitle?: string;
}

export const TitleOverlay: React.FC<TitleOverlayProps> = (props) => {
  const styleProps = {
    text: props.text,
    durMs: props.durMs,
    width: props.width,
    height: props.height,
    fps: props.fps,
    accentColor: props.accentColor ?? "#FFD166",
    textColor: props.textColor ?? "#FFFFFF",
    fontFamily: props.fontFamily ?? "Inter",
    subtitle: props.subtitle,
  };

  return (
    <AbsoluteFill style={{ backgroundColor: "transparent" }}>
      {props.style === "lower_third" && <LowerThird {...styleProps} />}
      {props.style === "kinetic_burst" && <KineticBurst {...styleProps} />}
      {props.style === "fullscreen" && <Fullscreen {...styleProps} />}
      {props.style === "tag_line" && <TagLine {...styleProps} />}
      {props.style === "badge" && <Badge {...styleProps} />}
      {props.style === "ticker" && <Ticker {...styleProps} />}
    </AbsoluteFill>
  );
};
