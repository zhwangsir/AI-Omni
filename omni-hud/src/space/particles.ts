/**
 * particles GPU 实例化粒子系统（M5.2）：InstancedBufferGeometry + ShaderMaterial。
 * 实例属性：种子位置（三维体积分布，z 向拉开深度层次）、漂移速度、尺寸
 * （近大远小由 shader 透视承担）、色板索引（越界钳制）、相位；
 * soft radial sprite 程序纹理（DataTexture，无 DOM canvas 依赖）；
 * 加色混合、深度写出关闭；按画质档重建实例数（同种子重建 → 切换不闪断，
 * 旧 geometry dispose 不泄漏，material / texture 复用）。
 * three 模块全部经 deps 注入：本文件不做顶层 three import，测试以 fake 替换。
 */
import { ATTRACTOR_GLSL } from "./attractor";
import { FLOWFIELD_GLSL, FLOW_VELOCITY_MAX } from "./flowfield";
import { RIPPLE_GLSL, RIPPLE_MAX_CONCURRENT } from "./ripples";
import { PALETTE_SLOTS, type Rgb } from "./themeBridge";

/** 实例属性构建的固定种子：档切换重建时同一批粒子，视觉连续不闪断。 */
export const PARTICLE_SEED = 0x5eed;

/** 粒子体积分布半径（世界单位）：z 向刻意更深，拉开纵深层次。 */
export const VOLUME_EXTENT = { x: 4.2, y: 2.6, z: 3.8 } as const;

/** soft sprite 程序纹理边长（px）。 */
export const SPRITE_TEXTURE_SIZE = 64;

/** 基础点大小（配合 aSize 与透视缩放）。
 * 全息氛围粒子应当是微小光点而非大光圈——9px 基础尺寸经近大远小透视后，
 * 近处粒子约 10-14px，远处约 3-5px，形成星点场感。 */
const BASE_POINT_SIZE = 9;

/** 实例属性集（positions 即 aSeed）。 */
export interface ParticleAttributes {
  readonly positions: Float32Array;
  readonly velocities: Float32Array;
  readonly sizes: Float32Array;
  readonly colorIndices: Float32Array;
  readonly phases: Float32Array;
}

/** 确定性 LCG：同种子同序列（重建连续性 + 测试可复现）。 */
function createLcg(seed: number): () => number {
  let state = seed & 0x7fffffff;
  return () => {
    state = (state * 1103515245 + 12345) & 0x7fffffff;
    return state / 0x7fffffff;
  };
}

/**
 * 构建 count 个粒子的实例属性。count 必须为正整数，否则 RangeError。
 * 速度模长 ≤ FLOW_VELOCITY_MAX；色板索引整数且钳制在 [0, PALETTE_SLOTS-1]。
 */
export function buildInstanceAttributes(
  count: number,
  seed: number = PARTICLE_SEED,
): ParticleAttributes {
  if (!Number.isInteger(count) || count <= 0) {
    throw new RangeError(`粒子数必须为正整数: ${count}`);
  }
  const rand = createLcg(seed);
  const positions = new Float32Array(count * 3);
  const velocities = new Float32Array(count * 3);
  const sizes = new Float32Array(count);
  const colorIndices = new Float32Array(count);
  const phases = new Float32Array(count);
  for (let i = 0; i < count; i++) {
    // 体积均匀分布（cbrt 反采样），椭球拉伸，z 向最深
    const r = Math.cbrt(rand());
    const theta = rand() * Math.PI * 2;
    const phi = Math.acos(2 * rand() - 1);
    positions[i * 3] = r * Math.sin(phi) * Math.cos(theta) * VOLUME_EXTENT.x;
    positions[i * 3 + 1] = r * Math.cos(phi) * VOLUME_EXTENT.y;
    positions[i * 3 + 2] = r * Math.sin(phi) * Math.sin(theta) * VOLUME_EXTENT.z;
    // 漂移速度：随机方向 × 有界模长（0.2~1.0 × MAX，避免全同速的呆板）
    const vTheta = rand() * Math.PI * 2;
    const vPhi = Math.acos(2 * rand() - 1);
    const speed = (0.2 + 0.8 * rand()) * FLOW_VELOCITY_MAX;
    velocities[i * 3] = speed * Math.sin(vPhi) * Math.cos(vTheta);
    velocities[i * 3 + 1] = speed * Math.cos(vPhi);
    velocities[i * 3 + 2] = speed * Math.sin(vPhi) * Math.sin(vTheta);
    sizes[i] = 0.7 + rand() * 0.6;
    colorIndices[i] = Math.min(PALETTE_SLOTS - 1, Math.floor(rand() * PALETTE_SLOTS));
    phases[i] = rand() * Math.PI * 2;
  }
  return { positions, velocities, sizes, colorIndices, phases };
}

/**
 * 全息光点 sprite 程序纹理（RGBA 彩色）：锐利亮核 → 快速衰减金光晕 → 极边缘微暗。
 *
 * 设计原则——星点场而非大光圈：
 * - Alpha 从中心快速单调递减（d<0.1 为亮核，d<0.4 基本衰减完毕），
 *   不形成大软边圆斑，保持星点锐利感；
 * - 颜色：中心亮白（模拟高光 core）→ 过渡金色光晕 → 最外缘仅有极淡暗棕
 *   （d>0.7 且 alpha<0.05 时才出现，仅够在纯白背景上标记位置，完全不可见为"环"）；
 * - 整体效果：微小锐利的金白色光点，深色背景上像星点/全息尘埃，
 *   浅色背景上极淡金点几乎不察觉，不遮挡内容阅读。
 *
 * size 必须为正整数，否则 RangeError。
 */
export function createSpriteTextureData(size: number = SPRITE_TEXTURE_SIZE): Uint8Array {
  if (!Number.isInteger(size) || size <= 0) {
    throw new RangeError(`纹理尺寸必须为正整数: ${size}`);
  }
  const data = new Uint8Array(size * size * 4);
  const half = (size - 1) / 2;

  // 颜色（0-255）：亮白核 → 金光晕 → 极淡暗边
  const C0 = [255, 250, 238]; // core：高光白（略带暖调）
  const C1 = [225, 190, 120]; // halo：accent 金
  const C2 = [120, 95, 55];   // edge：淡棕金（比 halo 深，但远不到黑色——避免硬边环）

  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const dx = (x - half) / half;
      const dy = (y - half) / half;
      const d = Math.sqrt(dx * dx + dy * dy);

      // Alpha 快速单调递减——星点状而非大圆形（连续函数，无跳变）：
      // d=0 → a=1.0（锐利亮核）
      // d=0.1 → a≈0.36（核→晕过渡）
      // d=0.25 → a≈0.10（光晕快速消散）
      // d=0.5 → a≈0（完全透明，硬截止保证无软边拖尾）
      let a: number;
      if (d >= 0.5) {
        a = 0;
      } else {
        // 两段幂函数平滑拼接：核区快速跌落 + 晕区长尾快速归零
        const t = d / 0.5; // 归一化到 [0,1]
        a = Math.pow(1 - t, 2.2) * (1 - t * 0.15);
      }

      // 颜色插值（d<0.5 范围内，d≥0.5 时 a=0 无像素输出）：
      // d<0.08 → 白核；0.08<d<0.28 → 金晕过渡；d>0.28 → 极淡暗边（仅在 a<0.1 处微显）
      let r: number, g: number, b: number;
      if (d < 0.08) {
        r = C0[0]; g = C0[1]; b = C0[2];
      } else if (d < 0.28) {
        const t = (d - 0.08) / 0.2;
        const s = t * t * (3 - 2 * t);
        r = C0[0] + (C1[0] - C0[0]) * s;
        g = C0[1] + (C1[1] - C0[1]) * s;
        b = C0[2] + (C1[2] - C0[2]) * s;
      } else {
        const t = Math.min(1, (d - 0.28) / 0.22);
        const s = t * t;
        r = C1[0] * (1 - s * 0.3) + C2[0] * s * 0.3;
        g = C1[1] * (1 - s * 0.3) + C2[1] * s * 0.3;
        b = C1[2] * (1 - s * 0.3) + C2[2] * s * 0.3;
      }

      const offset = (y * size + x) * 4;
      data[offset] = Math.max(0, Math.min(255, Math.round(r)));
      data[offset + 1] = Math.max(0, Math.min(255, Math.round(g)));
      data[offset + 2] = Math.max(0, Math.min(255, Math.round(b)));
      data[offset + 3] = Math.max(0, Math.min(255, Math.round(a * 255)));
    }
  }
  return data;
}

/** 粒子系统消费的最小 three 结构契约（真实 three 与 fake 均满足）。 */
export interface InstancedGeometryLike {
  instanceCount: number;
  setAttribute(name: string, attribute: unknown): void;
  getAttribute?(name: string): unknown;
  dispose(): void;
}

export interface TextureLike {
  needsUpdate: boolean;
  dispose(): void;
}

export interface ParticleMaterialLike {
  readonly uniforms: Record<string, { value: unknown }>;
  dispose(): void;
}

export interface PointsLike {
  geometry: unknown;
}

export interface ParticleThree {
  InstancedBufferGeometry: new () => InstancedGeometryLike;
  InstancedBufferAttribute: new (array: Float32Array, itemSize: number) => unknown;
  BufferAttribute: new (array: Float32Array, itemSize: number) => unknown;
  DataTexture: new (data: Uint8Array, width: number, height: number) => TextureLike;
  ShaderMaterial: new (options: {
    uniforms: Record<string, { value: unknown }>;
    vertexShader: string;
    fragmentShader: string;
    transparent?: boolean;
    depthWrite?: boolean;
    depthTest?: boolean;
    blending?: unknown;
  }) => ParticleMaterialLike;
  Points: new (geometry: unknown, material: unknown) => PointsLike;
  AdditiveBlending: unknown;
  NormalBlending: unknown;
}

export interface ParticleSystemDeps {
  readonly three: ParticleThree;
  readonly count: number;
  readonly seed?: number;
}

export interface ParticleSystem {
  /** 场景挂载用的 Points 对象。 */
  readonly points: PointsLike;
  /** 材质 uniforms（uFlowTime / uMorphFactor / uAttractor / uAttractorStrength / uPalette …）。 */
  readonly uniforms: Record<string, { value: unknown }>;
  /** 材质构造参数（透明 / 深度写出关闭 / 加色混合契约的测试探针）。 */
  readonly materialOptions: { transparent?: boolean; depthWrite?: boolean; depthTest?: boolean; blending?: unknown };
  /** 当前实例数。 */
  getCount(): number;
  /** 按画质档重建实例数：同种子 → 视觉连续；旧 geometry dispose；material/texture 复用。 */
  setCount(count: number): void;
  /** 上传形状目标点（长度必须 = count*3，否则 RangeError）。 */
  setShapeTargets(targets: Float32Array): void;
  /** 快照当前目标为 from，上传新目标为 to，开启形状间插值混合（t=0 回到 from 避免闪现）。 */
  beginShapeBlend(toTargets: Float32Array): void;
  /** 将目标插值到 t（0=from 旧形态，1=to 新形态）；未 begin 时 no-op。 */
  stepShapeBlend(t: number): void;
  /** 结束形状混合：精确落位到 to 目标，释放快照缓冲。 */
  endShapeBlend(): void;
  /** 取消形状混合：释放快照缓冲，保持当前插值位置。 */
  cancelShapeBlend(): void;
  /** 写入 6 槽色板 uniform；超过 PALETTE_SLOTS 色抛 RangeError（硬校验）。 */
  setPalette(palette: readonly Rgb[]): void;
  /** 幂等：释放 geometry / material / texture。 */
  dispose(): void;
}

/** 粒子 vertex shader：流场 → 水波纹径向位移 → morph lerp → 吸引子 → 透视点大小。 */
const PARTICLE_VERTEX = /* glsl */ `
  ${FLOWFIELD_GLSL}
  ${ATTRACTOR_GLSL}
  ${RIPPLE_GLSL}
  attribute vec3 aSeed;
  attribute vec3 aVelocity;
  attribute float aSize;
  attribute float aColorIndex;
  attribute float aPhase;
  attribute vec3 aTarget;
  uniform float uFlowTime;
  uniform float uMorphFactor;
  uniform vec3 uAttractor;
  uniform float uAttractorStrength;
  uniform float uSize;
  uniform float uPixelRatio;
  uniform vec3 uPalette[${PALETTE_SLOTS}];
  // M7.3 场语义参数（默认 no-op：dim=1 / 吸引子强度=0 / 角速度=0 / brightnessLift=0）
  uniform float uFieldDim;
  uniform vec3 uFieldAttractor;
  uniform float uFieldAttractorStrength;
  uniform vec3 uFieldOrbitCenter;
  uniform float uFieldOrbitAngularVel;
  uniform float uFieldBrightnessLift;
  // 四态粒子形态动画（默认 no-op：pulse=0 / rotAngle=0）
  uniform float uPulseStrength;
  uniform float uShapeRotAngle;
  uniform float uShapeScale;
  uniform float uFlickerIntensity;
  uniform float uFlickerSpeed;
  uniform float uGlowBoost;
  // M21.3 音频节奏同步（默认 no-op：均为 0，非音乐模式行为不变）
  // 低频→大粒子脉冲 / 中频→流速倍率 / 高频→闪烁增量 / 强拍→爆发尺寸
  uniform float uBassLevel;
  uniform float uMidLevel;
  uniform float uTrebleLevel;
  uniform float uBeatStrength;
  // M23.3 天气情绪联动（默认 no-op：均为 1.0，无天气情绪时行为不变）
  // uWeatherSpeed 流速倍率 [0.3, 2.0]，乘入 flowRate（与 M21 中频倍率正交叠加）
  // uWeatherBrightness 亮度倍率 [0.2, 1.0]，乘入 vAlpha（与 fieldDim/brightnessLift 正交）
  uniform float uWeatherSpeed;
  uniform float uWeatherBrightness;
  varying vec3 vColor;
  varying float vAlpha;
  varying float vGlow;
  varying float vFlicker;
  void main() {
    // M21.3 中频驱动流场时钟倍率（music 模式下流速随中频浮动，默认 1.0）
    // M23.3 天气情绪流速倍率正交叠加（uWeatherSpeed 默认 1.0 = no-op）
    float flowRate = (1.0 + uMidLevel * 0.6) * uWeatherSpeed;
    vec3 flowPos = aSeed + omniFlowOffset(aSeed, aVelocity, aPhase, uFlowTime * flowRate);
    flowPos += omniRippleOffset(flowPos); // M5.3：点击水波纹沿流场扩散（morph 时随 lerp 淡出）
    // 形状目标点：先应用 x 轴自转（DNA 螺旋），再应用心跳脉冲（球呼吸）
    vec3 shapePos = aTarget;
    float src = cos(uShapeRotAngle);
    float srs = sin(uShapeRotAngle);
    float sry = shapePos.y * src - shapePos.z * srs;
    float srz = shapePos.y * srs + shapePos.z * src;
    shapePos.y = sry;
    shapePos.z = srz;
    float beat = sin(uFlowTime * 3.5 + aPhase * 0.3);
    float pulseScale = 1.0 + uPulseStrength * 0.12 * beat;
    // M21.3 低频脉冲：bass 段能量额外放大形态呼吸（克制 0.18 上限，避免形变失控）
    float bassPulse = 1.0 + uBassLevel * 0.18 * beat;
    shapePos *= pulseScale * uShapeScale * bassPulse;
    vec3 pos = mix(flowPos, shapePos, uMorphFactor);
    // M21.3 强拍爆发：beat 触发时径向外推（指数衰减，强度 ≤0.15 避免粒子飞散）
    if (uBeatStrength > 0.001) {
      vec3 burstDir = normalize(shapePos + vec3(0.001));
      pos += burstDir * uBeatStrength * 0.15 * (0.5 + 0.5 * sin(aPhase));
    }
    // 指针吸引子：在自由流场（morphFactor=0）时最强，完全成形（morphFactor=1）时衰减到 0.25 倍，
    // 避免球体被鼠标拉扯变形，仅保留极轻微的向光性暗示
    float attractStrength = uAttractorStrength * (1.0 - uMorphFactor * 0.75);
    pos += omniAttractOffset(pos, uAttractor, attractStrength);
    // M7.3 场语义倾向点（井心吸引子，与指针吸引子独立叠加；默认强度 0 = no-op）
    pos += omniAttractOffset(pos, uFieldAttractor, uFieldAttractorStrength);
    // M7.3 场语义轨道流（绕井心缓速旋转；默认角速度 0 → cos=1/sin=0，位置不变）
    float orbitAngle = uFieldOrbitAngularVel * uFlowTime;
    float oc = cos(orbitAngle);
    float os = sin(orbitAngle);
    vec3 orbitRel = pos - uFieldOrbitCenter;
    pos.x = uFieldOrbitCenter.x + oc * orbitRel.x - os * orbitRel.y;
    pos.y = uFieldOrbitCenter.y + os * orbitRel.x + oc * orbitRel.y;
    vColor = uPalette[int(aColorIndex + 0.5)];
    vec4 mv = modelViewMatrix * vec4(pos, 1.0);
    gl_Position = projectionMatrix * mv;
    // 近大远小自然透视；呼吸明暗（慢速，非频闪）；场 dim 系数乘入亮度（默认 1 = 不变）；
    // brightnessLift 为加法增量（≤0.2 红线，与 mood bloomBoost 通路正交独立）。
    // 基础 alpha 0.45 + 呼吸 0.08——粒子作为全息氛围层存在，不遮挡下层内容阅读。
    // 闪烁：基于相位的正弦波，不同粒子有不同相位形成波状 shimmer 而非集体闪
    float flickerWave = sin(uFlowTime * uFlickerSpeed * 6.2832 + aPhase * 2.0);
    float flickerEnv = 0.5 + 0.5 * flickerWave;
    float flicker = uFlickerIntensity * (flickerEnv - 0.5) * 2.0;
    // M21.3 高频闪烁：treble 段额外驱动高频微闪（克制 0.2 上限，避免光敏风险）
    float trebleFlicker = uTrebleLevel * 0.2 * sin(uFlowTime * 18.0 + aPhase * 5.0);
    flicker += trebleFlicker;
    vFlicker = flicker;
    float sizeBoost = 1.0 + uGlowBoost * 0.6 + flicker * 0.15;
    // M21.3 强拍尺寸爆发：beat 触发时点尺寸额外放大（≤0.4 上限）
    float beatSizeBoost = 1.0 + uBeatStrength * 0.4;
    gl_PointSize = aSize * uSize * uPixelRatio * (6.0 / -mv.z) * max(0.5, sizeBoost * beatSizeBoost);
    float baseAlpha = 0.45 + 0.08 * sin(uFlowTime * 0.4 + aPhase);
    float glowAdd = uGlowBoost * 0.25;
    // M21.3 低频亮度提升：bass 段额外提亮（≤0.15 上限，与 brightnessLift 正交）
    float bassLift = uBassLevel * 0.15;
    vAlpha = (baseAlpha + flicker * 0.5 + glowAdd + uFieldBrightnessLift + bassLift) * uFieldDim * uWeatherBrightness;
    vGlow = uGlowBoost + flicker * 0.3 + uBeatStrength * 0.2;
  }
`;

/** 粒子 fragment：全息光点 sprite × 色板淡染色。
 *
 * sprite 自带白核→金→暗边颜色；vColor 作为极淡色调偏移（30%）融入光晕区，
 * 既支持主题切换又不破坏金白色全息基调。核心保持亮白不过度染色。
 */
const PARTICLE_FRAGMENT = /* glsl */ `
  precision mediump float;
  uniform sampler2D uSprite;
  varying vec3 vColor;
  varying float vAlpha;
  varying float vGlow;
  varying float vFlicker;
  void main() {
    vec4 tex = texture2D(uSprite, gl_PointCoord);
    float luminance = dot(tex.rgb, vec3(0.299, 0.587, 0.114));
    float tintFactor = smoothstep(0.3, 0.75, luminance);
    vec3 colored = mix(tex.rgb, vColor * 1.1, tintFactor * 0.3);
    float glowHalo = vGlow * (1.0 - luminance) * 0.4;
    vec3 glowColor = colored + vec3(glowHalo * 0.3, glowHalo * 0.2, glowHalo * 0.1);
    // 闪烁同时影响亮度（不仅仅是alpha），让明暗变化更有"脉动呼吸"感
    float flickerBrightness = 1.0 + vFlicker * 0.25;
    vec3 finalColor = glowColor * flickerBrightness;
    float a = tex.a * vAlpha;
    gl_FragColor = vec4(finalColor, a);
  }
`;

export function createParticleSystem(deps: ParticleSystemDeps): ParticleSystem {
  const three = deps.three;
  const seed = deps.seed ?? PARTICLE_SEED;
  let count = deps.count;
  buildInstanceAttributes(count, seed); // 入参校验（非法 count → RangeError）

  const texture = new three.DataTexture(
    createSpriteTextureData(SPRITE_TEXTURE_SIZE),
    SPRITE_TEXTURE_SIZE,
    SPRITE_TEXTURE_SIZE,
  );
  texture.needsUpdate = true;

  const materialOptions = {
    transparent: true,
    depthWrite: false,
    depthTest: false,
    blending: three.NormalBlending,
  };
  const material = new three.ShaderMaterial({
    uniforms: {
      uSprite: { value: texture },
      uPalette: { value: new Float32Array(PALETTE_SLOTS * 3) },
      uFlowTime: { value: 0 },
      uMorphFactor: { value: 0 },
      uAttractor: { value: { x: 0, y: 0, z: 0 } },
      uAttractorStrength: { value: 0 },
      uSize: { value: BASE_POINT_SIZE },
      uPixelRatio: { value: 1 },
      // M5.3 水波纹：origin vec3 × 4 槽 + (t0, duration) 秒 × 4 槽 + 当前时刻（秒）
      uRippleOrigins: { value: new Float32Array(RIPPLE_MAX_CONCURRENT * 3) },
      uRippleTimes: { value: new Float32Array(RIPPLE_MAX_CONCURRENT * 2) },
      uNowSec: { value: 0 },
      // M7.3 场语义参数：默认 no-op（dim=1 / 吸引子强度=0 / 角速度=0 / brightnessLift=0），
      // 由 createSpace.setField(FieldParams) 桥接写入——场未接时渲染等价于 M5 行为。
      uFieldDim: { value: 1 },
      uFieldAttractor: { value: { x: 0, y: 0, z: 0 } },
      uFieldAttractorStrength: { value: 0 },
      uFieldOrbitCenter: { value: { x: 0, y: 0, z: 0 } },
      uFieldOrbitAngularVel: { value: 0 },
      uFieldBrightnessLift: { value: 0 },
      // 四态粒子形态动画：心跳脉冲强度 [0,1]；螺旋 x 轴自转累积角（rad，由 JS 递增）
      uPulseStrength: { value: 0 },
      uShapeRotAngle: { value: 0 },
      uShapeScale: { value: 1.0 },
      uFlickerIntensity: { value: 0 },
      uFlickerSpeed: { value: 0 },
      uGlowBoost: { value: 0 },
      // M21.3 音频节奏同步：默认 0（非音乐模式 no-op）；bass/mid/treble ∈ [0,1]、beat ∈ [0,3]
      uBassLevel: { value: 0 },
      uMidLevel: { value: 0 },
      uTrebleLevel: { value: 0 },
      uBeatStrength: { value: 0 },
      // M23.3 天气情绪联动：默认 1.0（no-op，无天气情绪时行为不变）
      // uWeatherSpeed ∈ [0.3, 2.0] 流速倍率 / uWeatherBrightness ∈ [0.2, 1.0] 亮度倍率
      uWeatherSpeed: { value: 1 },
      uWeatherBrightness: { value: 1 },
    },
    vertexShader: PARTICLE_VERTEX,
    fragmentShader: PARTICLE_FRAGMENT,
    ...materialOptions,
  });

  let targetAttr: { array: Float32Array; needsUpdate?: boolean } | null = null;
  let geometry = buildGeometry(count);
  const points = new three.Points(geometry, material);

  let blendFrom: Float32Array | null = null;
  let blendTo: Float32Array | null = null;

  function buildGeometry(nextCount: number): InstancedGeometryLike {
    const data = buildInstanceAttributes(nextCount, seed);
    const geo = new three.InstancedBufferGeometry();
    // 单顶点 × instanceCount 实例：Points 每实例绘一个 sprite
    geo.setAttribute("position", new three.BufferAttribute(new Float32Array(3), 3));
    geo.setAttribute("aSeed", new three.InstancedBufferAttribute(data.positions, 3));
    geo.setAttribute("aVelocity", new three.InstancedBufferAttribute(data.velocities, 3));
    geo.setAttribute("aSize", new three.InstancedBufferAttribute(data.sizes, 1));
    geo.setAttribute("aColorIndex", new three.InstancedBufferAttribute(data.colorIndices, 1));
    geo.setAttribute("aPhase", new three.InstancedBufferAttribute(data.phases, 1));
    // 初始目标 = 种子位置（morphFactor 为 0 时无影响；首次成形从原位出发）
    const targets = new Float32Array(data.positions);
    const attr = new three.InstancedBufferAttribute(targets, 3) as {
      array: Float32Array;
      needsUpdate?: boolean;
    };
    targetAttr = attr;
    geo.setAttribute("aTarget", attr);
    geo.instanceCount = nextCount;
    return geo;
  }

  let disposed = false;

  function stepShapeBlendInternal(t: number): void {
    if (disposed || !targetAttr || !blendFrom || !blendTo) return;
    const arr = targetAttr.array as Float32Array;
    const from = blendFrom;
    const to = blendTo;
    const s = Math.min(1, Math.max(0, t));
    for (let i = 0; i < arr.length; i++) {
      arr[i] = from[i]! + (to[i]! - from[i]!) * s;
    }
    targetAttr.needsUpdate = true;
  }

  function cancelShapeBlendInternal(): void {
    blendFrom = null;
    blendTo = null;
  }

  return {
    points,
    uniforms: material.uniforms,
    materialOptions,

    getCount(): number {
      return count;
    },

    setCount(nextCount: number): void {
      buildInstanceAttributes(nextCount, seed); // 校验
      if (disposed || nextCount === count) return;
      cancelShapeBlendInternal();
      const old = geometry;
      geometry = buildGeometry(nextCount);
      count = nextCount;
      points.geometry = geometry;
      old.dispose(); // 旧 geometry 立即释放，不泄漏
    },

    setShapeTargets(targets: Float32Array): void {
      if (targets.length !== count * 3) {
        throw new RangeError(`形状目标点数 ${targets.length / 3} 与粒子数 ${count} 不匹配`);
      }
      if (disposed || !targetAttr) return;
      cancelShapeBlendInternal();
      targetAttr.array.set(targets);
      targetAttr.needsUpdate = true;
    },

    beginShapeBlend(toTargets: Float32Array): void {
      if (toTargets.length !== count * 3) {
        throw new RangeError(`形状目标点数 ${toTargets.length / 3} 与粒子数 ${count} 不匹配`);
      }
      if (disposed || !targetAttr) return;
      blendFrom = new Float32Array(targetAttr.array as Float32Array);
      blendTo = new Float32Array(toTargets);
      stepShapeBlendInternal(0);
    },

    stepShapeBlend(t: number): void {
      stepShapeBlendInternal(t);
    },

    endShapeBlend(): void {
      if (!blendTo || !targetAttr) {
        blendFrom = null;
        blendTo = null;
        return;
      }
      (targetAttr.array as Float32Array).set(blendTo);
      targetAttr.needsUpdate = true;
      blendFrom = null;
      blendTo = null;
    },

    cancelShapeBlend(): void {
      cancelShapeBlendInternal();
    },

    setPalette(palette: readonly Rgb[]): void {
      if (palette.length > PALETTE_SLOTS) {
        throw new RangeError(`主题色板 ${palette.length} 色超过 ${PALETTE_SLOTS} 槽硬上限`);
      }
      if (disposed) return;
      const data = material.uniforms.uPalette!.value as Float32Array;
      for (let i = 0; i < palette.length; i++) {
        const color = palette[i]!;
        data[i * 3] = color[0];
        data[i * 3 + 1] = color[1];
        data[i * 3 + 2] = color[2];
      }
    },

    dispose(): void {
      if (disposed) return;
      disposed = true;
      geometry.dispose();
      material.dispose();
      texture.dispose();
    },
  };
}
