import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";

export type OutroProps = {
  sub: string;       // small line under the layout, e.g. channel promise
  accent: string;
  bg: string;
  durationInFrames?: number;
};

export const outroDefaults: OutroProps = {
  sub: "New evidence-based health breakdowns every week",
  accent: "#38bdf8",
  bg: "#0a0f1a",
};

// YouTube end-screen-friendly end card: a LEFT 16:9 zone (where YouTube drops the
// real next-video card) and a RIGHT circle zone (where the real subscribe button
// lands). We do NOT draw a fake red subscribe button — that would fight YouTube's
// real overlay. Just clean glass placeholders + gentle arrows to guide the eye.
// The spoken outro (comment → subscribe → next) plays OVER this; hard-cut at end.
export const OutroCTA: React.FC<OutroProps> = ({ sub, accent, bg }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  const enter = spring({ frame, fps, config: { damping: 200 }, durationInFrames: 22 });
  const y = interpolate(enter, [0, 1], [40, 0]);
  const op = interpolate(frame, [0, 14], [0, 1], { extrapolateRight: "clamp" });
  const bob = Math.sin((frame / fps) * Math.PI * 2 * 1.1) * 8;

  const glass: React.CSSProperties = {
    background: "rgba(255,255,255,0.05)",
    border: "2px dashed rgba(255,255,255,0.28)",
    backdropFilter: "blur(8px)",
    display: "flex", alignItems: "center", justifyContent: "center",
    color: "rgba(255,255,255,0.55)", fontWeight: 700, letterSpacing: "0.06em",
  };

  return (
    <AbsoluteFill style={{ background: `radial-gradient(circle at 50% 40%, #11203a 0%, ${bg} 70%)`,
      fontFamily: "Inter, Segoe UI, Arial, sans-serif", opacity: op }}>
      <AbsoluteFill style={{ flexDirection: "row", alignItems: "center", justifyContent: "center",
        gap: "6%", transform: `translateY(${y}px)` }}>
        {/* LEFT — next-video zone */}
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 22 }}>
          <div style={{ ...glass, width: 620, height: 349, borderRadius: 18, fontSize: 30 }}>
            ▶  WATCH NEXT
          </div>
          <div style={{ color: "#cbd5e1", fontSize: 30, fontWeight: 600,
            transform: `translateX(${bob}px)` }}>← tap the next video</div>
        </div>
        {/* RIGHT — subscribe zone (circle where YouTube's real button lands) */}
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 22 }}>
          <div style={{ ...glass, width: 300, height: 300, borderRadius: "50%", fontSize: 26,
            boxShadow: `0 0 40px ${accent}33` }}>
            SUBSCRIBE
          </div>
          <div style={{ color: accent, fontSize: 30, fontWeight: 700,
            transform: `translateY(${-bob}px)` }}>↑ one tap</div>
        </div>
      </AbsoluteFill>
      <AbsoluteFill style={{ justifyContent: "flex-end", alignItems: "center", paddingBottom: "6%" }}>
        <div style={{ color: "#94a3b8", fontSize: 34, fontWeight: 500, opacity: op }}>{sub}</div>
      </AbsoluteFill>
    </AbsoluteFill>
  );
};
