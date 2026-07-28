/**
 * postfx 后处理效果链（M5.1）：EffectComposer 装配——
 * render → UnrealBloom（克制强度，随画质档缩放）→ 自定义氛围 ShaderPass
 * （vignette 暗角 + 静态 film grain，离散步进更新，禁高频闪烁）→ output。
 * three 的 examples 模块全部经 deps.modules 注入，本模块不做顶层 import，
 * 测试以 fake 模块替换、不创建真实 WebGL 上下文。
 */
import { getTierSpec, type QualityTierName } from "./quality";
import type { SceneParams } from "./themeBridge";

/** 效果链消费的最小 composer/pass 结构契约（真实 three 与 fake 均满足）。 */
export interface ComposerLike {
  addPass(pass: unknown): void;
  setSize(width: number, height: number): void;
  setPixelRatio?(ratio: number): void;
  render(): void;
  dispose?(): void;
}

export interface BloomPassLike {
  strength: number;
  radius: number;
  threshold: number;
}

export interface ShaderPassLike {
  uniforms: Record<string, { value: unknown }>;
}

export interface AtmosphereShader {
  uniforms: Record<string, { value: unknown }>;
  vertexShader: string;
  fragmentShader: string;
}

export interface RenderTargetLike {
  texture: unknown;
  setSize(w: number, h: number): void;
  dispose(): void;
}

export interface PostfxModules {
  WebGLRenderTarget: new (width: number, height: number, options?: Record<string, unknown>) => RenderTargetLike;
  HalfFloatType: number;
  RGBAFormat: number;
  LinearFilter: number;
  LinearSRGBColorSpace: string;
  EffectComposer: new (renderer: unknown, renderTarget?: RenderTargetLike) => ComposerLike;
  RenderPass: new (scene: unknown, camera: unknown) => unknown;
  UnrealBloomPass: new (
    resolution: { x: number; y: number },
    strength: number,
    radius: number,
    threshold: number,
  ) => BloomPassLike;
  ShaderPass: new (shader: AtmosphereShader) => ShaderPassLike;
  OutputPass: new () => unknown;
}

export interface PostfxDeps {
  readonly modules: PostfxModules;
  readonly renderer: unknown;
  readonly scene: unknown;
  readonly camera: unknown;
  readonly width: number;
  readonly height: number;
}

export interface PostfxOptions {
  readonly tier: QualityTierName;
}

export interface Postfx {
  /** 渲染一帧（委托 composer.render；dt 驱动 grain 离散步进时钟）。 */
  render(dt: number): void;
  resize(width: number, height: number): void;
  /** 切换画质档：bloom 强度按档缩放。未知档抛 RangeError。 */
  setQuality(tier: QualityTierName): void;
  /** 主题场景参数接入：bloom 强度/阈值、暗角、颗粒微调。 */
  applyParams(params: SceneParams): void;
  /** M5.3 语音氛围：bloom 强度增量（≥0，NaN 按 0）；与主题参数叠加后仍受克制上限钳制。 */
  setBloomBoost(boost: number): void;
  /**
   * M21.3/M21.8 强拍 bloom 脉冲：beat 触发时 bloom 短时增强（指数衰减）。
   * strength ∈ [0,3]，NaN 按 0；与 mood bloomBoost 正交叠加。
   * 内部维护衰减时钟，每帧 render 时按 dt 衰减。
   */
  setBeatPulse(strength: number): void;
  setPixelRatio(ratio: number): void;
  getVignetteStrength(): number;
  getGrainAmount(): number;
  /** M21.8 测试探针：当前 beat 脉冲强度（衰减后）。 */
  getBeatPulse(): number;
  dispose(): void;
}

/**
 * bloom 强度随画质档缩放：低档压泛光保帧率。
 * M21.7 cinematic 档与同级别 normal 档同系数（cinematic 仅放宽粒子数，bloom 不加码）。
 * M22.4 wallpaper 档与 low 同系数（壁纸态不抢视觉焦点，bloom 进一步由 setWallpaperMode 半衰）。
 */
const TIER_BLOOM_SCALE: Record<QualityTierName, number> = {
  high: 1,
  medium: 0.85,
  low: 0.65,
  cinematic_high: 1,
  cinematic_medium: 0.85,
  cinematic_low: 0.65,
  wallpaper: 0.65,
};

/** 克制区间硬上限（审美红线：不得全屏泛光 / 黑边糊脸 / 颗粒噪点显眼）。 */
const MAX_BLOOM_STRENGTH = 0.9;
const MAX_VIGNETTE = 0.55;
const MAX_GRAIN = 0.08;
const BLOOM_RADIUS = 0.4;
/** M21.8 强拍 bloom 增量硬上限（克制：再强拍也不全屏泛光）。 */
const MAX_BEAT_BLOOM_BOOST = 0.35;
/** M21.8 强拍 bloom 衰减时间常数（秒，~150ms 落位）。 */
const BEAT_DECAY = 0.15;
/** M21.8 色差强度硬上限（克制：避免视觉晕眩）。 */
const MAX_CHROMATIC_ABERRATION = 0.004;
/** M21.8 暗角呼吸幅度（克制：≤0.06，避免边缘明显明暗变化）。 */
const MAX_VIGNETTE_BREATH = 0.06;

/** grain 时间轴量化步长：8 步/秒低速换帧——静态颗粒感，不闪烁。 */
const GRAIN_STEPS_PER_SECOND = 8;

/** 未接入主题时的缺省参数（与 themeBridge 的克制基线一致）。 */
const DEFAULT_PARAMS: SceneParams = {
  fogColor: [0, 0, 0],
  palette: [],
  bloomStrength: 0.4,
  bloomThreshold: 0.75,
  vignetteStrength: 0.45,
  grainOpacity: 0.05,
};

const clamp = (value: number, max: number): number => Math.min(max, Math.max(0, value));

/**
 * 氛围 shader：暗角（椭圆径向压暗，引导视线聚焦中央）+
 * 静态胶片颗粒（hash 噪点 × 低透明度，grainTime 离散步进 → 低频更换不闪烁）+
 * M21.8 色差（chromatic aberration，强拍触发径向 RGB 偏移）+
 * M21.8 暗角呼吸（vignette 随 beat 缓慢强弱，呼吸感）。
 */
const ATMOSPHERE_SHADER: AtmosphereShader = {
  uniforms: {
    tDiffuse: { value: null },
    vignetteStrength: { value: DEFAULT_PARAMS.vignetteStrength },
    grainAmount: { value: DEFAULT_PARAMS.grainOpacity },
    grainTime: { value: 0 },
    // M21.8 节奏后处理参数（默认 0 = no-op，非音乐模式行为不变）
    chromaticAberration: { value: 0 },
    vignetteBreath: { value: 0 },
    breathPhase: { value: 0 },
  },
  vertexShader: /* glsl */ `
    varying vec2 vUv;
    void main() {
      vUv = uv;
      gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
    }
  `,
  fragmentShader: /* glsl */ `
    uniform sampler2D tDiffuse;
    uniform float vignetteStrength;
    uniform float grainAmount;
    uniform float grainTime;
    uniform float chromaticAberration;
    uniform float vignetteBreath;
    uniform float breathPhase;
    varying vec2 vUv;

    float omniHash(vec2 p) {
      return fract(sin(dot(p, vec2(127.1, 311.7)) + mod(grainTime, 10.0) * 7.13) * 43758.5453123);
    }

    void main() {
      vec2 uv = vUv;
      // M21.8 色差：径向 RGB 偏移（中心无偏移，边缘最大），强度由 beat 驱动
      vec2 centered = (uv - 0.5) * vec2(1.12, 1.0);
      float vig = smoothstep(0.38, 0.85, length(centered));
      if (chromaticAberration > 0.0001) {
        vec2 dir = normalize(centered + vec2(0.0001));
        float offset = chromaticAberration * length(centered);
        float r = texture2D(tDiffuse, uv + dir * offset).r;
        float g = texture2D(tDiffuse, uv).g;
        float b = texture2D(tDiffuse, uv - dir * offset).b;
        float a = texture2D(tDiffuse, uv).a;
        gl_FragColor = vec4(r, g, b, a);
      } else {
        gl_FragColor = texture2D(tDiffuse, uv);
      }
      vec4 color = gl_FragColor;
      // 暗角：轻微椭圆径向压暗 + M21.8 呼吸（beat 触发时暗角强度缓慢强弱）
      float breathFactor = 1.0 + vignetteBreath * 0.5 * sin(breathPhase);
      color.rgb *= 1.0 - vignetteStrength * breathFactor * vig;
      // 胶片颗粒：低透明度亮度噪点，暗角处略减（避免边缘噪点显眼）
      float grain = (omniHash(vUv * 917.0) - 0.5) * grainAmount;
      color.rgb += grain * (0.35 + 0.65 * (1.0 - vig));
      gl_FragColor = color;
    }
  `,
};

export function createPostfx(deps: PostfxDeps, options: PostfxOptions): Postfx {
  getTierSpec(options.tier); // 非法画质档 → RangeError（契约同 quality）
  const { modules } = deps;

  let tier = options.tier;
  let params = DEFAULT_PARAMS;
  let bloomBoost = 0; // M5.3 mood 微升：独立于主题参数，applyParams 不冲掉
  let beatPulse = 0; // M21.3/M21.8 强拍 bloom 脉冲（指数衰减）
  let breathPhase = 0; // M21.8 暗角呼吸相位（beat 触发后缓慢推进）
  let grainClock = 0;
  let disposed = false;

  // 创建 alpha-enabled 渲染目标（透明 HUD 必备）
  const rtOptions = {
    type: modules.HalfFloatType,
    format: modules.RGBAFormat,
    minFilter: modules.LinearFilter,
    magFilter: modules.LinearFilter,
    colorSpace: modules.LinearSRGBColorSpace,
    depthBuffer: true,
    stencilBuffer: false,
  };
  const renderTarget = new modules.WebGLRenderTarget(deps.width, deps.height, rtOptions);
  const composer = new modules.EffectComposer(deps.renderer, renderTarget);
  composer.addPass(new modules.RenderPass(deps.scene, deps.camera));
  const bloomStrength = (): number =>
    clamp(
      params.bloomStrength * TIER_BLOOM_SCALE[tier] + bloomBoost + beatPulse * MAX_BEAT_BLOOM_BOOST,
      MAX_BLOOM_STRENGTH,
    );
  const bloom = new modules.UnrealBloomPass(
    { x: deps.width, y: deps.height },
    bloomStrength(),
    BLOOM_RADIUS,
    params.bloomThreshold,
  );
  composer.addPass(bloom);
  const atmosphere = new modules.ShaderPass(ATMOSPHERE_SHADER);
  composer.addPass(atmosphere);
  composer.addPass(new modules.OutputPass());
  composer.setSize(deps.width, deps.height);

  const applyAtmosphere = (): void => {
    bloom.strength = bloomStrength();
    bloom.threshold = params.bloomThreshold;
    atmosphere.uniforms.vignetteStrength!.value = clamp(params.vignetteStrength, MAX_VIGNETTE);
    atmosphere.uniforms.grainAmount!.value = clamp(params.grainOpacity, MAX_GRAIN);
  };
  applyAtmosphere();

  return {
    render(dt: number): void {
      if (disposed) return;
      const safeDt = Math.max(0, dt);
      grainClock += safeDt;
      // 离散步进更新 grain 时间轴：低频换帧的静态颗粒，不是逐帧闪烁
      atmosphere.uniforms.grainTime!.value =
        Math.floor(grainClock * GRAIN_STEPS_PER_SECOND) / GRAIN_STEPS_PER_SECOND;
      // M21.8 强拍 bloom 脉冲指数衰减（每帧按 dt 衰减）
      if (beatPulse > 0) {
        beatPulse *= Math.exp(-safeDt / BEAT_DECAY);
        if (beatPulse < 0.001) beatPulse = 0;
        bloom.strength = bloomStrength();
        // 色差强度随 beatPulse 线性映射（克制上限）
        atmosphere.uniforms.chromaticAberration!.value =
          (beatPulse / 3) * MAX_CHROMATIC_ABERRATION;
        // 暗角呼吸：beat 触发时启用，相位缓慢推进
        atmosphere.uniforms.vignetteBreath!.value =
          Math.min(MAX_VIGNETTE_BREATH, (beatPulse / 3) * MAX_VIGNETTE_BREATH);
        breathPhase += safeDt * 4; // ~0.64Hz 呼吸频率（克制慢速）
        atmosphere.uniforms.breathPhase!.value = breathPhase;
      } else {
        // beatPulse 归零后同步回落 bloom 与节奏后处理参数（避免残留高泛光）
        bloom.strength = bloomStrength();
        atmosphere.uniforms.chromaticAberration!.value = 0;
        atmosphere.uniforms.vignetteBreath!.value = 0;
      }
      composer.render();
    },

    resize(width: number, height: number): void {
      if (disposed) return;
      composer.setSize(width, height);
    },

    setQuality(next: QualityTierName): void {
      getTierSpec(next); // 非法档 → RangeError
      tier = next;
      if (disposed) return;
      bloom.strength = bloomStrength();
    },

    applyParams(next: SceneParams): void {
      params = next;
      if (disposed) return;
      applyAtmosphere();
    },

    setBloomBoost(boost: number): void {
      bloomBoost = Number.isFinite(boost) ? Math.max(0, boost) : 0;
      if (disposed) return;
      bloom.strength = bloomStrength();
    },

    setBeatPulse(strength: number): void {
      const s = Number.isFinite(strength) ? Math.min(3, Math.max(0, strength)) : 0;
      // 0 表示停止音乐模式（setAudioLevels(null)）：硬重置脉冲，让 bloom 立即回落
      if (s === 0) {
        beatPulse = 0;
        return;
      }
      // 取较大值：新拍点叠加到正在衰减的脉冲上（不覆盖更强的进行中脉冲）
      if (s > beatPulse) beatPulse = s;
    },

    setPixelRatio(ratio: number): void {
      if (disposed) return;
      composer.setPixelRatio?.(ratio);
    },

    getVignetteStrength(): number {
      return atmosphere.uniforms.vignetteStrength!.value as number;
    },

    getGrainAmount(): number {
      return atmosphere.uniforms.grainAmount!.value as number;
    },

    getBeatPulse(): number {
      return beatPulse;
    },

    dispose(): void {
      if (disposed) return;
      disposed = true;
      composer.dispose?.();
      renderTarget.dispose();
    },
  };
}
