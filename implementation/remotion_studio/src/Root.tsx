import { Composition } from "remotion";
import { IntroCard, introDefaults } from "./IntroCard";
import { StatPop, statDefaults } from "./StatPop";
import { OutroCTA, outroDefaults } from "./OutroCTA";

const FPS = 30;
const W = 1920;
const H = 1080;

// Each composition is a reusable "scene template" rendered per-scene by
// render_real_video via remotion_render.py. Duration is overridable from props
// (durationInFrames) so a scene matches its narration length.
export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="IntroCard"
        component={IntroCard as any}
        durationInFrames={FPS * 4}
        fps={FPS}
        width={W}
        height={H}
        defaultProps={introDefaults}
        calculateMetadata={({ props }) => ({
          durationInFrames: Math.max(FPS, Math.round((props as any).durationInFrames || FPS * 4)),
        })}
      />
      <Composition
        id="StatPop"
        component={StatPop as any}
        durationInFrames={FPS * 3}
        fps={FPS}
        width={W}
        height={H}
        defaultProps={statDefaults}
        calculateMetadata={({ props }) => ({
          durationInFrames: Math.max(FPS, Math.round((props as any).durationInFrames || FPS * 3)),
        })}
      />
      <Composition
        id="OutroCTA"
        component={OutroCTA as any}
        durationInFrames={FPS * 5}
        fps={FPS}
        width={W}
        height={H}
        defaultProps={outroDefaults}
        calculateMetadata={({ props }) => ({
          durationInFrames: Math.max(FPS, Math.round((props as any).durationInFrames || FPS * 5)),
        })}
      />
    </>
  );
};
