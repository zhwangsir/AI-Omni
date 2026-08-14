import React from "react";
import {
  AbsoluteFill,
  Audio,
  Img,
  interpolate,
  Sequence,
  staticFile,
  useCurrentFrame,
} from "remotion";

import { ParticleCanvas } from "./particles/ParticleCanvas";
import type { SafeZone } from "./particles/engine";

/**
 * AI-OMNI 项目演示视频（M46 粒子系统重做）
 * Film Atelier 暗房风格：深底、琥珀强调色、克制的淡入淡出与缓动。
 * 粒子：程序化 Canvas 引擎（particles/）——intro 汇聚成球、场景过场涟漪、
 * outro 轨道球，全套纯函数帧驱动，取代 M39 静态 hero 主视觉。
 */

const C = {
  bg: "#0a0a0b",
  amber: "#d4a96a",
  amberDim: "rgba(212,169,106,0.35)",
  text: "#e8e2d9",
  dim: "#8a8378",
};

const FONT =
  '"PingFang SC","Hiragino Sans GB","Microsoft YaHei","Noto Sans SC",sans-serif';

const FADE = 14; // 场景淡入淡出帧数
// M40 配音：旁白在场景内的起始延迟（帧）——与 voiceover_script.VOICEOVER_OFFSET_S 对齐
const VOICEOVER_DELAY = 18;

/** 标题文字安全区（左下 TitleBlock）：粒子在此衰减为零 */
const TITLE_SAFE_ZONE: SafeZone = { x: 500, y: 780, radius: 380, falloff: 300 };
/** 截图说明文字安全区（左下 caption）：过场涟漪在此衰减 */
const CAPTION_SAFE_ZONE: SafeZone = { x: 520, y: 920, radius: 340, falloff: 260 };

/** 场景包装：黑底下淡入淡出，所有转场统一克制处理 */
const Scene: React.FC<{ from: number; duration: number; children: React.ReactNode }> = ({
  from,
  duration,
  children,
}) => {
  const frame = useCurrentFrame();
  const local = frame - from;
  if (local < 0 || local >= duration) return null;
  const opacity = interpolate(
    local,
    [0, FADE, duration - FADE, duration - 1],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  return <AbsoluteFill style={{ backgroundColor: C.bg, opacity }}>{children}</AbsoluteFill>;
};

/** 标题组：kicker 小字 + 主标题 + 副标题，错峰淡入上移 */
const TitleBlock: React.FC<{
  from: number;
  kicker: string;
  title: string;
  subtitle: string;
  titleSize?: number;
}> = ({ from, kicker, title, subtitle, titleSize = 108 }) => {
  const frame = useCurrentFrame();
  const local = frame - from;
  const rise = (delay: number) =>
    interpolate(local - delay, [0, 24], [26, 0], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
  const fade = (delay: number) =>
    interpolate(local - delay, [0, 24], [0, 1], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
  return (
    <div
      style={{
        position: "absolute",
        left: 140,
        bottom: 170,
        fontFamily: FONT,
        color: C.text,
      }}
    >
      <div
        style={{
          opacity: fade(6),
          transform: `translateY(${rise(6)}px)`,
          color: C.amber,
          fontSize: 26,
          letterSpacing: 10,
          marginBottom: 22,
        }}
      >
        {kicker}
      </div>
      <div
        style={{
          opacity: fade(14),
          transform: `translateY(${rise(14)}px)`,
          fontSize: titleSize,
          fontWeight: 700,
          letterSpacing: 14,
          lineHeight: 1.05,
        }}
      >
        {title}
      </div>
      <div
        style={{
          opacity: fade(24),
          transform: `translateY(${rise(24)}px)`,
          marginTop: 26,
          fontSize: 34,
          color: C.dim,
          letterSpacing: 4,
        }}
      >
        {subtitle}
      </div>
    </div>
  );
};

/** 真实截图场景：胶片卡框 + 缓慢缩放 + 左下说明文字 */
const ShotScene: React.FC<{
  from: number;
  img: string;
  kicker: string;
  caption: string;
  vo?: string;
}> = ({ from, img, kicker, caption, vo }) => {
  const frame = useCurrentFrame();
  const local = frame - from;
  const scale = interpolate(local, [0, 230], [0.985, 1.015], {
    extrapolateRight: "clamp",
  });
  const captionOpacity = interpolate(local - 12, [0, 22], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const captionRise = interpolate(local - 12, [0, 22], [18, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <AbsoluteFill
      style={{
        backgroundColor: C.bg,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      {/* M40 雪莉旁白：场景淡入后入场，Sequence 按全局帧定位 */}
      {vo ? (
        <Sequence from={from + VOICEOVER_DELAY}>
          <Audio src={staticFile(`voiceover/${vo}`)} />
        </Sequence>
      ) : null}
      <div
        style={{
          width: 1560,
          borderRadius: 14,
          overflow: "hidden",
          border: `1px solid ${C.amberDim}`,
          boxShadow: "0 30px 90px rgba(0,0,0,0.65)",
          transform: `scale(${scale})`,
        }}
      >
        <Img
          src={staticFile(img)}
          style={{ width: "100%", display: "block" }}
        />
      </div>
      <div
        style={{
          position: "absolute",
          left: 190,
          bottom: 84,
          fontFamily: FONT,
          opacity: captionOpacity,
          transform: `translateY(${captionRise}px)`,
        }}
      >
        <div
          style={{
            color: C.amber,
            fontSize: 22,
            letterSpacing: 8,
            marginBottom: 12,
          }}
        >
          {kicker}
        </div>
        <div style={{ color: C.text, fontSize: 40, letterSpacing: 3 }}>
          {caption}
        </div>
        <div
          style={{
            marginTop: 16,
            width: 64,
            height: 2,
            backgroundColor: C.amber,
          }}
        />
      </div>
    </AbsoluteFill>
  );
};

/** M46 过场涟漪：场景开场自中心向外扩散的显影环带（3.3s 自然消隐） */
const RippleTransition: React.FC<{ from: number; seed: number }> = ({
  from,
  seed,
}) => (
  <ParticleCanvas
    behavior="ripple"
    from={from}
    duration={100}
    count={140}
    seed={seed}
    focal={{ x: 0.5, y: 0.42 }}
    opacity={0.5}
    safeZones={[CAPTION_SAFE_ZONE]}
  />
);

export const Demo: React.FC = () => {
  return (
    <AbsoluteFill style={{ backgroundColor: C.bg }}>
      {/* M40 暗房氛围底乐：全片低音量垫底（ffmpeg 合成 59s drone，首尾淡入淡出已烘焙） */}
      <Audio src={staticFile("bgm-darkroom.mp3")} volume={0.32} />

      {/* Intro 0-149（5s）：星云底 + 粒子汇聚成球 + 标题 */}
      <Scene from={0} duration={150}>
        <ParticleCanvas
          behavior="nebula"
          from={0}
          duration={150}
          count={110}
          seed={7}
          opacity={0.55}
          focal={{ x: 0.62, y: 0.42 }}
          safeZones={[TITLE_SAFE_ZONE]}
        />
        <ParticleCanvas
          behavior="converge"
          from={0}
          duration={150}
          count={260}
          seed={42}
          connections
          focal={{ x: 0.62, y: 0.42 }}
          safeZones={[TITLE_SAFE_ZONE]}
        />
        <TitleBlock
          from={0}
          kicker="LOCAL-FIRST AI ASSISTANT"
          title="AI-OMNI"
          subtitle="本地大脑 · 插件化能力的 AI 全能助手"
        />
        <Sequence from={0 + VOICEOVER_DELAY}>
          <Audio src={staticFile("voiceover/scene-01-intro.wav")} />
        </Sequence>
      </Scene>

      {/* 沉浸空间 150-389（8s） */}
      <Scene from={150} duration={240}>
        <ShotScene
          from={150}
          img="06-field-thinking.png"
          kicker="IMMERSIVE SPACE"
          caption="沉浸式粒子空间 · Three.js 4000 粒子 GPU 分档"
          vo="scene-02-space.wav"
        />
        <RippleTransition from={150} seed={150} />
      </Scene>

      {/* 语音助手 390-629（8s） */}
      <Scene from={390} duration={240}>
        <ShotScene
          from={390}
          img="01-voice-active.png"
          kicker="VOICE PIPELINE"
          caption="语音助手雪莉 · VAD / ASR / TTS 全本地管道"
          vo="scene-03-voice.wav"
        />
        <RippleTransition from={390} seed={390} />
      </Scene>

      {/* 交互井 630-869（8s） */}
      <Scene from={630} duration={240}>
        <ShotScene
          from={630}
          img="02-well-ring-hover.png"
          kicker="WELL ZONE"
          caption="WellZone 交互井 · 悬停显影控制环"
          vo="scene-04-well.wav"
        />
        <RippleTransition from={630} seed={630} />
      </Scene>

      {/* 实时字幕 870-1109（8s） */}
      <Scene from={870} duration={240}>
        <ShotScene
          from={870}
          img="03-well-caption-card.png"
          kicker="LIVE CAPTION"
          caption="实时字幕卡 · ASR 流式上屏"
          vo="scene-05-caption.wav"
        />
        <RippleTransition from={870} seed={870} />
      </Scene>

      {/* 音乐 Dock 1110-1349（8s） */}
      <Scene from={1110} duration={240}>
        <ShotScene
          from={1110}
          img="04-music-dock.png"
          kicker="MUSIC DOCK"
          caption="音乐 Dock · 歌词事件总线联动"
          vo="scene-06-music.wav"
        />
        <RippleTransition from={1110} seed={1110} />
      </Scene>

      {/* 多主题 1350-1589（8s） */}
      <Scene from={1350} duration={240}>
        <ShotScene
          from={1350}
          img="05-theme-safelight-red.png"
          kicker="FILM ATELIER"
          caption="暗房多主题 · 安全灯红"
          vo="scene-07-theme.wav"
        />
        <RippleTransition from={1350} seed={1350} />
      </Scene>

      {/* Outro 1590-1769（6s）：星云底 + 轨道球 + 标题 */}
      <Scene from={1590} duration={180}>
        <ParticleCanvas
          behavior="nebula"
          from={1590}
          duration={180}
          count={100}
          seed={90}
          opacity={0.5}
          focal={{ x: 0.5, y: 0.44 }}
          safeZones={[TITLE_SAFE_ZONE]}
        />
        <ParticleCanvas
          behavior="orbit"
          from={1590}
          duration={180}
          count={250}
          seed={77}
          focal={{ x: 0.5, y: 0.44 }}
          safeZones={[TITLE_SAFE_ZONE]}
        />
        <TitleBlock
          from={1590}
          kicker="AI-OMNI"
          title="隐私优先"
          subtitle="核心数据全本地 · M0–M46 · 4300+ 自动化测试"
          titleSize={88}
        />
        <Sequence from={1590 + VOICEOVER_DELAY}>
          <Audio src={staticFile("voiceover/scene-08-outro.wav")} />
        </Sequence>
      </Scene>
    </AbsoluteFill>
  );
};
