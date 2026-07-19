import { AbsoluteFill, Img, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

export type StatProps = {
  value: number;        // target number to count up to
  prefix: string;       // e.g. "" or "$"
  suffix: string;       // e.g. "%", "X", "g", " min"
  label: string;        // ALL-CAPS caption
  accent: string;
  bgImage?: string;     // optional file:// path to a still/frame behind the stat
  decimals?: number;
  durationInFrames?: number;
};

export const statDefaults: StatProps = {
  value: 50,
  prefix: "",
  suffix: "%",
  label: "SLOWER GASTRIC EMPTYING",
  accent: "#38bdf8",
  decimals: 0,
};

// The kinetic stat done right: the number COUNTS UP (spring) instead of a static
// PNG. Plain white + accent underline (Vfacts-restrained), pops at scene start.
export const StatPop: React.FC<StatProps> = ({ value, prefix, suffix, label, accent, bgImage, decimals = 0 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const prog = spring({ frame, fps, config: { damping: 200 }, durationInFrames: Math.round(fps * 1.1) });
  const shown = (value * prog).toFixed(decimals);
  const rise = interpolate(prog, [0, 1], [26, 0]);
  const opacity = interpolate(frame, [0, 8], [0, 1], { extrapolateRight: "clamp" });
  const barW = interpolate(prog, [0, 1], [0, 38]);

  return (
    <AbsoluteFill style={{ background: bgImage ? "#000" : "#0a0f1a", fontFamily: "Inter, Segoe UI, Arial, sans-serif" }}>
      {bgImage ? <Img src={bgImage} style={{ width: "100%", height: "100%", objectFit: "cover", opacity: 0.85 }} /> : null}
      <AbsoluteFill style={{ justifyContent: "flex-end", alignItems: "flex-start", padding: "0 0 12% 7%" }}>
        <div style={{ opacity, transform: `translateY(${rise}px)` }}>
          <div style={{ fontSize: 200, fontWeight: 800, color: "#fff", lineHeight: 0.95, letterSpacing: "-0.03em",
            textShadow: "0 6px 30px rgba(0,0,0,0.6)", WebkitTextStroke: "2px rgba(0,0,0,0.35)" }}>
            {prefix}{shown}{suffix}
          </div>
          <div style={{ width: `${barW}vw`, height: 10, background: accent, borderRadius: 6, marginTop: 18, boxShadow: `0 0 22px ${accent}` }} />
          <div style={{ fontSize: 46, fontWeight: 700, color: "#fff", marginTop: 22, textTransform: "uppercase",
            letterSpacing: "0.04em", textShadow: "0 3px 14px rgba(0,0,0,0.7)" }}>
            {label}
          </div>
        </div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
