import { Composition } from "remotion";
import { TitleOverlay, TitleOverlayProps } from "./TitleOverlay";

const DEFAULT_PROPS: TitleOverlayProps = {
  text: "Sample title",
  style: "lower_third",
  durMs: 2500,
  width: 1080,
  height: 1920,
  fps: 30,
  accentColor: "#FFD166",
  fontFamily: "Inter",
};

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="TitleOverlay"
        component={TitleOverlay}
        durationInFrames={Math.round((DEFAULT_PROPS.durMs / 1000) * DEFAULT_PROPS.fps)}
        fps={DEFAULT_PROPS.fps}
        width={DEFAULT_PROPS.width}
        height={DEFAULT_PROPS.height}
        defaultProps={DEFAULT_PROPS}
        calculateMetadata={({ props }) => {
          const fps = props.fps ?? 30;
          const durMs = props.durMs ?? 2500;
          const width = props.width ?? 1080;
          const height = props.height ?? 1920;
          return {
            durationInFrames: Math.max(1, Math.round((durMs / 1000) * fps)),
            fps,
            width,
            height,
          };
        }}
      />
    </>
  );
};
