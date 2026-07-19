import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

export type IntroProps = {
  title: string;
  subtitle: string;
  accent: string;
  bg: string;
  durationInFrames?: number;
};

export const introDefaults: IntroProps = {
  title: "THE GLP-1 STOMACH TRAP",
  subtitle: "Why your healthy meals make Ozempic nausea worse",
  accent: "#38bdf8",
  bg: "#0a0f1a",
};

// Animated title card: title springs up + accent underline wipes in, subtitle fades.
// Restrained motion (premium documentary), not flashy.
export const IntroCard: React.FC<IntroProps> = ({ title, subtitle, accent, bg }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const titleY = spring({ frame, fps, config: { damping: 200 }, durationInFrames: 24 });
  const titleOpacity = interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" });
  const barW = interpolate(spring({ frame: frame - 8, fps, config: { damping: 200 }, durationInFrames: 26 }), [0, 1], [0, 46]);
  const subOpacity = interpolate(frame, [18, 34], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });

  return (
    <AbsoluteFill style={{ background: bg, justifyContent: "center", alignItems: "center", fontFamily: "Inter, Segoe UI, Arial, sans-serif" }}>
      <div style={{ maxWidth: "78%", textAlign: "center", transform: `translateY(${(1 - titleY) * 40}px)`, opacity: titleOpacity }}>
        <div style={{ fontSize: 96, fontWeight: 900, color: "#fff", lineHeight: 1.04, letterSpacing: "-0.02em", textShadow: "0 6px 28px rgba(0,0,0,0.5)" }}>
          {title}
        </div>
        <div style={{ width: `${barW}%`, height: 8, background: accent, borderRadius: 6, margin: "28px auto 0", boxShadow: `0 0 24px ${accent}` }} />
        <div style={{ fontSize: 40, fontWeight: 500, color: "#cbd5e1", marginTop: 28, opacity: subOpacity }}>
          {subtitle}
        </div>
      </div>
    </AbsoluteFill>
  );
};
