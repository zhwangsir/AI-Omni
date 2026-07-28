/**
 * createSpace 测试（M5.1 契约 + M5.2 集成）：全 fake 后端——注入 fake three 模块，
 * 验证 renderer/scene/camera rig/循环/resize/dispose 契约，以及 M5.2 GPU 粒子集成：
 * 实例数随画质档（high 4000 / low 800）重建不泄漏、morphTo/releaseShape 句柄、
 * 吸引子脉冲与指针激活、reduced-motion 流场时间冻结。
 * 不创建真实 WebGL 上下文（jsdom 无 GPU）。
 */
import { describe, expect, it, vi } from "vitest";

import { ATTRACTOR_BASE_STRENGTH, ATTRACTOR_MAX_STRENGTH } from "./attractor";
import { CINEMA_MAX_ORBIT_RADIUS, CINEMA_MAX_SHAKE } from "./cinemaRig";
import { createSpace } from "./createSpace";
import type { SpaceDeps } from "./createSpace";
import { QUALITY_TIERS, getTierSpec } from "./quality";
import { getTheme } from "../theme/themes";

/**
 * fake three 模块：状态放在闭包 state 对象里，class 访问器全部转发到 state，
 * 这样实现侧对实例的写入（scene.fog = ... / camera.aspect = ...）测试都能读到。
 */
function makeFakeThree() {
  const rendererState = {
    domElement: document.createElement("canvas"),
    setPixelRatio: vi.fn(),
    setSize: vi.fn(),
    setClearColor: vi.fn(),
    render: vi.fn(),
    dispose: vi.fn(),
  };
  const sceneState = {
    add: vi.fn(),
    remove: vi.fn(),
    fog: null as unknown,
    background: null as unknown,
  };
  const cameraState = {
    position: { x: 0, y: 0, z: 8 },
    lookAt: vi.fn(),
    aspect: 1,
    fov: 42 as number, // M21.4 dolly zoom 需要可读写的 fov
    updateProjectionMatrix: vi.fn(),
  };
  const geometryDispose = vi.fn();
  const materialDispose = vi.fn();
  const textureDispose = vi.fn();
  const geometries: FakeInstancedBufferGeometry[] = [];
  const materials: FakeShaderMaterial[] = [];

  class WebGLRenderer {
    domElement = rendererState.domElement;
    setPixelRatio = rendererState.setPixelRatio;
    setSize = rendererState.setSize;
    setClearColor = rendererState.setClearColor;
    render = rendererState.render;
    dispose = rendererState.dispose;
    constructor(public opts: unknown) {}
  }
  class Scene {
    add = sceneState.add;
    remove = sceneState.remove;
    get fog() {
      return sceneState.fog;
    }
    set fog(value: unknown) {
      sceneState.fog = value;
    }
    get background() {
      return sceneState.background;
    }
    set background(value: unknown) {
      sceneState.background = value;
    }
  }
  class PerspectiveCamera {
    position = cameraState.position;
    lookAt = cameraState.lookAt;
    updateProjectionMatrix = cameraState.updateProjectionMatrix;
    constructor(fov: number, aspect: number, public near: number, public far: number) {
      cameraState.aspect = aspect;
      cameraState.fov = fov;
    }
    get aspect() {
      return cameraState.aspect;
    }
    set aspect(value: number) {
      cameraState.aspect = value;
    }
    // M21.4 dolly zoom：fov 读写透传到 cameraState（测试探针可观测）
    get fov(): number {
      return cameraState.fov;
    }
    set fov(value: number) {
      cameraState.fov = value;
    }
  }
  class FakeInstancedBufferAttribute {
    needsUpdate = false;
    constructor(
      public array: Float32Array,
      public itemSize: number,
    ) {}
    get count() {
      return this.array.length / this.itemSize;
    }
  }
  class FakeBufferAttribute {
    constructor(
      public array: Float32Array,
      public itemSize: number,
    ) {}
  }
  class FakeInstancedBufferGeometry {
    instanceCount = 0;
    private attrs = new Map<string, unknown>();
    constructor() {
      geometries.push(this);
    }
    setAttribute(name: string, attr: unknown) {
      this.attrs.set(name, attr);
    }
    getAttribute(name: string) {
      return this.attrs.get(name);
    }
    dispose() {
      geometryDispose();
    }
  }
  class FakeShaderMaterial {
    uniforms: Record<string, { value: unknown }>;
    constructor(public opts: { uniforms?: Record<string, { value: unknown }> }) {
      this.uniforms = opts.uniforms ?? {};
      materials.push(this);
    }
    dispose() {
      materialDispose();
    }
  }
  class FakeDataTexture {
    needsUpdate = false;
    constructor(
      public data: Uint8Array,
      public width: number,
      public height: number,
    ) {}
    dispose() {
      textureDispose();
    }
  }
  class Points {
    constructor(
      public geometry: FakeInstancedBufferGeometry,
      public material: FakeShaderMaterial,
    ) {}
  }
  class Color {
    r = 0;
    g = 0;
    b = 0;
    setRGB(r: number, g: number, b: number) {
      this.r = r;
      this.g = g;
      this.b = b;
      return this;
    }
  }
  class FogExp2 {
    constructor(
      public color: unknown,
      public density: number,
    ) {}
  }
  // M23.3 AmbientLight：记录 color.setRGB 调用 + 可写 intensity（测试探针可观测）
  const ambientLights: FakeAmbientLight[] = [];
  class FakeAmbientLight {
    color = new Color();
    intensity = 1;
    constructor() {
      ambientLights.push(this);
    }
  }

  return {
    WebGLRenderer,
    Scene,
    PerspectiveCamera,
    InstancedBufferGeometry: FakeInstancedBufferGeometry,
    InstancedBufferAttribute: FakeInstancedBufferAttribute,
    BufferAttribute: FakeBufferAttribute,
    DataTexture: FakeDataTexture,
    ShaderMaterial: FakeShaderMaterial,
    Points,
    Color,
    FogExp2,
    AmbientLight: FakeAmbientLight,
    AdditiveBlending: 2,
    __spy: {
      renderer: rendererState,
      scene: sceneState,
      camera: cameraState,
      geometryDispose,
      materialDispose,
      textureDispose,
      geometries,
      materials,
      ambientLights,
    },
  };
}

type FakeThree = ReturnType<typeof makeFakeThree>;

/** 当前粒子 Points 的 uniforms（取最后一个被 add 的带 material 的对象）。 */
function particleUniforms(fake: FakeThree): Record<string, { value: unknown }> {
  return fake.__spy.materials[0]!.uniforms;
}

function makeDeps(overrides?: Partial<SpaceDeps>): {
  deps: SpaceDeps;
  fake: FakeThree;
  pumpFrames: (n: number) => void;
} {
  const fake = makeFakeThree();
  let now = 0;
  const queue: FrameRequestCallback[] = [];
  const deps: SpaceDeps = {
    three: fake as unknown as SpaceDeps["three"],
    width: 1280,
    height: 800,
    devicePixelRatio: 2,
    now: () => now,
    requestFrame: (cb) => {
      queue.push(cb);
      return queue.length;
    },
    cancelFrame: vi.fn(),
    ...overrides,
  };
  return {
    deps,
    fake,
    pumpFrames: (n: number) => {
      for (let i = 0; i < n; i++) {
        const cb = queue.shift();
        if (!cb) return;
        now += 16.7;
        cb(now);
      }
    },
  };
}

describe("createSpace 初始化契约", () => {
  it("创建 renderer 并挂到容器，画布 class 为 immersive-space", () => {
    const { deps } = makeDeps();
    const container = document.createElement("div");
    const space = createSpace(deps, container);
    expect(container.children).toHaveLength(1);
    const canvas = container.children[0] as HTMLElement;
    expect(canvas.classList.contains("immersive-space")).toBe(true);
    space.dispose();
  });

  it("renderer 按 DPR 与尺寸初始化（setPixelRatio/setSize）", () => {
    const { deps, fake } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    expect(fake.__spy.renderer.setPixelRatio).toHaveBeenCalledWith(2);
    expect(fake.__spy.renderer.setSize).toHaveBeenCalledWith(1280, 800);
    space.dispose();
  });

  it("画布不拦截指针（pointer-events: none）", () => {
    const { deps } = makeDeps();
    const container = document.createElement("div");
    const space = createSpace(deps, container);
    const canvas = container.children[0] as HTMLElement;
    expect(canvas.style.pointerEvents).toBe("none");
    space.dispose();
  });

  it("GPU 粒子系统加入场景：实例数 = high 档 4000，实例属性齐备", () => {
    const { deps, fake } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    expect(fake.__spy.scene.add).toHaveBeenCalled();
    const geometry = fake.__spy.geometries[0]!;
    expect(geometry.instanceCount).toBe(getTierSpec("high").particleCount);
    for (const name of ["aSeed", "aVelocity", "aSize", "aColorIndex", "aPhase", "aTarget"]) {
      expect(geometry.getAttribute(name)).toBeDefined();
    }
    space.dispose();
  });

  it("创建即按当前主题设置雾（scene.fog 非空），色板 uniform 写入 6 槽", () => {
    const { deps, fake } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    expect(fake.__spy.scene.fog).not.toBeNull();
    const palette = particleUniforms(fake).uPalette!.value as Float32Array;
    expect(palette.length).toBe(18);
    // 默认主题第一槽为显影琥珀 accent #c9a86a
    expect(palette[0]).toBeCloseTo(0xc9 / 255, 3);
    expect(palette[1]).toBeCloseTo(0xa8 / 255, 3);
    expect(palette[2]).toBeCloseTo(0x6a / 255, 3);
    space.dispose();
  });
});

describe("createSpace 帧循环与相机 rig", () => {
  it("每帧渲染一次（renderer.render 被调用）", () => {
    const { deps, fake, pumpFrames } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    pumpFrames(3);
    expect(fake.__spy.renderer.render.mock.calls.length).toBeGreaterThanOrEqual(1);
    space.dispose();
  });

  it("相机随指针缓动视差：setPointer 后位置逐帧逼近目标并收敛", () => {
    const { deps, fake, pumpFrames } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    const x0 = fake.__spy.camera.position.x;
    space.setPointer(1, 0);
    pumpFrames(30);
    const x1 = fake.__spy.camera.position.x;
    expect(x1).toBeGreaterThan(x0);
    pumpFrames(300);
    const x2 = fake.__spy.camera.position.x;
    expect(x2).toBeGreaterThanOrEqual(x1);
    expect(Number.isFinite(x2)).toBe(true);
    expect(fake.__spy.camera.lookAt).toHaveBeenCalled();
    space.dispose();
  });

  it("setPointer 越界输入被钳制到 [-1, 1]，非法值抛 RangeError", () => {
    const { deps, fake, pumpFrames } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    expect(() => space.setPointer(Number.NaN, 0)).toThrow(RangeError);
    space.setPointer(5, 0); // 钳制到 1，不得爆掉
    pumpFrames(400);
    const x = fake.__spy.camera.position.x;
    expect(Number.isFinite(x)).toBe(true);
    expect(x).toBeLessThanOrEqual(1.5); // 视差偏移有界
    space.dispose();
  });

  it("reducedMotion：只渲染一帧静态画面，泵帧不再渲染、相机不漂移、流场时间冻结", () => {
    const { deps, fake, pumpFrames } = makeDeps();
    const space = createSpace(deps, document.createElement("div"), { reducedMotion: true });
    expect(fake.__spy.renderer.render).toHaveBeenCalledTimes(1); // 静态一帧
    const frozenTime = particleUniforms(fake).uFlowTime!.value as number;
    space.setPointer(1, 0);
    pumpFrames(5);
    expect(fake.__spy.renderer.render).toHaveBeenCalledTimes(1);
    expect(fake.__spy.camera.position.x).toBe(0);
    expect(particleUniforms(fake).uFlowTime!.value).toBe(frozenTime); // 时间冻结
    space.dispose();
  });

  it("setReducedMotion(false) 后恢复帧循环，流场时间继续前进", () => {
    const { deps, fake, pumpFrames } = makeDeps();
    const space = createSpace(deps, document.createElement("div"), { reducedMotion: true });
    expect(fake.__spy.renderer.render).toHaveBeenCalledTimes(1);
    const frozenTime = particleUniforms(fake).uFlowTime!.value as number;
    space.setReducedMotion(false);
    pumpFrames(3);
    expect(fake.__spy.renderer.render.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(particleUniforms(fake).uFlowTime!.value as number).toBeGreaterThan(frozenTime);
    space.dispose();
  });
});

describe("createSpace 画质档与 resize", () => {
  it("resize 后相机 aspect 与 renderer 尺寸同步更新", () => {
    const { deps, fake } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    space.resize(640, 480);
    expect(fake.__spy.renderer.setSize).toHaveBeenCalledWith(640, 480);
    expect(fake.__spy.camera.aspect).toBeCloseTo(640 / 480, 5);
    expect(fake.__spy.camera.updateProjectionMatrix).toHaveBeenCalled();
    space.dispose();
  });

  it("resize 非法尺寸抛 RangeError", () => {
    const { deps } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    expect(() => space.resize(0, 480)).toThrow(RangeError);
    expect(() => space.resize(640, Number.NaN)).toThrow(RangeError);
    space.dispose();
  });

  it("setQuality 接受合法档，非法档抛 RangeError", () => {
    const { deps } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    for (const tier of QUALITY_TIERS) {
      expect(() => space.setQuality(tier)).not.toThrow();
    }
    expect(() => space.setQuality("ultra" as never)).toThrow(RangeError);
    space.dispose();
  });

  it("low 档把 pixelRatio 压到 ≤1，high 档用完整 DPR", () => {
    const { deps, fake } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    fake.__spy.renderer.setPixelRatio.mockClear();
    space.setQuality("low");
    const lowCall = fake.__spy.renderer.setPixelRatio.mock.calls.at(-1)![0] as number;
    expect(lowCall).toBeLessThanOrEqual(1);
    space.setQuality("high");
    const highCall = fake.__spy.renderer.setPixelRatio.mock.calls.at(-1)![0] as number;
    expect(highCall).toBe(2);
    space.dispose();
  });

  it("画质档切换重建粒子实例数（4000→800），旧 geometry 释放、material 复用不闪断", () => {
    const { deps, fake } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    expect(fake.__spy.geometries[0]!.instanceCount).toBe(4000);
    space.setQuality("low");
    expect(fake.__spy.geometries).toHaveLength(2);
    expect(fake.__spy.geometries[1]!.instanceCount).toBe(800);
    expect(fake.__spy.geometryDispose).toHaveBeenCalledTimes(1); // 旧 geometry 释放
    expect(fake.__spy.materialDispose).not.toHaveBeenCalled(); // 材质未换 → uniform 连续
    space.setQuality("high");
    expect(fake.__spy.geometries[2]!.instanceCount).toBe(4000);
    space.dispose();
  });
});

describe("createSpace M5.2 交互句柄（morph / release / pulse）", () => {
  it("morphTo 后 uMorphFactor 缓动上升，≥600ms 后收敛到 1；releaseShape 缓动回 0", () => {
    const { deps, fake, pumpFrames } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    pumpFrames(2);
    space.morphTo("sphere");
    pumpFrames(3); // ~50ms：过渡已开始但未完成（禁瞬跳）
    const mid = particleUniforms(fake).uMorphFactor!.value as number;
    expect(mid).toBeGreaterThan(0);
    expect(mid).toBeLessThan(0.5);
    pumpFrames(60); // ~1s：收敛
    expect(particleUniforms(fake).uMorphFactor!.value).toBe(1);
    space.releaseShape();
    pumpFrames(60);
    expect(particleUniforms(fake).uMorphFactor!.value).toBe(0);
    space.dispose();
  });

  it("morphTo 未知形状抛 RangeError", () => {
    const { deps } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    expect(() => space.morphTo("cube" as never)).toThrow(RangeError);
    space.dispose();
  });

  it("pulseAttractor 抬升 uAttractorStrength（≤ MAX）并随时间衰减", () => {
    const { deps, fake, pumpFrames } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    pumpFrames(2);
    expect(particleUniforms(fake).uAttractorStrength!.value).toBe(0); // 无指针 → 纯流场
    space.pulseAttractor();
    pumpFrames(2);
    const boosted = particleUniforms(fake).uAttractorStrength!.value as number;
    expect(boosted).toBeGreaterThan(0.5);
    expect(boosted).toBeLessThanOrEqual(ATTRACTOR_MAX_STRENGTH);
    pumpFrames(600); // ~10s 脉冲消散
    expect(particleUniforms(fake).uAttractorStrength!.value as number).toBeLessThan(0.05);
    space.dispose();
  });

  it("setPointer 激活吸引子：强度升到基础值，位置 uniform 朝指针世界坐标移动", () => {
    const { deps, fake, pumpFrames } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    pumpFrames(2);
    space.setPointer(0.8, 0);
    pumpFrames(5);
    const uniforms = particleUniforms(fake);
    expect(uniforms.uAttractorStrength!.value).toBeCloseTo(ATTRACTOR_BASE_STRENGTH, 3);
    const pos = uniforms.uAttractor!.value as { x: number; y: number; z: number };
    expect(pos.x).toBeGreaterThan(0.05); // 朝 +x 移动（未瞬移到位）
    space.dispose();
  });

  it("reduced-motion 下 morphTo / pulseAttractor 为空操作（静止降级）", () => {
    const { deps, fake, pumpFrames } = makeDeps();
    const space = createSpace(deps, document.createElement("div"), { reducedMotion: true });
    space.morphTo("sphere");
    space.pulseAttractor();
    pumpFrames(5);
    expect(particleUniforms(fake).uMorphFactor!.value).toBe(0);
    expect(particleUniforms(fake).uAttractorStrength!.value).toBe(0);
    space.dispose();
  });

  it("setField 设置持久形态后，点击 morphTo/releaseShape 不覆盖场形态", () => {
    const { deps, fake, pumpFrames } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    pumpFrames(2);
    // field 设置球体持久形态
    space.setField({
      dimFactor: 1,
      brightnessLift: 0,
      attractor: null,
      orbit: null,
      flowline: null,
      ripple: null,
      dormant: false,
      particleShape: "sphere",
      pulseStrength: 0,
      helixRotSpeed: 0,
      flickerIntensity: 0,
      flickerSpeed: 0,
      glowBoost: 0,
      sphereScale: 1,
    });
    pumpFrames(60); // ~1s 让 morph 收敛
    expect(particleUniforms(fake).uMorphFactor!.value).toBe(1);
    // 点击尝试 morph 到另一个形状——不应改变形态（field 拥有形态权）
    space.morphTo("ring");
    pumpFrames(30);
    expect(particleUniforms(fake).uMorphFactor!.value).toBe(1); // 形态保持不变
    // 点击尝试 releaseShape——不应释放
    space.releaseShape();
    pumpFrames(30);
    expect(particleUniforms(fake).uMorphFactor!.value).toBe(1); // 形态仍保持
    space.dispose();
  });

  it("setField 释放形态（particleShape=null）后，点击 morphTo/releaseShape 恢复正常", () => {
    const { deps, fake, pumpFrames } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    pumpFrames(2);
    // field 先设球体
    space.setField({
      dimFactor: 1,
      brightnessLift: 0,
      attractor: null,
      orbit: null,
      flowline: null,
      ripple: null,
      dormant: false,
      particleShape: "sphere",
      pulseStrength: 0,
      helixRotSpeed: 0,
      flickerIntensity: 0,
      flickerSpeed: 0,
      glowBoost: 0,
      sphereScale: 1,
    });
    pumpFrames(60);
    expect(particleUniforms(fake).uMorphFactor!.value).toBe(1);
    // field 释放形态回到 idle
    space.setField({
      dimFactor: 1,
      brightnessLift: 0,
      attractor: null,
      orbit: null,
      flowline: null,
      ripple: null,
      dormant: false,
      particleShape: null,
      pulseStrength: 0,
      helixRotSpeed: 0,
      flickerIntensity: 0,
      flickerSpeed: 0,
      glowBoost: 0,
      sphereScale: 1,
    });
    pumpFrames(60);
    expect(particleUniforms(fake).uMorphFactor!.value).toBe(0); // 已释放
    // 点击 morphTo 恢复正常工作
    space.morphTo("helix");
    pumpFrames(60);
    expect(particleUniforms(fake).uMorphFactor!.value).toBe(1);
    // releaseShape 正常释放
    space.releaseShape();
    pumpFrames(60);
    expect(particleUniforms(fake).uMorphFactor!.value).toBe(0);
    space.dispose();
  });

  it("releaseShape 释放后 currentShape 同步置 null，后续 setField 同形可重新触发 morph", () => {
    const { deps, fake, pumpFrames } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    pumpFrames(2);
    space.morphTo("sphere");
    pumpFrames(60);
    expect(particleUniforms(fake).uMorphFactor!.value).toBe(1);
    space.releaseShape();
    pumpFrames(60);
    expect(particleUniforms(fake).uMorphFactor!.value).toBe(0);
    // setField 设置球体（之前 click 聚集过的同形状）应能重新 morph
    space.setField({
      dimFactor: 1,
      brightnessLift: 0,
      attractor: null,
      orbit: null,
      flowline: null,
      ripple: null,
      dormant: false,
      particleShape: "sphere",
      pulseStrength: 0,
      helixRotSpeed: 0,
      flickerIntensity: 0,
      flickerSpeed: 0,
      glowBoost: 0,
      sphereScale: 1,
    });
    pumpFrames(60);
    expect(particleUniforms(fake).uMorphFactor!.value).toBe(1);
    space.dispose();
  });

  it("setField 形态间切换（sphere→dna_helix）走形状混合直接插值，不消散（morphFactor 保持 1）", () => {
    const { deps, fake, pumpFrames } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    pumpFrames(2);
    // 先设球体，完全成形
    space.setField({
      dimFactor: 1, brightnessLift: 0, attractor: null, orbit: null,
      flowline: null, ripple: null, dormant: false,
      particleShape: "sphere", pulseStrength: 0, helixRotSpeed: 0,
      flickerIntensity: 0, flickerSpeed: 0, glowBoost: 0, sphereScale: 1,
    });
    pumpFrames(60);
    expect(particleUniforms(fake).uMorphFactor!.value).toBe(1);
    // 切换到 dna_helix：morph factor 应保持为 1（不消散回 0）
    space.setField({
      dimFactor: 1, brightnessLift: 0, attractor: null, orbit: null,
      flowline: null, ripple: null, dormant: false,
      particleShape: "dna_helix", pulseStrength: 0, helixRotSpeed: 1.0,
      flickerIntensity: 0, flickerSpeed: 0, glowBoost: 0, sphereScale: 1,
    });
    // 切换后立即（1帧）：factor 仍为 1，不消散
    pumpFrames(1);
    expect(particleUniforms(fake).uMorphFactor!.value).toBe(1);
    // 过渡中期（~400ms / 25 帧）：factor 仍为 1，但形状在混合中
    pumpFrames(24);
    expect(particleUniforms(fake).uMorphFactor!.value).toBe(1);
    // 过渡完成后（~900ms / 55 帧）：factor 仍为 1，形状已落位
    pumpFrames(30);
    expect(particleUniforms(fake).uMorphFactor!.value).toBeCloseTo(1, 5);
    space.dispose();
  });

  it("setField 从空闲（null）首次设形态走普通 morphTo（无需 reset）", () => {
    const { deps, fake, pumpFrames } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    pumpFrames(2);
    expect(particleUniforms(fake).uMorphFactor!.value).toBe(0);
    // 首次设球体
    space.setField({
      dimFactor: 1, brightnessLift: 0, attractor: null, orbit: null,
      flowline: null, ripple: null, dormant: false,
      particleShape: "sphere", pulseStrength: 0, helixRotSpeed: 0,
      flickerIntensity: 0, flickerSpeed: 0, glowBoost: 0, sphereScale: 1,
    });
    pumpFrames(1);
    // 首次 morph 从当前 factor（0）开始，起始接近 0
    expect(particleUniforms(fake).uMorphFactor!.value).toBeLessThan(0.1);
    pumpFrames(60);
    expect(particleUniforms(fake).uMorphFactor!.value).toBeCloseTo(1, 5);
    space.dispose();
  });
});

describe("createSpace dispose 与主题", () => {
  it("dispose 移除画布、停止循环、释放 geometry/material/texture/renderer，且幂等", () => {
    const { deps, fake, pumpFrames } = makeDeps();
    const container = document.createElement("div");
    const space = createSpace(deps, container);
    space.dispose();
    expect(container.children).toHaveLength(0);
    expect(fake.__spy.geometryDispose).toHaveBeenCalled();
    expect(fake.__spy.materialDispose).toHaveBeenCalled();
    expect(fake.__spy.textureDispose).toHaveBeenCalled();
    expect(fake.__spy.renderer.dispose).toHaveBeenCalled();
    pumpFrames(3); // dispose 后不应再有渲染
    expect(fake.__spy.renderer.render).not.toHaveBeenCalled();
    expect(() => space.dispose()).not.toThrow(); // 幂等
    expect(fake.__spy.renderer.dispose).toHaveBeenCalledTimes(1);
  });

  it("applyTheme 不抛错并保持雾非空；色板 uniform 随 260ms 过渡插值", () => {
    const { deps, fake, pumpFrames } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    const before = (particleUniforms(fake).uPalette!.value as Float32Array)[0]!;
    space.applyTheme(getTheme("silver-gray"));
    pumpFrames(2); // 过渡中：色板已开始插值但未完成
    const mid = (particleUniforms(fake).uPalette!.value as Float32Array)[0]!;
    expect(mid).not.toBeCloseTo(before, 5);
    expect(fake.__spy.scene.fog).not.toBeNull();
    pumpFrames(30); // 过渡完成
    expect(fake.__spy.scene.fog).not.toBeNull();
    space.dispose();
  });
});

/** fake postfx 模块：捕获 bloom 实例供 mood 微升断言。 */
function makeFakePostfx() {
  const blooms: { strength: number; radius: number; threshold: number }[] = [];
  class WebGLRenderTarget {
    dispose = (): void => {};
    constructor(
      public width: number,
      public height: number,
      public options?: unknown,
    ) {}
  }
  class EffectComposer {
    addPass(): void {}
    setSize(): void {}
    setPixelRatio(): void {}
    render(): void {}
    dispose(): void {}
    constructor(public renderer: unknown, public renderTarget?: unknown) {}
  }
  class RenderPass {
    constructor(
      public scene: unknown,
      public camera: unknown,
    ) {}
  }
  class UnrealBloomPass {
    strength: number;
    radius: number;
    threshold: number;
    constructor(
      public resolution: { x: number; y: number },
      strength: number,
      radius: number,
      threshold: number,
    ) {
      this.strength = strength;
      this.radius = radius;
      this.threshold = threshold;
      blooms.push(this);
    }
  }
  class ShaderPass {
    uniforms: Record<string, { value: unknown }>;
    constructor(public shader: { uniforms?: Record<string, { value: unknown }> }) {
      // 继承 shader 声明的 uniforms（含 M21.8 chromaticAberration/vignetteBreath/breathPhase），
      // 否则 postfx.render 写入新 uniform 时会因 key 缺失抛 TypeError。
      this.uniforms = shader.uniforms ?? {
        vignetteStrength: { value: 0 },
        grainAmount: { value: 0 },
        grainTime: { value: 0 },
      };
    }
  }
  class OutputPass {}
  return {
    modules: {
      WebGLRenderTarget,
      HalfFloatType: 1,
      RGBAFormat: 2,
      LinearFilter: 1,
      LinearSRGBColorSpace: "srgb-linear",
      EffectComposer,
      RenderPass,
      UnrealBloomPass,
      ShaderPass,
      OutputPass,
    },
    blooms,
  };
}

describe("createSpace M5.3 交互句柄（addRipple / setMood）", () => {
  it("addRipple 写入 origin 与秒制时间 uniform，uNowSec 随帧推进", () => {
    const { deps, fake, pumpFrames } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    pumpFrames(1); // now = 16.7ms
    space.addRipple({ x: 1, y: 0.5, z: 0 });
    pumpFrames(2); // now = 50.1ms
    const origins = particleUniforms(fake).uRippleOrigins!.value as Float32Array;
    const times = particleUniforms(fake).uRippleTimes!.value as Float32Array;
    expect(origins[0]).toBe(1);
    expect(origins[1]).toBe(0.5);
    expect(origins[2]).toBe(0);
    expect(times[0]).toBeCloseTo(0.0167, 4); // 入队时刻转秒
    expect(times[1]).toBeCloseTo(2, 5); // 默认生命周期 2s（≥1200ms 慢速下限）
    expect(particleUniforms(fake).uNowSec!.value).toBeCloseTo(0.0501, 4);
    space.dispose();
  });

  it("波纹过期自动出队：2s 后 uniform 槽位生命周期清零", () => {
    const { deps, fake, pumpFrames } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    pumpFrames(1);
    space.addRipple({ x: 0, y: 0, z: 0 });
    pumpFrames(60); // ~1s：仍在生命期内
    expect((particleUniforms(fake).uRippleTimes!.value as Float32Array)[1]).toBeCloseTo(2, 5);
    pumpFrames(65); // ~2.1s：已过期
    expect((particleUniforms(fake).uRippleTimes!.value as Float32Array)[1]).toBe(0);
    space.dispose();
  });

  it("addRipple 非法坐标抛 RangeError", () => {
    const { deps } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    expect(() => space.addRipple({ x: Number.NaN, y: 0 })).toThrow(RangeError);
    space.dispose();
  });

  it("reduced-motion 下 addRipple 零产生（槽位保持空闲）", () => {
    const { deps, fake, pumpFrames } = makeDeps();
    const space = createSpace(deps, document.createElement("div"), { reducedMotion: true });
    space.addRipple({ x: 1, y: 1, z: 0 });
    pumpFrames(3);
    const times = particleUniforms(fake).uRippleTimes!.value as Float32Array;
    expect(times[1]).toBe(0);
    space.dispose();
  });

  it("setMood(speaking) 流场提速且 bloom 微升；回基线后双双恢复", () => {
    const postfx = makeFakePostfx();
    const { deps, fake, pumpFrames } = makeDeps({
      postfx: postfx.modules as unknown as SpaceDeps["postfx"],
    });
    const space = createSpace(deps, document.createElement("div"));
    const uniforms = particleUniforms(fake);
    pumpFrames(2);
    // 基线流速：60 帧 ~1s 的 uFlowTime 增量
    const t1 = uniforms.uFlowTime!.value as number;
    pumpFrames(60);
    const baselineDelta = (uniforms.uFlowTime!.value as number) - t1;
    const baselineBloom = postfx.blooms[0]!.strength;
    // speaking：流速明显快于基线（×≤2.0），bloom 微升
    space.setMood({ flowScale: 1.8, bloomBoost: 0.08 });
    const t2 = uniforms.uFlowTime!.value as number;
    pumpFrames(60);
    const speakingDelta = (uniforms.uFlowTime!.value as number) - t2;
    expect(speakingDelta).toBeGreaterThan(baselineDelta * 1.5);
    expect(speakingDelta).toBeLessThan(baselineDelta * 2.05);
    expect(postfx.blooms[0]!.strength).toBeGreaterThan(baselineBloom);
    // 回基线：双双恢复
    space.setMood(null);
    pumpFrames(80); // 流速缓动收敛
    const t3 = uniforms.uFlowTime!.value as number;
    pumpFrames(60);
    const restoredDelta = (uniforms.uFlowTime!.value as number) - t3;
    expect(restoredDelta).toBeLessThan(baselineDelta * 1.3);
    expect(postfx.blooms[0]!.strength).toBeCloseTo(baselineBloom, 5);
    space.dispose();
  });

  it("setMood 倍率硬钳制：越限输入被钳到上限内", () => {
    const { deps, fake, pumpFrames } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    const uniforms = particleUniforms(fake);
    pumpFrames(2);
    space.setMood({ flowScale: 99, bloomBoost: 99 });
    const t1 = uniforms.uFlowTime!.value as number;
    pumpFrames(120); // 缓动收敛后测速
    const t2 = uniforms.uFlowTime!.value as number;
    pumpFrames(60);
    const delta = (uniforms.uFlowTime!.value as number) - t2;
    void t1;
    // ×99 被钳到 ≤×2.0：1s 增量 < 2.05s 等效
    expect(delta).toBeLessThan(2.05);
    expect(delta).toBeGreaterThan(1.5); // 但仍为上限档活跃
    space.dispose();
  });

  it("reduced-motion 下 setMood 恒基线：流速冻结、bloom 不升", () => {
    const postfx = makeFakePostfx();
    const { deps, fake, pumpFrames } = makeDeps({
      postfx: postfx.modules as unknown as SpaceDeps["postfx"],
    });
    const space = createSpace(deps, document.createElement("div"), { reducedMotion: true });
    const uniforms = particleUniforms(fake);
    const frozenTime = uniforms.uFlowTime!.value as number;
    const baselineBloom = postfx.blooms[0]!.strength;
    space.setMood({ flowScale: 1.8, bloomBoost: 0.08 });
    pumpFrames(5);
    expect(uniforms.uFlowTime!.value).toBe(frozenTime);
    expect(postfx.blooms[0]!.strength).toBeCloseTo(baselineBloom, 5);
    space.dispose();
  });
});

describe("createSpace M21.3 粒子节奏同步（setAudioLevels）", () => {
  it("写入音频频段 uniforms：bass/mid/treble 钳制 [0,1]、beatStrength 钳制 [0,3]", () => {
    const { deps, fake, pumpFrames } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    pumpFrames(1);
    const uniforms = particleUniforms(fake);
    space.setAudioLevels({ bass: 0.6, mid: 0.4, treble: 0.2, beatStrength: 1.5 });
    expect(uniforms.uBassLevel!.value).toBeCloseTo(0.6, 5);
    expect(uniforms.uMidLevel!.value).toBeCloseTo(0.4, 5);
    expect(uniforms.uTrebleLevel!.value).toBeCloseTo(0.2, 5);
    expect(uniforms.uBeatStrength!.value).toBeCloseTo(1.5, 5);
    space.dispose();
  });

  it("越限输入被钳制：bass/mid/treble → [0,1]，beatStrength → [0,3]", () => {
    const { deps, fake, pumpFrames } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    pumpFrames(1);
    const uniforms = particleUniforms(fake);
    space.setAudioLevels({ bass: 1.5, mid: -0.2, treble: 99, beatStrength: 5 });
    expect(uniforms.uBassLevel!.value).toBe(1);
    expect(uniforms.uMidLevel!.value).toBe(0);
    expect(uniforms.uTrebleLevel!.value).toBe(1);
    expect(uniforms.uBeatStrength!.value).toBe(3);
    space.dispose();
  });

  it("NaN 频段视为 0（不污染 uniform）", () => {
    const { deps, fake, pumpFrames } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    pumpFrames(1);
    const uniforms = particleUniforms(fake);
    space.setAudioLevels({
      bass: Number.NaN,
      mid: Number.POSITIVE_INFINITY,
      treble: Number.NaN,
      beatStrength: Number.NaN,
    });
    expect(uniforms.uBassLevel!.value).toBe(0);
    expect(uniforms.uMidLevel!.value).toBe(0);
    expect(uniforms.uTrebleLevel!.value).toBe(0);
    expect(uniforms.uBeatStrength!.value).toBe(0);
    space.dispose();
  });

  it("null 归零全部音频 uniforms（停止音乐模式回到非音乐态）", () => {
    const { deps, fake, pumpFrames } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    pumpFrames(1);
    const uniforms = particleUniforms(fake);
    space.setAudioLevels({ bass: 0.8, mid: 0.5, treble: 0.3, beatStrength: 2 });
    expect(uniforms.uBassLevel!.value).toBe(0.8);
    space.setAudioLevels(null);
    expect(uniforms.uBassLevel!.value).toBe(0);
    expect(uniforms.uMidLevel!.value).toBe(0);
    expect(uniforms.uTrebleLevel!.value).toBe(0);
    expect(uniforms.uBeatStrength!.value).toBe(0);
    space.dispose();
  });

  it("强拍同步推 bloom 脉冲：beatStrength>0 时 bloom 强度上升（叠加 beatPulse 增量）", () => {
    const postfx = makeFakePostfx();
    const { deps, pumpFrames } = makeDeps({
      postfx: postfx.modules as unknown as SpaceDeps["postfx"],
    });
    const space = createSpace(deps, document.createElement("div"));
    pumpFrames(1);
    const baselineBloom = postfx.blooms[0]!.strength;
    space.setAudioLevels({ bass: 0.5, mid: 0.5, treble: 0.5, beatStrength: 2 });
    pumpFrames(1);
    // beatPulse=2 → bloom 增量 = 2 * MAX_BEAT_BLOOM_BOOST(0.35) = 0.7（受 MAX_BLOOM_STRENGTH 0.9 钳制）
    expect(postfx.blooms[0]!.strength).toBeGreaterThan(baselineBloom);
    space.dispose();
  });

  it("null 时同步把 bloom 脉冲归零", () => {
    const postfx = makeFakePostfx();
    const { deps, pumpFrames } = makeDeps({
      postfx: postfx.modules as unknown as SpaceDeps["postfx"],
    });
    const space = createSpace(deps, document.createElement("div"));
    pumpFrames(1);
    space.setAudioLevels({ bass: 0.5, mid: 0.5, treble: 0.5, beatStrength: 2 });
    pumpFrames(1);
    const liftedBloom = postfx.blooms[0]!.strength;
    space.setAudioLevels(null);
    pumpFrames(1);
    expect(postfx.blooms[0]!.strength).toBeLessThan(liftedBloom);
    space.dispose();
  });

  it("reduced-motion 下 setAudioLevels 恒归零（光敏防护，禁用节奏粒子脉冲）", () => {
    const { deps, fake, pumpFrames } = makeDeps();
    const space = createSpace(deps, document.createElement("div"), { reducedMotion: true });
    pumpFrames(1);
    const uniforms = particleUniforms(fake);
    space.setAudioLevels({ bass: 0.9, mid: 0.9, treble: 0.9, beatStrength: 3 });
    expect(uniforms.uBassLevel!.value).toBe(0);
    expect(uniforms.uMidLevel!.value).toBe(0);
    expect(uniforms.uTrebleLevel!.value).toBe(0);
    expect(uniforms.uBeatStrength!.value).toBe(0);
    space.dispose();
  });

  it("dispose 后 setAudioLevels 静默 no-op（不抛错、不写 uniform）", () => {
    const { deps, fake, pumpFrames } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    pumpFrames(1);
    const uniforms = particleUniforms(fake);
    space.dispose();
    expect(() =>
      space.setAudioLevels({ bass: 0.5, mid: 0.5, treble: 0.5, beatStrength: 1 }),
    ).not.toThrow();
    // 已 dispose：uniform 保持初始 0，不被写入
    expect(uniforms.uBassLevel!.value).toBe(0);
  });
});

describe("createSpace M21.4 节奏电影镜头（setCinemaMode）", () => {
  it("初始 cinema mode=off，getCinemaMode 返回 off", () => {
    const { deps } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    expect(space.getCinemaMode()).toBe("off");
    space.dispose();
  });

  it("setCinemaMode 切换模式（calm/standard/intense），getCinemaMode 反映切换", () => {
    const { deps } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    space.setCinemaMode("calm");
    expect(space.getCinemaMode()).toBe("calm");
    space.setCinemaMode("intense");
    expect(space.getCinemaMode()).toBe("intense");
    space.setCinemaMode("off");
    expect(space.getCinemaMode()).toBe("off");
    space.dispose();
  });

  it("calm 模式产生 FOV 呼吸：camera.fov 偏离基线 CAMERA_FOV(42)", () => {
    const { deps, fake, pumpFrames } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    space.setCinemaMode("calm");
    // 渲染多帧捕捉正弦呼吸的非零相位
    let fovChanged = false;
    for (let i = 0; i < 120; i += 1) {
      pumpFrames(1);
      if (fake.__spy.camera.fov !== 42) {
        fovChanged = true;
        break;
      }
    }
    expect(fovChanged).toBe(true);
    space.dispose();
  });

  it("off 模式 camera.fov 恒为基线 42（不干预）", () => {
    const { deps, fake, pumpFrames } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    for (let i = 0; i < 30; i += 1) {
      pumpFrames(1);
      expect(fake.__spy.camera.fov).toBe(42);
    }
    space.dispose();
  });

  it("intense 模式 + beat 触发相机位置偏移（环绕/摇晃）", () => {
    const { deps, fake, pumpFrames } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    space.setCinemaMode("intense");
    // 权重过渡需要 ~1s 收敛
    pumpFrames(60);
    const baseX = fake.__spy.camera.position.x;
    // 多次 beat + 帧推进触发环绕
    for (let i = 0; i < 30; i += 1) {
      space.setAudioLevels({ bass: 0.5, mid: 0.5, treble: 0.5, beatStrength: 2 });
      pumpFrames(1);
    }
    // 环绕/摇晃应使 x 偏离基础视差位置
    expect(fake.__spy.camera.position.x).not.toBeCloseTo(baseX, 1);
    space.dispose();
  });

  it("reduced-motion 下 setCinemaMode 强制 off（光敏防护）", () => {
    const { deps, fake, pumpFrames } = makeDeps();
    const space = createSpace(deps, document.createElement("div"), { reducedMotion: true });
    space.setCinemaMode("intense");
    expect(space.getCinemaMode()).toBe("off");
    // 渲染多帧：camera.fov 恒基线、位置无 cinema 偏移
    for (let i = 0; i < 30; i += 1) {
      pumpFrames(1);
      expect(fake.__spy.camera.fov).toBe(42);
    }
    space.dispose();
  });

  it("setAudioLevels 转发 beat 到 cinema rig：intense 模式下 beat>0 触发震动", () => {
    const { deps, fake, pumpFrames } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    space.setCinemaMode("intense");
    // 权重过渡需要 ~1s 收敛（MODE_TRANSITION_RATE=2.5 → 400ms 达 95%）
    pumpFrames(60);
    // 强 beat
    space.setAudioLevels({ bass: 0.5, mid: 0.5, treble: 0.5, beatStrength: 3 });
    pumpFrames(1);
    // 摇晃使 camera position 偏离纯视差位置（rig.x=0 时 cinema 偏移应非零）
    const cinemaOffsetX = fake.__spy.camera.position.x;
    expect(Math.abs(cinemaOffsetX)).toBeGreaterThan(0.001);
    // 渲染 1s 后摇晃衰减（cinema 摇晃分量归零，但环绕仍推进）
    for (let i = 0; i < 60; i += 1) {
      pumpFrames(1);
    }
    // 摇晃衰减后偏移主要由环绕贡献（稳定值，无震动尖峰）
    const settledX = fake.__spy.camera.position.x;
    expect(Math.abs(settledX)).toBeLessThanOrEqual(CINEMA_MAX_ORBIT_RADIUS + CINEMA_MAX_SHAKE + 1e-3);
    space.dispose();
  });

  it("dispose 后 setCinemaMode 静默 no-op", () => {
    const { deps } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    space.dispose();
    expect(() => space.setCinemaMode("intense")).not.toThrow();
    expect(space.getCinemaMode()).toBe("off");
  });

  it("setCinemaMode 未知模式抛 RangeError", () => {
    const { deps } = makeDeps();
    const space = createSpace(deps, document.createElement("div"));
    expect(() => space.setCinemaMode("extreme" as never)).toThrow(RangeError);
    space.dispose();
  });
});
