/**
 * cinemaRig 节奏电影镜头测试（M21.4 TDD）：
 * 纯状态机：cinema mode (off/calm/standard/intense) + beat 事件 →
 * 相机位置 / FOV / 摇晃 / 环绕偏移。
 *
 * 设计：
 * - off：纯零偏移（不干预基础视差 rig）
 * - calm：轻微 dolly zoom（FOV ±2°，慢速正弦呼吸）
 * - standard：环绕（orbitAngle 随 beat 推进）+ 轻 dolly
 * - intense：摇晃（beat 触发衰减震动）+ 强环绕 + dolly zoom
 *
 * 红线（CLAUDE.md §六）：偏移有界、reduced-motion 恒零、无高频闪烁。
 * 纯逻辑测试：无 three / WebGL 依赖。
 */
import { describe, expect, it } from "vitest";

import {
  CINEMA_MAX_DOLLY_Z,
  CINEMA_MAX_FOV_OFFSET,
  CINEMA_MAX_ORBIT_RADIUS,
  CINEMA_MAX_SHAKE,
  createCinemaRig,
  type CinemaMode,
} from "./cinemaRig";

describe("createCinemaRig 基础契约", () => {
  it("初始 mode=off，step 返回全零偏移（不干预基础 rig）", () => {
    const rig = createCinemaRig();
    const s = rig.step(1 / 60, 0);
    expect(s.posX).toBe(0);
    expect(s.posY).toBe(0);
    expect(s.posZ).toBe(0);
    expect(s.fovOffset).toBe(0);
    expect(s.shakeX).toBe(0);
    expect(s.shakeY).toBe(0);
    expect(s.orbitAngle).toBe(0);
  });

  it("getMode 返回当前模式", () => {
    const rig = createCinemaRig();
    expect(rig.getMode()).toBe("off");
    rig.setMode("calm");
    expect(rig.getMode()).toBe("calm");
  });

  it("setMode 幂等：同值不产生副作用", () => {
    const rig = createCinemaRig();
    rig.setMode("standard");
    const s1 = rig.step(1 / 60, 0);
    rig.setMode("standard");
    const s2 = rig.step(1 / 60, 1 / 60);
    // 仅时间推进，mode 切换未触发额外状态变化
    expect(s2.orbitAngle).toBeGreaterThanOrEqual(s1.orbitAngle);
  });

  it("setMode('off') 清零所有偏移（回到基础 rig）", () => {
    const rig = createCinemaRig({ initialMode: "intense" });
    rig.onBeat(2, 0);
    rig.step(1 / 60, 0);
    rig.setMode("off");
    const s = rig.step(1 / 60, 1 / 60);
    expect(s.posX).toBe(0);
    expect(s.posY).toBe(0);
    expect(s.posZ).toBe(0);
    expect(s.fovOffset).toBe(0);
    expect(s.shakeX).toBe(0);
    expect(s.shakeY).toBe(0);
  });

  it("未知 mode 抛 RangeError", () => {
    const rig = createCinemaRig();
    expect(() => rig.setMode("extreme" as CinemaMode)).toThrow(RangeError);
  });
});

describe("calm 模式：轻微 dolly zoom（FOV 呼吸）", () => {
  it("FOV 偏移随时间正弦呼吸，幅度 ≤ CINEMA_MAX_FOV_OFFSET", () => {
    const rig = createCinemaRig({ initialMode: "calm" });
    let maxAbs = 0;
    for (let i = 0; i < 120; i += 1) {
      const s = rig.step(1 / 60, i / 60);
      maxAbs = Math.max(maxAbs, Math.abs(s.fovOffset));
    }
    expect(maxAbs).toBeGreaterThan(0.01); // 确有呼吸
    expect(maxAbs).toBeLessThanOrEqual(CINEMA_MAX_FOV_OFFSET);
  });

  it("calm 不产生摇晃（shake 恒零）", () => {
    const rig = createCinemaRig({ initialMode: "calm" });
    rig.onBeat(2, 0);
    for (let i = 0; i < 10; i += 1) {
      const s = rig.step(1 / 60, i / 60);
      expect(s.shakeX).toBe(0);
      expect(s.shakeY).toBe(0);
    }
  });

  it("calm 不产生环绕偏移（posX/posY 恒零，仅 FOV/Z 呼吸）", () => {
    const rig = createCinemaRig({ initialMode: "calm" });
    for (let i = 0; i < 30; i += 1) {
      const s = rig.step(1 / 60, i / 60);
      expect(s.posX).toBe(0);
      expect(s.posY).toBe(0);
    }
  });
});

describe("standard 模式：环绕 + 轻 dolly", () => {
  it("beat 推进 orbitAngle（环绕角累积）", () => {
    const rig = createCinemaRig({ initialMode: "standard" });
    const before = rig.step(1 / 60, 0).orbitAngle;
    rig.onBeat(1.5, 0);
    const after = rig.step(1 / 60, 1 / 60).orbitAngle;
    expect(after).toBeGreaterThan(before);
  });

  it("环绕产生的 posX/posY 偏移 ≤ CINEMA_MAX_ORBIT_RADIUS", () => {
    const rig = createCinemaRig({ initialMode: "standard" });
    let maxRadius = 0;
    for (let i = 0; i < 60; i += 1) {
      rig.onBeat(1.5, i / 60);
      const s = rig.step(1 / 60, i / 60);
      maxRadius = Math.max(maxRadius, Math.hypot(s.posX, s.posY));
    }
    expect(maxRadius).toBeGreaterThan(0.01);
    expect(maxRadius).toBeLessThanOrEqual(CINEMA_MAX_ORBIT_RADIUS + 1e-6);
  });

  it("standard 不产生摇晃（shake 恒零）", () => {
    const rig = createCinemaRig({ initialMode: "standard" });
    rig.onBeat(2, 0);
    const s = rig.step(1 / 60, 1 / 60);
    expect(s.shakeX).toBe(0);
    expect(s.shakeY).toBe(0);
  });
});

describe("intense 模式：摇晃 + 强环绕 + dolly zoom", () => {
  it("beat 触发摇晃（shake 非零），幅度 ≤ CINEMA_MAX_SHAKE", () => {
    const rig = createCinemaRig({ initialMode: "intense" });
    rig.onBeat(2, 0);
    const s = rig.step(1 / 60, 1 / 60);
    expect(Math.hypot(s.shakeX, s.shakeY)).toBeGreaterThan(0);
    let maxShake = 0;
    for (let i = 0; i < 60; i += 1) {
      rig.onBeat(2, i / 60);
      const f = rig.step(1 / 60, i / 60);
      maxShake = Math.max(maxShake, Math.hypot(f.shakeX, f.shakeY));
    }
    expect(maxShake).toBeLessThanOrEqual(CINEMA_MAX_SHAKE + 1e-6);
  });

  it("beat 后摇晃指数衰减（多帧后归零）", () => {
    const rig = createCinemaRig({ initialMode: "intense" });
    rig.onBeat(3, 0);
    // 渲染 1s 后摇晃应衰减到接近 0
    let lastShake = Number.POSITIVE_INFINITY;
    for (let i = 0; i < 60; i += 1) {
      const s = rig.step(1 / 60, i / 60);
      lastShake = Math.hypot(s.shakeX, s.shakeY);
    }
    expect(lastShake).toBeLessThan(0.01);
  });

  it("intense 环绕半径 > standard（更强电影感）", () => {
    const standard = createCinemaRig({ initialMode: "standard" });
    let standardMax = 0;
    for (let i = 0; i < 60; i += 1) {
      standard.onBeat(2, i / 60);
      const s = standard.step(1 / 60, i / 60);
      standardMax = Math.max(standardMax, Math.hypot(s.posX, s.posY));
    }
    const intense = createCinemaRig({ initialMode: "intense" });
    let intenseMax = 0;
    for (let i = 0; i < 60; i += 1) {
      intense.onBeat(2, i / 60);
      const s = intense.step(1 / 60, i / 60);
      intenseMax = Math.max(intenseMax, Math.hypot(s.posX, s.posY));
    }
    expect(intenseMax).toBeGreaterThan(standardMax);
  });

  it("dolly z 偏移有界 ≤ CINEMA_MAX_DOLLY_Z", () => {
    const rig = createCinemaRig({ initialMode: "intense" });
    let maxAbs = 0;
    for (let i = 0; i < 120; i += 1) {
      rig.onBeat(2, i / 60);
      const s = rig.step(1 / 60, i / 60);
      maxAbs = Math.max(maxAbs, Math.abs(s.posZ));
    }
    expect(maxAbs).toBeLessThanOrEqual(CINEMA_MAX_DOLLY_Z + 1e-6);
  });
});

describe("onBeat 强度语义", () => {
  it("onBeat(0) 不推进 orbit（等效无拍）", () => {
    const rig = createCinemaRig({ initialMode: "standard" });
    const before = rig.step(1 / 60, 0).orbitAngle;
    rig.onBeat(0, 0);
    const after = rig.step(1 / 60, 1 / 60).orbitAngle;
    // 仅时间推进产生的微小角度，无 beat 推进
    expect(after - before).toBeLessThan(0.01);
  });

  it("onBeat NaN 视为 0（不污染状态）", () => {
    const rig = createCinemaRig({ initialMode: "intense" });
    rig.onBeat(Number.NaN, 0);
    const s = rig.step(1 / 60, 1 / 60);
    expect(Math.hypot(s.shakeX, s.shakeY)).toBe(0);
  });

  it("onBeat 钳制 [0,3]，越限值按上限处理", () => {
    const rig = createCinemaRig({ initialMode: "intense" });
    rig.onBeat(99, 0);
    const s = rig.step(1 / 60, 1 / 60);
    const shakeMag = Math.hypot(s.shakeX, s.shakeY);
    // 与 strength=3 等效
    const rig2 = createCinemaRig({ initialMode: "intense" });
    rig2.onBeat(3, 0);
    const s2 = rig2.step(1 / 60, 1 / 60);
    expect(Math.hypot(s2.shakeX, s2.shakeY)).toBeCloseTo(shakeMag, 5);
  });
});

describe("reduced-motion：恒零偏移（光敏防护）", () => {
  it("reduced-motion 初始：intense 模式 + beat 仍全零", () => {
    const rig = createCinemaRig({ initialMode: "intense", reducedMotion: true });
    rig.onBeat(3, 0);
    for (let i = 0; i < 10; i += 1) {
      const s = rig.step(1 / 60, i / 60);
      expect(s.posX).toBe(0);
      expect(s.posY).toBe(0);
      expect(s.posZ).toBe(0);
      expect(s.fovOffset).toBe(0);
      expect(s.shakeX).toBe(0);
      expect(s.shakeY).toBe(0);
      expect(s.orbitAngle).toBe(0);
    }
  });

  it("setReducedMotion(true) 后立即归零（运行时切换）", () => {
    const rig = createCinemaRig({ initialMode: "intense" });
    rig.onBeat(3, 0);
    rig.step(1 / 60, 0);
    rig.setReducedMotion(true);
    const s = rig.step(1 / 60, 1 / 60);
    expect(s.shakeX).toBe(0);
    expect(s.posX).toBe(0);
    expect(s.fovOffset).toBe(0);
  });

  it("setReducedMotion(false) 后恢复模式效果", () => {
    const rig = createCinemaRig({ initialMode: "calm", reducedMotion: true });
    rig.step(1 / 60, 0);
    rig.setReducedMotion(false);
    let hasFov = false;
    for (let i = 0; i < 60; i += 1) {
      const s = rig.step(1 / 60, i / 60);
      if (Math.abs(s.fovOffset) > 0.01) hasFov = true;
    }
    expect(hasFov).toBe(true);
  });
});

describe("模式切换平滑（无瞬跳）", () => {
  it("standard → intense 切换：摇晃从 0 渐入而非瞬跳到最大", () => {
    const rig = createCinemaRig({ initialMode: "standard" });
    rig.step(1 / 60, 0);
    rig.setMode("intense");
    rig.onBeat(2, 1 / 60);
    const s = rig.step(1 / 60, 2 / 60);
    // 切换后首帧摇晃应远低于 MAX_SHAKE（渐入）
    expect(Math.hypot(s.shakeX, s.shakeY)).toBeLessThan(CINEMA_MAX_SHAKE * 0.5);
  });

  it("intense → calm 切换：FOV 呼吸从当前值平滑过渡", () => {
    const rig = createCinemaRig({ initialMode: "intense" });
    for (let i = 0; i < 30; i += 1) {
      rig.onBeat(2, i / 60);
      rig.step(1 / 60, i / 60);
    }
    rig.setMode("calm");
    // 切换后首帧不应产生巨大 FOV 跳变
    const s = rig.step(1 / 60, 30 / 60);
    expect(Math.abs(s.fovOffset)).toBeLessThanOrEqual(CINEMA_MAX_FOV_OFFSET);
  });
});

describe("dispose 语义", () => {
  it("dispose 后 step 返回全零（停止镜头干预）", () => {
    const rig = createCinemaRig({ initialMode: "intense" });
    rig.onBeat(3, 0);
    rig.step(1 / 60, 0);
    rig.dispose();
    const s = rig.step(1 / 60, 1 / 60);
    expect(s.posX).toBe(0);
    expect(s.shakeX).toBe(0);
    expect(s.fovOffset).toBe(0);
  });

  it("dispose 幂等", () => {
    const rig = createCinemaRig();
    expect(() => {
      rig.dispose();
      rig.dispose();
    }).not.toThrow();
  });
});
