/**
 * createSpace 场景装配（M5.1 底座 + M5.2 GPU 粒子系统）：
 * renderer（alpha 透明、antialias 按档）、perspective 相机 + 相机 rig
 * （指针 → 目标偏移 lerp 0.06 缓动视差）、GPU 实例化粒子（particles.ts：
 * 流场漂移 / 指针吸引子 / 形状 morph，实例数按画质档 4000/2000/800 重建）、
 * 主题雾色/色板经 themeBridge 260ms 过渡、fps 滚动均值自动降档、resize、幂等 dispose。
 * three 模块全部经 deps 注入：本文件不做顶层 three import，
 * 测试以 fake three 替换、不创建真实 WebGL 上下文；缺省 postfx 模块时
 * 退化为 renderer 直接渲染（降级路径）。
 */
import { createAttractor, pointerToPlane } from "./attractor";
import { createCinemaRig, type CinemaMode, type CinemaRig } from "./cinemaRig";
import type { FieldParams } from "../field/fieldState";
import { MOOD_BASELINE, clampMoodSpec, type MoodSpec } from "./mood";
import { createParticleSystem, type ParticleSystem } from "./particles";
import { createPostfx, type Postfx, type PostfxModules } from "./postfx";
import {
  createQualityMonitor,
  getTierSpec,
  type QualityTierName,
  type QualityTierSpec,
} from "./quality";
import { createRippleQueue } from "./ripples";
import {
  createMorphTransition,
  generateShapePoints,
  isShapeKind,
  type ShapeKind,
} from "./shapes";
import { createThemeTransition, themeToSceneParams, type SceneParams } from "./themeBridge";
import { DEFAULT_THEME_ID, getTheme, type DarkroomTheme } from "../theme/themes";
import {
  applyWeatherMood,
  clearWeatherMood,
  DEFAULT_AMBIENT_COLOR,
  DEFAULT_AMBIENT_INTENSITY,
  type WeatherMoodScene,
} from "./weatherMood";
import type { WeatherMood } from "../data/sources";

/** createSpace 消费的最小 three 结构契约（真实 three 与 fake 均满足）。 */
export interface RendererLike {
  readonly domElement: HTMLCanvasElement;
  setPixelRatio(ratio: number): void;
  setSize(width: number, height: number): void;
  setClearColor(color: unknown, alpha?: number): void;
  render(scene: unknown, camera: unknown): void;
  dispose(): void;
}

export interface SceneLike {
  add(object: unknown): void;
  remove(object: unknown): void;
  fog: unknown;
  background: unknown;
}

export interface CameraLike {
  readonly position: { x: number; y: number; z: number };
  aspect: number;
  /** M21.4 dolly zoom 需要可写 fov（度）。 */
  fov: number;
  lookAt(x: number, y: number, z: number): void;
  updateProjectionMatrix(): void;
}

export interface ColorLike {
  setRGB(r: number, g: number, b: number): ColorLike;
}

export interface ThreeModule {
  WebGLRenderer: new (options: {
    alpha?: boolean;
    antialias?: boolean;
    powerPreference?: string;
  }) => RendererLike;
  Scene: new () => SceneLike;
  PerspectiveCamera: new (fov: number, aspect: number, near: number, far: number) => CameraLike;
  InstancedBufferGeometry: new () => {
    instanceCount: number;
    setAttribute(name: string, attribute: unknown): void;
    dispose(): void;
  };
  InstancedBufferAttribute: new (array: Float32Array, itemSize: number) => unknown;
  BufferAttribute: new (array: Float32Array, itemSize: number) => unknown;
  DataTexture: new (data: Uint8Array, width: number, height: number) => {
    needsUpdate: boolean;
    dispose(): void;
  };
  ShaderMaterial: new (options: {
    uniforms: Record<string, { value: unknown }>;
    vertexShader: string;
    fragmentShader: string;
    transparent?: boolean;
    depthWrite?: boolean;
    depthTest?: boolean;
    blending?: unknown;
  }) => { readonly uniforms: Record<string, { value: unknown }>; dispose(): void };
  Points: new (geometry: unknown, material: unknown) => { geometry: unknown };
  Color: new () => ColorLike;
  FogExp2: new (color: unknown, density: number) => unknown;
  AdditiveBlending: unknown;
  NormalBlending: unknown;
  // --- M23.3 天气情绪联动：AmbientLight 驱动场景主色调 ---
  // color.setRGB + 可写 intensity；真实 three.AmbientLight 与 fake 均满足此契约。
  AmbientLight: new (color?: unknown, intensity?: number) => {
    readonly color: ColorLike;
    intensity: number;
  };
  // --- M20 Shelf 子场景所需 API（three.js 标准命名空间提供，fake 须补全） ---
  /** 卡片架 Group 容器。 */
  Group: new () => ShelfGroup;
  /** 单张卡片 Mesh（PlaneGeometry + Material）。 */
  Mesh: new (geometry: unknown, material: unknown) => ShelfMesh;
  /** 卡片平面几何（带 dispose）。 */
  PlaneGeometry: new (width: number, height: number, segmentsX?: number, segmentsY?: number) => {
    dispose(): void;
  };
  /** 卡片背面 / 无纹理兜底材质。 */
  MeshBasicMaterial: new (opts: Record<string, unknown>) => { dispose(): void };
  /** 标题 / 副标题 canvas → 纹理（带 needsUpdate / dispose）。 */
  CanvasTexture: new (canvas: HTMLCanvasElement) => { needsUpdate: boolean; dispose(): void };
  /** 封面 URL → Texture 异步加载器。 */
  TextureLoader: new () => { load(url: string, onLoad?: (tex: unknown) => void): unknown };
  /** 三维向量（position / scale 复用）。 */
  Vector3: new (x?: number, y?: number, z?: number) => ShelfVec3;
  /** 欧拉角（rotation 复用）。 */
  Euler: new (x?: number, y?: number, z?: number, order?: string) => ShelfEuler;
}

/** ShelfStage 消费的 Group 形状（与 three.Group 子集对齐）。 */
export interface ShelfGroup {
  readonly position: ShelfVec3;
  readonly rotation: ShelfEuler;
  readonly children: unknown[];
  add(object: unknown): void;
  remove(object: unknown): void;
}

/** ShelfStage 消费的 Mesh 形状。 */
export interface ShelfMesh {
  readonly position: ShelfVec3;
  readonly rotation: ShelfEuler;
  readonly scale: ShelfVec3;
  readonly geometry: unknown;
  readonly material: unknown;
  visible: boolean;
}

/** 三维向量契约（position / scale 复用）。 */
export interface ShelfVec3 {
  x: number;
  y: number;
  z: number;
  set(x: number, y: number, z: number): ShelfVec3;
  copy(v: { x: number; y: number; z: number }): ShelfVec3;
}

/** 欧拉角契约（rotation 复用）。 */
export interface ShelfEuler {
  x: number;
  y: number;
  z: number;
  set(x: number, y: number, z: number): ShelfEuler;
}

export interface SpaceDeps {
  readonly three: ThreeModule;
  /** 可选：后处理模块（EffectComposer 等）；缺省时退化为直接渲染。 */
  readonly postfx?: PostfxModules;
  readonly width: number;
  readonly height: number;
  readonly devicePixelRatio: number;
  readonly now: () => number;
  readonly requestFrame: (callback: FrameRequestCallback) => number;
  readonly cancelFrame: (handle: number) => void;
}

export interface SpaceOptions {
  readonly theme?: DarkroomTheme;
  readonly reducedMotion?: boolean;
}

/**
 * M20 ShelfHost：暴露 Space 内部场景 / 相机 / three 模块 / 时序注入给 ShelfStage 子场景。
 * ShelfStage 借此共享同一 renderer/camera（避免第二 WebGL 上下文与 alpha 透明冲突），
 * 在 scene 中挂载自己的 Group，由 Space 帧循环统一渲染。
 */
export interface ShelfHost {
  readonly scene: SceneLike;
  readonly camera: CameraLike;
  readonly three: ThreeModule;
  readonly now: () => number;
  readonly requestFrame: (callback: FrameRequestCallback) => number;
  readonly cancelFrame: (handle: number) => void;
}

export interface Space {
  /** 归一化指针（[-1, 1]），驱动相机视差与吸引子；越界钳制，非有限值抛 RangeError。 */
  setPointer(x: number, y: number): void;
  setReducedMotion(on: boolean): void;
  /** 手动画质档覆盖（接受档位名或档定义对象）；未知档抛 RangeError。M21.7 起接受 cinematic 档。 */
  setQuality(tier: QualityTierName | QualityTierSpec): void;
  /**
   * M22.4 壁纸模式：true 强制 wallpaper 画质档（粒子≤2000 + 关 AA + 像素比钳 1），
   * 同时 bloom 减半、后处理简化（关色差 / 暗角呼吸降基线）；false 恢复自动档与基线 bloom。
   * 优先级低于 reduced-motion（光敏防护最优先），高于 override / auto。
   */
  setWallpaperMode(on: boolean): void;
  /** 主题切换：雾色 / 色板 / bloom 经 260ms 过渡插值。 */
  applyTheme(theme: DarkroomTheme): void;
  /** 粒子聚集成形（M5.3 触发接线）；未知形状抛 RangeError；reduced-motion 静止降级为空操作。 */
  morphTo(shape: ShapeKind): void;
  /** 消散回自由流场（≥600ms 缓动，禁瞬跳）。 */
  releaseShape(): void;
  /** 吸引子点击脉冲（强度钳制 [0, MAX]）；reduced-motion 为空操作。 */
  pulseAttractor(strength?: number): void;
  /**
   * M5.3：在世界坐标处激起 3D 水波纹（慢速大范围扩散）。
   * 并发满（4 条）返回 false；非法坐标抛 RangeError；reduced-motion 零产生（返回 false）。
   */
  addRipple(ripple: { x: number; y: number; z?: number; durationMs?: number }): boolean;
  /** NDC([-1,1]) 处激起水波纹：反投影到粒子层深度平面；非法输入抛 RangeError。 */
  addRippleAt(ndcX: number, ndcY: number, durationMs?: number): boolean;
  /**
   * M5.3 语音氛围：flowScale 缓动收敛、bloom 增量即时生效；
   * null 回平静基线；倍率经 clampMoodSpec 硬钳制；reduced-motion 恒基线（流速冻结、bloom 不升）。
   */
  setMood(spec: MoodSpec | null): void;
  /**
   * M7.3 四态场语义：voice.state 经 resolveFieldState 映射为 FieldParams，
   * 桥接写入粒子场 uniforms（dim 系数 / 井心吸引子 / 轨道中心+角速度 / brightnessLift）。
   * 参数中的 ripple / flowline 由 FieldStage 自行消费（addRipple / canvas）；
   * reduced-motion 下 setField 仍接受并写入 dim（静态视觉态），动效附属已被
   * resolveFieldState 剥离——调用方无需特判。dispose 后空操作。
   */
  setField(params: FieldParams): void;
  /**
   * M21.3 粒子节奏同步：写入音频频段 uniforms（uBassLevel/uMidLevel/uTrebleLevel）
   * + 强拍 uniform（uBeatStrength）。null 表示停止音乐模式，全部归零回到非音乐态。
   * 倍率硬钳制 [0,1]（bass/mid/treble）与 [0,3]（beatStrength）；reduced-motion
   * 下全部归零（禁用节奏粒子脉冲，仅保留基础形态——防光敏风险）。
   * dispose 后空操作。
   */
  setAudioLevels(levels: { bass: number; mid: number; treble: number; beatStrength: number } | null): void;
  /**
   * M21.4 节奏电影镜头：设置 cinema mode（off/calm/standard/intense）。
   * off = 不干预基础视差 rig；calm/standard/intense 叠加 dolly/环绕/摇晃。
   * beat 事件由 setAudioLevels 的 beatStrength 自动转发到 cinemaRig.onBeat。
   * reduced-motion 下恒 off（光敏防护）。dispose 后空操作。
   */
  setCinemaMode(mode: CinemaMode): void;
  /** M21.4 当前 cinema mode（测试探针）。 */
  getCinemaMode(): CinemaMode;
  /**
   * M23.3 天气情绪联动：把 WeatherMood 应用到场景——
   * AmbientLight 颜色 / 强度 + 粒子色板 / 密度 / uWeatherSpeed / uWeatherBrightness。
   * null 清除天气情绪（恢复默认 AmbientLight + 粒子参数）。
   * 与 M21 节奏粒子 / M5.3 语音氛围正交叠加，互不冲突。
   * reduced-motion 下仍写入 AmbientLight 与色板（静态视觉态），粒子密度也生效；
   * uWeatherSpeed 在 reduced-motion 下被 mood.ts 流场冻结机制覆盖（uFlowTime 不推进）。
   * dispose 后空操作。
   */
  setWeatherMood(mood: WeatherMood | null): void;
  resize(width: number, height: number): void;
  /** 幂等：移除画布、停循环、释放 geometry/material/texture/renderer。 */
  dispose(): void;
  /**
   * M20：获取 ShelfHost（场景 / 相机 / three 模块 / 时序注入）供 ShelfStage 子场景挂载。
   * dispose 后返回 null；ShelfStage 借此共享同一 renderer/camera，避免第二 WebGL 上下文。
   */
  getShelfHost(): ShelfHost | null;
}

// 相机 rig 常量：视差偏移有界（|x| ≤ 0.6 < 1.5），缓动落在 spec 的 0.04~0.08。
const CAMERA_Z = 8;
const CAMERA_FOV = 42;
const PARALLAX_X = 0.6;
const PARALLAX_Y = 0.35;
const RIG_LERP = 0.06;
const FOG_DENSITY = 0.055;
/** 吸引子反投影目标平面：粒子体积分布的中位深度。 */
const ATTRACTOR_PLANE_Z = 0;
/** mood 流速缓动收敛率（/s）：~300ms 内收敛到新氛围，禁瞬跳。 */
const MOOD_FLOW_LERP_RATE = 6;

const clampPointer = (value: number): number => Math.min(1, Math.max(-1, value));

export function createSpace(
  deps: SpaceDeps,
  container: HTMLElement,
  options: SpaceOptions = {},
): Space {
  if (
    !Number.isFinite(deps.width) ||
    deps.width <= 0 ||
    !Number.isFinite(deps.height) ||
    deps.height <= 0
  ) {
    throw new RangeError(`非法视口尺寸: ${deps.width}×${deps.height}`);
  }
  const three = deps.three;
  const monitor = createQualityMonitor({ reducedMotion: options.reducedMotion ?? false });
  let reduced = options.reducedMotion ?? false;

  // --- renderer：alpha 透明（窗口契约透出桌面），antialias / pixelRatio 按画质档 ---
  const initialSpec = monitor.getTierSpec();
  const renderer = new three.WebGLRenderer({
    alpha: true,
    antialias: initialSpec.antialias,
    powerPreference: "high-performance",
  });
  const canvas = renderer.domElement;
  canvas.classList.add("immersive-space");
  canvas.style.pointerEvents = "none"; // 绝不拦截指针（审美红线：不遮挡交互）
  canvas.setAttribute("aria-hidden", "true");
  container.appendChild(canvas);

  const pixelRatioFor = (tier: QualityTierName): number =>
    Math.min(deps.devicePixelRatio || 1, getTierSpec(tier).pixelRatioCap);
  let pixelRatio = pixelRatioFor(monitor.getTier());
  renderer.setPixelRatio(pixelRatio);
  renderer.setSize(deps.width, deps.height);
  renderer.setClearColor(0x000000, 0); // 全透明清屏，雾色只作用于场景深度

  // --- scene / camera / 雾 ---
  const scene = new three.Scene();
  const initialParams = themeToSceneParams(options.theme ?? getTheme(DEFAULT_THEME_ID));
  const fogColor = new three.Color();
  fogColor.setRGB(...initialParams.fogColor);
  scene.fog = new three.FogExp2(fogColor, FOG_DENSITY);

  // --- M23.3 天气情绪联动：AmbientLight 驱动场景主色调（默认暖白克制基线） ---
  const ambientLight = new three.AmbientLight();
  ambientLight.color.setRGB(...DEFAULT_AMBIENT_COLOR);
  ambientLight.intensity = DEFAULT_AMBIENT_INTENSITY;
  scene.add(ambientLight);

  const camera = new three.PerspectiveCamera(
    CAMERA_FOV,
    deps.width / deps.height,
    0.1,
    60,
  );
  camera.position.x = 0;
  camera.position.y = 0;
  camera.position.z = CAMERA_Z;
  camera.lookAt(0, 0, 0);

  // --- GPU 粒子系统（M5.2）：实例数随画质档，流场 + 吸引子 + 形状 morph ---
  const particles: ParticleSystem = createParticleSystem({
    three,
    count: initialSpec.particleCount,
  });
  particles.uniforms.uPixelRatio!.value = pixelRatio;
  scene.add(particles.points);
  const attractor = createAttractor();
  const morph = createMorphTransition();
  const SHAPE_BLEND_MS = 900; // 形态间直接变形时长（ms），smoothstep 缓动
  let shapeBlendActive = false;
  let shapeBlendStart = 0;
  function shapeBlendTo(now: number): void {
    shapeBlendActive = true;
    shapeBlendStart = now;
  }
  function sampleShapeBlend(now: number): number {
    if (!shapeBlendActive) return 1;
    const raw = (now - shapeBlendStart) / SHAPE_BLEND_MS;
    if (raw >= 1) {
      shapeBlendActive = false;
      return 1;
    }
    const t = Math.min(1, Math.max(0, raw));
    return t * t * (3 - 2 * t); // smoothstep
  }
  let currentShape: ShapeKind | null = null;
  let desiredShape: ShapeKind | null = null;
  let targetHelixSpeed = 0; // 螺旋自转角速度目标（rad/s），由 setField 写入
  let pointerActive = false;
  let flowTime = 0; // 流场时钟：reduced-motion / 循环停止时自然冻结
  let helixAngle = 0; // DNA 螺旋自转累积角（rad），speed=0 时归零
  let curFlickerIntensity = 0;
  let tgtFlickerIntensity = 0;
  let curFlickerSpeed = 0;
  let tgtFlickerSpeed = 0;
  let curGlowBoost = 0;
  let tgtGlowBoost = 0;
  let curSphereScale = 1;
  let tgtSphereScale = 1;
  const FX_LERP_RATE = 8;

  // --- M5.3 水波纹队列：uniform 数组就地复用（每帧 writeUniforms 原地改写） ---
  const ripples = createRippleQueue();
  const rippleOrigins = particles.uniforms.uRippleOrigins!.value as Float32Array;
  const rippleTimes = particles.uniforms.uRippleTimes!.value as Float32Array;

  // --- M5.3 语音氛围：flowScale 缓动收敛（禁瞬跳），bloom 增量即时生效 ---
  let moodTarget: MoodSpec = MOOD_BASELINE;
  let flowScale = MOOD_BASELINE.flowScale;

  // --- 后处理（可选）：注入模块存在时走 composer 效果链，否则直接渲染。
  // 当前因透明窗口与 UnrealBloomPass alpha 通道冲突，生产 runtime 不加载 postfx 模块，
  // 保留代码路径供测试与未来 bloom alpha 修复后恢复 ---
  let fx: Postfx | null = null;
  if (deps.postfx) {
    fx = createPostfx(
      { modules: deps.postfx, renderer, scene, camera, width: deps.width, height: deps.height },
      { tier: monitor.getTier() },
    );
    fx.setPixelRatio(pixelRatio);
  }

  // --- 主题过渡：每帧采样插值参数并应用（雾色 / 色板 / 氛围） ---
  const transition = createThemeTransition(initialParams);
  const applySceneParams = (params: SceneParams): void => {
    fogColor.setRGB(...params.fogColor);
    particles.setPalette(params.palette); // 6 槽色板 → uniform，随主题 260ms 过渡
    fx?.applyParams(params);
  };
  applySceneParams(initialParams);

  // --- 画质档联动：pixelRatio 压档 + 粒子数重建（不闪断）+ 效果链降档 ---
  const applyTier = (tier: QualityTierName): void => {
    pixelRatio = pixelRatioFor(tier);
    renderer.setPixelRatio(pixelRatio);
    particles.setCount(getTierSpec(tier).particleCount);
    if (currentShape) {
      // 成形中换档：目标点云按新实例数重生成（确定性生成，形状不抖动）
      particles.setShapeTargets(generateShapePoints(currentShape, particles.getCount()));
    }
    particles.uniforms.uPixelRatio!.value = pixelRatio;
    fx?.setQuality(tier);
    fx?.setPixelRatio(pixelRatio);
  };
  monitor.subscribe(applyTier);

  // --- 帧循环与相机 rig ---
  const pointer = { x: 0, y: 0 };
  const rig = { x: 0, y: 0 };
  // M21.4 节奏电影镜头：纯状态机，产出相机偏移叠加到基础视差 rig 之上
  const cinemaRig: CinemaRig = createCinemaRig({ reducedMotion: reduced });
  let disposed = false;
  let frameHandle: number | null = null;
  let lastNow: number | null = null;

  const renderFrame = (now: number): void => {
    const dt = lastNow === null ? 1 / 60 : Math.min(0.1, Math.max(0, (now - lastNow) / 1000));
    lastNow = now;
    monitor.recordFrame(now);
    applySceneParams(transition.sample(now).params);
    rig.x += (pointer.x * PARALLAX_X - rig.x) * RIG_LERP;
    rig.y += (pointer.y * PARALLAX_Y - rig.y) * RIG_LERP;
    // M21.4 节奏电影镜头：叠加 cinema rig 偏移（dolly/环绕/摇晃）
    const cinema = cinemaRig.step(dt, now / 1000);
    camera.position.x = rig.x + cinema.posX;
    camera.position.y = rig.y + cinema.posY;
    camera.position.z = CAMERA_Z + cinema.posZ;
    // M21.4 dolly zoom：FOV 偏移直接改 camera.fov 并重算投影矩阵
    if (cinema.fovOffset !== 0) {
      camera.fov = CAMERA_FOV + cinema.fovOffset;
      camera.updateProjectionMatrix();
    } else if (camera.fov !== CAMERA_FOV) {
      camera.fov = CAMERA_FOV;
      camera.updateProjectionMatrix();
    }
    camera.lookAt(0, 0, 0);
    // 吸引子：指针 NDC 反投影到粒子层深度平面（无指针时强度归零 → 纯流场）
    if (pointerActive) {
      const target = pointerToPlane(pointer.x, pointer.y, {
        fovDeg: CAMERA_FOV,
        aspect: camera.aspect,
        cameraZ: CAMERA_Z,
        planeZ: ATTRACTOR_PLANE_Z,
        originX: rig.x,
        originY: rig.y,
      });
      attractor.setTarget(target.x, target.y, target.z);
    }
    const a = attractor.step(dt);
    const attractorUniform = particles.uniforms.uAttractor!.value as {
      x: number;
      y: number;
      z: number;
    };
    attractorUniform.x = a.x;
    attractorUniform.y = a.y;
    attractorUniform.z = a.z;
    particles.uniforms.uAttractorStrength!.value = a.strength;
    // M5.3 水波纹：过期出队 + uniform 数组原地改写（秒制时钟随帧推进）
    ripples.writeUniforms(rippleOrigins, rippleTimes, now);
    particles.uniforms.uNowSec!.value = now / 1000;
    // M5.3 语音氛围：流速倍率缓动收敛到 moodTarget（禁瞬跳）
    flowScale += (moodTarget.flowScale - flowScale) * Math.min(1, dt * MOOD_FLOW_LERP_RATE);
    // 粒子特效参数（闪烁/辉光/球体缩放）缓动收敛，避免状态切换时瞬跳
    curFlickerIntensity += (tgtFlickerIntensity - curFlickerIntensity) * Math.min(1, dt * FX_LERP_RATE);
    curFlickerSpeed += (tgtFlickerSpeed - curFlickerSpeed) * Math.min(1, dt * FX_LERP_RATE);
    curGlowBoost += (tgtGlowBoost - curGlowBoost) * Math.min(1, dt * FX_LERP_RATE);
    curSphereScale += (tgtSphereScale - curSphereScale) * Math.min(1, dt * FX_LERP_RATE);
    particles.uniforms.uFlickerIntensity!.value = curFlickerIntensity;
    particles.uniforms.uFlickerSpeed!.value = curFlickerSpeed;
    particles.uniforms.uGlowBoost!.value = curGlowBoost;
    particles.uniforms.uShapeScale!.value = curSphereScale;
    // 流场时钟前进（dt × 氛围倍率驱动；循环冻结时时间同步冻结）+ morph 过渡采样
    flowTime += dt * flowScale;
    particles.uniforms.uFlowTime!.value = flowTime;
    particles.uniforms.uMorphFactor!.value = morph.sample(now);
    // 形态间直接插值：形状混合进行中时逐帧 lerp aTarget，保持 morphFactor=1 不消散
    if (shapeBlendActive) {
      const s = sampleShapeBlend(now);
      particles.stepShapeBlend(s);
      if (!shapeBlendActive) {
        particles.endShapeBlend();
      }
    }
    // DNA 螺旋自转：按目标角速度累积角度；speed=0 时归零（非螺旋态不应用旋转）
    if (targetHelixSpeed > 0) {
      helixAngle += dt * targetHelixSpeed;
      particles.uniforms.uShapeRotAngle!.value = helixAngle;
    } else {
      helixAngle = 0;
      particles.uniforms.uShapeRotAngle!.value = 0;
    }
    if (fx) fx.render(dt);
    else renderer.render(scene, camera);
  };

  const schedule = (): void => {
    frameHandle = deps.requestFrame((now) => {
      frameHandle = null;
      if (disposed || reduced) return;
      renderFrame(now);
      schedule();
    });
  };
  const startLoop = (): void => {
    if (frameHandle !== null || disposed) return;
    schedule();
  };
  const stopLoop = (): void => {
    if (frameHandle === null) return;
    deps.cancelFrame(frameHandle);
    frameHandle = null;
  };

  // reduced-motion：创建即冻结为单帧静态画面，不启动循环。
  if (reduced) renderFrame(deps.now());
  else startLoop();

  return {
    setPointer(x: number, y: number): void {
      if (!Number.isFinite(x) || !Number.isFinite(y)) {
        throw new RangeError(`指针坐标非法: (${x}, ${y})`);
      }
      if (reduced) return; // 静止降级：相机不漂移、吸引子不激活
      pointer.x = clampPointer(x);
      pointer.y = clampPointer(y);
      if (!pointerActive) {
        pointerActive = true;
        attractor.setActive(true);
      }
    },

    setReducedMotion(on: boolean): void {
      if (on === reduced) return;
      reduced = on;
      monitor.setReducedMotion(on);
      if (disposed) return;
      if (on) {
        stopLoop();
        transition.finish();
        fx?.setBloomBoost(0); // 静止降级：氛围加成归零，恒基线
        // M21.3 静止降级：音频节奏全部归零（禁用强拍脉冲 / bloom 增强 / 色差 / 暗角呼吸）
        particles.uniforms.uBassLevel!.value = 0;
        particles.uniforms.uMidLevel!.value = 0;
        particles.uniforms.uTrebleLevel!.value = 0;
        particles.uniforms.uBeatStrength!.value = 0;
        fx?.setBeatPulse(0);
        // 静止降级：释放粒子形态、停螺旋、零脉冲
        if (currentShape !== null || desiredShape !== null) {
          currentShape = null;
          desiredShape = null;
          shapeBlendActive = false;
          particles.cancelShapeBlend();
          particles.uniforms.uMorphFactor!.value = 0;
        }
        targetHelixSpeed = 0;
        helixAngle = 0;
        particles.uniforms.uShapeRotAngle!.value = 0;
        particles.uniforms.uPulseStrength!.value = 0;
        curFlickerIntensity = tgtFlickerIntensity = 0;
        curFlickerSpeed = tgtFlickerSpeed = 0;
        curGlowBoost = tgtGlowBoost = 0;
        curSphereScale = tgtSphereScale = 1;
        particles.uniforms.uFlickerIntensity!.value = 0;
        particles.uniforms.uFlickerSpeed!.value = 0;
        particles.uniforms.uGlowBoost!.value = 0;
        particles.uniforms.uShapeScale!.value = 1;
        renderFrame(deps.now()); // 冻结为当前主题静态帧
      } else {
        lastNow = null;
        fx?.setBloomBoost(moodTarget.bloomBoost); // 恢复氛围加成
        startLoop();
      }
    },

    setQuality(input: QualityTierName | QualityTierSpec): void {
      const tier = typeof input === "string" ? input : input.tier;
      getTierSpec(tier); // 非法档 → RangeError
      monitor.setOverride(tier); // 经 subscribe 通知 applyTier 生效
    },

    setWallpaperMode(on: boolean): void {
      // M22.4：壁纸模式 → 强制 wallpaper 画质档 + bloom 减半 + 后处理简化
      monitor.setWallpaperMode(on);
      if (disposed) return;
      // bloom 减半：壁纸态不抢视觉焦点，暗房风克制
      fx?.setBloomBoost(on ? moodTarget.bloomBoost * 0.5 : moodTarget.bloomBoost);
    },

    applyTheme(theme: DarkroomTheme): void {
      const params = themeToSceneParams(theme);
      transition.start(params, deps.now());
      if (reduced && !disposed) {
        transition.finish(); // 静止降级：立即落位并重绘静态帧
        renderFrame(deps.now());
      }
    },

    morphTo(shape: ShapeKind): void {
      if (!isShapeKind(shape)) {
        throw new RangeError(`未知形状: ${String(shape)}`);
      }
      if (reduced || disposed) return; // 静止降级：不聚集
      // field 驱动了持久形态时，点击聚集不覆盖（波纹/脉冲仍生效，形状保持不变）
      if (desiredShape !== null) return;
      const newTargets = generateShapePoints(shape, particles.getCount());
      // 已有临时形态且 morph 已基本成形（factor 接近 1），走形状混合避免瞬跳
      if (currentShape !== null && currentShape !== shape) {
        particles.beginShapeBlend(newTargets);
        shapeBlendTo(deps.now());
      } else {
        particles.setShapeTargets(newTargets);
        shapeBlendActive = false;
        particles.cancelShapeBlend();
        morph.morphTo(deps.now());
      }
      currentShape = shape;
    },

    releaseShape(): void {
      if (reduced || disposed) return;
      // field 驱动了持久形态时，点击缓释不释放（语音态的形状由 setField 生命周期管理）
      if (desiredShape !== null) return;
      currentShape = null;
      shapeBlendActive = false;
      particles.cancelShapeBlend();
      morph.release(deps.now());
    },

    pulseAttractor(strength?: number): void {
      if (reduced || disposed) return; // 静止降级：无脉冲
      attractor.pulse(strength);
    },

    addRipple(ripple: { x: number; y: number; z?: number; durationMs?: number }): boolean {
      if (reduced || disposed) return false; // 静止降级：零产生
      return ripples.add({
        x: ripple.x,
        y: ripple.y,
        z: ripple.z ?? 0,
        startedAt: deps.now(),
        durationMs: ripple.durationMs,
      });
    },

    addRippleAt(ndcX: number, ndcY: number, durationMs?: number): boolean {
      if (!Number.isFinite(ndcX) || !Number.isFinite(ndcY)) {
        throw new RangeError(`非法波纹 NDC 坐标: (${ndcX}, ${ndcY})`);
      }
      if (reduced || disposed) return false; // 静止降级：零产生
      // 与吸引子同一反投影：点击处的水波纹原点即指针下的粒子层世界坐标
      const point = pointerToPlane(ndcX, ndcY, {
        fovDeg: CAMERA_FOV,
        aspect: camera.aspect,
        cameraZ: CAMERA_Z,
        planeZ: ATTRACTOR_PLANE_Z,
        originX: rig.x,
        originY: rig.y,
      });
      return ripples.add({
        x: point.x,
        y: point.y,
        z: point.z,
        startedAt: deps.now(),
        durationMs,
      });
    },

    setMood(spec: MoodSpec | null): void {
      moodTarget = spec === null ? MOOD_BASELINE : clampMoodSpec(spec);
      // bloom 增量即时生效（量小无跳变感）；reduced-motion 恒基线不升
      fx?.setBloomBoost(reduced ? 0 : moodTarget.bloomBoost);
    },

    setField(params: FieldParams): void {
      if (disposed) return;
      // dim 系数（[0,1]，1=不变）：直接写入 vAlpha 乘子，reduced-motion 下仍生效（静态视觉态）。
      particles.uniforms.uFieldDim!.value = params.dimFactor;
      // 井心吸引子：null 时强度归零（shader 内 omniAttractOffset 返回 0 向量，no-op）。
      const fieldAttractor = particles.uniforms.uFieldAttractor!.value as {
        x: number;
        y: number;
        z: number;
      };
      if (params.attractor) {
        fieldAttractor.x = params.attractor.position.x;
        fieldAttractor.y = params.attractor.position.y;
        fieldAttractor.z = params.attractor.position.z;
        particles.uniforms.uFieldAttractorStrength!.value = params.attractor.strength;
      } else {
        fieldAttractor.x = 0;
        fieldAttractor.y = 0;
        fieldAttractor.z = 0;
        particles.uniforms.uFieldAttractorStrength!.value = 0;
      }
      // 轨道流：null 时角速度归零（shader 内 cos(0)=1/sin(0)=0，位置不变 no-op）。
      const orbitCenter = particles.uniforms.uFieldOrbitCenter!.value as {
        x: number;
        y: number;
        z: number;
      };
      if (params.orbit) {
        orbitCenter.x = params.orbit.center.x;
        orbitCenter.y = params.orbit.center.y;
        orbitCenter.z = params.orbit.center.z;
        particles.uniforms.uFieldOrbitAngularVel!.value = params.orbit.angularVelocity;
      } else {
        orbitCenter.x = 0;
        orbitCenter.y = 0;
        orbitCenter.z = 0;
        particles.uniforms.uFieldOrbitAngularVel!.value = 0;
      }
      // brightnessLift（≤0.2 红线）：作为 vAlpha 加法增量（与 mood bloomBoost 通路正交独立，
      // reduced-motion 下 resolveFieldState 已剥离为 0，无需特判）。
      particles.uniforms.uFieldBrightnessLift!.value = params.brightnessLift;
      // 粒子形态：形状变化时触发过渡（同形重复调用不重触发）；
      // 形态间切换（A→B，均非 null）走 beginShapeBlend 直接插值变形（不经自由流场，丝滑不消散）；
      // 自由→形态走 morph.morphTo（从流场汇聚）；形态→自由走 morph.release（释放回流场）。
      // 心跳脉冲强度与螺旋自转角速度直接写入 uniform / 帧循环目标。
      const nextShape = params.particleShape;
      if (nextShape !== desiredShape) {
        const prevShape = desiredShape;
        desiredShape = nextShape;
        if (nextShape === null) {
          currentShape = null;
          shapeBlendActive = false;
          particles.cancelShapeBlend();
          if (reduced) {
            particles.uniforms.uMorphFactor!.value = 0;
          } else {
            morph.release(deps.now());
          }
        } else if (!reduced && isShapeKind(nextShape)) {
          const newTargets = generateShapePoints(nextShape, particles.getCount());
          if (prevShape !== null) {
            particles.beginShapeBlend(newTargets);
            shapeBlendTo(deps.now());
          } else {
            particles.setShapeTargets(newTargets);
            shapeBlendActive = false;
            particles.cancelShapeBlend();
            morph.morphTo(deps.now());
          }
          currentShape = nextShape;
        }
      }
      particles.uniforms.uPulseStrength!.value = params.pulseStrength;
      targetHelixSpeed = params.helixRotSpeed;
      tgtFlickerIntensity = params.flickerIntensity;
      tgtFlickerSpeed = params.flickerSpeed;
      tgtGlowBoost = params.glowBoost;
      tgtSphereScale = params.sphereScale;
    },

    setAudioLevels(levels: { bass: number; mid: number; treble: number; beatStrength: number } | null): void {
      if (disposed) return;
      // reduced-motion：全部归零，禁用节奏粒子脉冲（防光敏风险），仅保留基础形态
      if (reduced || levels === null) {
        particles.uniforms.uBassLevel!.value = 0;
        particles.uniforms.uMidLevel!.value = 0;
        particles.uniforms.uTrebleLevel!.value = 0;
        particles.uniforms.uBeatStrength!.value = 0;
        fx?.setBeatPulse(0);
        // M21.4 停止音乐模式：cinema rig 不再接收 beat（保持当前模式但不触发新震动）
        return;
      }
      // 钳制 [0,1] / [0,3]，NaN 视为 0
      const clamp01 = (v: number): number => {
        if (!Number.isFinite(v)) return 0;
        return Math.min(1, Math.max(0, v));
      };
      const clampBeat = (v: number): number => {
        if (!Number.isFinite(v)) return 0;
        return Math.min(3, Math.max(0, v));
      };
      particles.uniforms.uBassLevel!.value = clamp01(levels.bass);
      particles.uniforms.uMidLevel!.value = clamp01(levels.mid);
      particles.uniforms.uTrebleLevel!.value = clamp01(levels.treble);
      particles.uniforms.uBeatStrength!.value = clampBeat(levels.beatStrength);
      // 同步推 bloom 强拍增强（M21.8 后处理消费）
      const beat = clampBeat(levels.beatStrength);
      fx?.setBeatPulse(beat);
      // M21.4 转发 beat 到 cinema rig（驱动环绕推进 + intense 摇晃）
      cinemaRig.onBeat(beat, performance.now() / 1000);
    },

    setCinemaMode(mode: CinemaMode): void {
      if (disposed) return;
      // reduced-motion：强制 off（光敏防护，禁用所有镜头运动）
      cinemaRig.setMode(reduced ? "off" : mode);
    },

    getCinemaMode(): CinemaMode {
      return cinemaRig.getMode();
    },

    setWeatherMood(mood: WeatherMood | null): void {
      if (disposed) return;
      const weatherScene: WeatherMoodScene = {
        ambientLight,
        particles,
        tierSpec: monitor.getTierSpec(),
      };
      if (mood === null) {
        clearWeatherMood(weatherScene);
        return;
      }
      applyWeatherMood(weatherScene, mood);
    },

    resize(width: number, height: number): void {
      if (!Number.isFinite(width) || width <= 0 || !Number.isFinite(height) || height <= 0) {
        throw new RangeError(`非法视口尺寸: ${width}×${height}`);
      }
      if (disposed) return;
      renderer.setSize(width, height);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      fx?.resize(width, height);
      if (reduced) renderFrame(deps.now()); // 静态画面跟随尺寸重绘
    },

    dispose(): void {
      if (disposed) return;
      disposed = true;
      stopLoop();
      if (canvas.parentNode === container) container.removeChild(canvas);
      scene.remove(particles.points);
      particles.dispose(); // geometry / material / texture 一并释放
      fx?.dispose();
      renderer.dispose();
    },

    getShelfHost(): ShelfHost | null {
      if (disposed) return null;
      return {
        scene,
        camera,
        three,
        now: deps.now,
        requestFrame: deps.requestFrame,
        cancelFrame: deps.cancelFrame,
      };
    },
  };
}
