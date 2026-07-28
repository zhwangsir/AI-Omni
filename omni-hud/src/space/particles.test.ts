/**
 * particles 测试（M5.2 TDD 红）：GPU 实例化粒子系统——
 * 实例 attribute 构建器（种子位置 / 漂移速度 / 尺寸 / 色板索引 / 相位）、
 * soft radial sprite 程序纹理、InstancedBufferGeometry + ShaderMaterial 装配、
 * 按画质档重建实例数（旧 geometry dispose 不泄漏）、色板 uniform 映射与 ≤6 硬校验。
 * 全部 fake three，不碰真实 WebGL。
 */
import { describe, expect, it, vi } from "vitest";

import { FLOW_VELOCITY_MAX } from "./flowfield";
import {
  PARTICLE_SEED,
  SPRITE_TEXTURE_SIZE,
  VOLUME_EXTENT,
  buildInstanceAttributes,
  createParticleSystem,
  createSpriteTextureData,
  type ParticleThree,
} from "./particles";
import { PALETTE_SLOTS, type Rgb } from "./themeBridge";

/** fake three 子集：仅粒子系统消费的契约。 */
function makeFakeParticleThree() {
  const geometries: FakeInstancedBufferGeometry[] = [];
  const textures: FakeDataTexture[] = [];
  const materialDispose = vi.fn();

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
  class FakeInstancedBufferGeometry {
    instanceCount = 0;
    dispose = vi.fn();
    private attrs = new Map<string, FakeInstancedBufferAttribute>();
    setAttribute(name: string, attr: FakeInstancedBufferAttribute) {
      this.attrs.set(name, attr);
    }
    getAttribute(name: string) {
      return this.attrs.get(name);
    }
    constructor() {
      geometries.push(this);
    }
  }
  class FakeBufferAttribute {
    constructor(
      public array: Float32Array,
      public itemSize: number,
    ) {}
  }
  class FakeDataTexture {
    needsUpdate = false;
    dispose = vi.fn();
    constructor(
      public data: Uint8Array,
      public width: number,
      public height: number,
    ) {
      textures.push(this);
    }
  }
  class FakeShaderMaterial {
    uniforms: Record<string, { value: unknown }>;
    dispose = materialDispose;
    constructor(public opts: { uniforms: Record<string, { value: unknown }> }) {
      this.uniforms = opts.uniforms;
    }
  }
  class FakePoints {
    constructor(
      public geometry: FakeInstancedBufferGeometry,
      public material: FakeShaderMaterial,
    ) {}
  }

  const three = {
    InstancedBufferGeometry: FakeInstancedBufferGeometry,
    InstancedBufferAttribute: FakeInstancedBufferAttribute,
    BufferAttribute: FakeBufferAttribute,
    DataTexture: FakeDataTexture,
    ShaderMaterial: FakeShaderMaterial,
    Points: FakePoints,
    AdditiveBlending: 2,
    NormalBlending: 1,
  };
  return { three: three as unknown as ParticleThree, geometries, textures, materialDispose };
}

describe("buildInstanceAttributes 实例属性构建", () => {
  it("每个字段长度与 count 匹配（位置/速度 vec3，尺寸/色相/相位 float）", () => {
    const data = buildInstanceAttributes(4000);
    expect(data.positions.length).toBe(4000 * 3);
    expect(data.velocities.length).toBe(4000 * 3);
    expect(data.sizes.length).toBe(4000);
    expect(data.colorIndices.length).toBe(4000);
    expect(data.phases.length).toBe(4000);
  });

  it("种子位置落在体积分布界内，z 向拉开深度层次", () => {
    const data = buildInstanceAttributes(2000);
    let minZ = Number.POSITIVE_INFINITY;
    let maxZ = Number.NEGATIVE_INFINITY;
    for (let i = 0; i < 2000; i++) {
      expect(Math.abs(data.positions[i * 3]!)).toBeLessThanOrEqual(VOLUME_EXTENT.x + 1e-6);
      expect(Math.abs(data.positions[i * 3 + 1]!)).toBeLessThanOrEqual(VOLUME_EXTENT.y + 1e-6);
      const z = data.positions[i * 3 + 2]!;
      expect(Math.abs(z)).toBeLessThanOrEqual(VOLUME_EXTENT.z + 1e-6);
      minZ = Math.min(minZ, z);
      maxZ = Math.max(maxZ, z);
    }
    // z 向确实有深度铺开（不是扁平面）
    expect(maxZ - minZ).toBeGreaterThan(VOLUME_EXTENT.z);
  });

  it("漂移速度有界（≤ FLOW_VELOCITY_MAX），尺寸为正且近大远小由 shader 透视承担", () => {
    const data = buildInstanceAttributes(1500);
    for (let i = 0; i < 1500; i++) {
      const speed = Math.hypot(
        data.velocities[i * 3]!,
        data.velocities[i * 3 + 1]!,
        data.velocities[i * 3 + 2]!,
      );
      expect(speed).toBeLessThanOrEqual(FLOW_VELOCITY_MAX + 1e-6);
      expect(data.sizes[i]!).toBeGreaterThan(0);
      expect(data.phases[i]!).toBeGreaterThanOrEqual(0);
      expect(data.phases[i]!).toBeLessThanOrEqual(Math.PI * 2 + 1e-6);
    }
  });

  it("色板索引钳制在 [0, PALETTE_SLOTS-1]（越界防护）", () => {
    const data = buildInstanceAttributes(3000);
    for (let i = 0; i < 3000; i++) {
      const idx = data.colorIndices[i]!;
      expect(Number.isInteger(idx)).toBe(true);
      expect(idx).toBeGreaterThanOrEqual(0);
      expect(idx).toBeLessThanOrEqual(PALETTE_SLOTS - 1);
    }
  });

  it("同种子构建结果确定（档切换重建不闪断的关键）", () => {
    const a = buildInstanceAttributes(800, PARTICLE_SEED);
    const b = buildInstanceAttributes(800, PARTICLE_SEED);
    expect(Array.from(a.positions)).toEqual(Array.from(b.positions));
  });

  it("非法 count 抛 RangeError", () => {
    expect(() => buildInstanceAttributes(0)).toThrow(RangeError);
    expect(() => buildInstanceAttributes(-10)).toThrow(RangeError);
    expect(() => buildInstanceAttributes(1.5)).toThrow(RangeError);
  });
});

describe("createSpriteTextureData 程序纹理", () => {
  it("生成 size×size 的 RGBA 数据", () => {
    const data = createSpriteTextureData(SPRITE_TEXTURE_SIZE);
    expect(data.length).toBe(SPRITE_TEXTURE_SIZE * SPRITE_TEXTURE_SIZE * 4);
  });

  it("径向柔边：中心不透明、边缘透明（soft radial sprite）", () => {
    const size = SPRITE_TEXTURE_SIZE;
    const data = createSpriteTextureData(size);
    const alphaAt = (x: number, y: number): number => data[(y * size + x) * 4 + 3]!;
    const center = alphaAt(size / 2, size / 2);
    const corner = alphaAt(1, 1);
    const midEdge = alphaAt(size / 2, 2);
    expect(center).toBeGreaterThan(200);
    expect(corner).toBe(0);
    expect(midEdge).toBeLessThan(center);
  });

  it("非法尺寸抛 RangeError", () => {
    expect(() => createSpriteTextureData(0)).toThrow(RangeError);
    expect(() => createSpriteTextureData(-4)).toThrow(RangeError);
  });
});

describe("createParticleSystem 装配与重建", () => {
  it("按 count 创建 InstancedBufferGeometry，实例属性全部上传", () => {
    const { three, geometries } = makeFakeParticleThree();
    const system = createParticleSystem({ three, count: 4000 });
    const geometry = geometries[0]!;
    expect(geometry.instanceCount).toBe(4000);
    expect(geometry.getAttribute("aSeed")!.count).toBe(4000);
    expect(geometry.getAttribute("aVelocity")!.count).toBe(4000);
    expect(geometry.getAttribute("aSize")!.count).toBe(4000);
    expect(geometry.getAttribute("aColorIndex")!.count).toBe(4000);
    expect(geometry.getAttribute("aPhase")!.count).toBe(4000);
    expect(geometry.getAttribute("aTarget")!.count).toBe(4000);
    system.dispose();
  });

  it("材质为 Normal 混合、depthWrite/depthTest 关闭、transparent（可见性契约：深浅背景均可见）", () => {
    const { three } = makeFakeParticleThree();
    const system = createParticleSystem({ three, count: 800 });
    const opts = system.materialOptions;
    expect(opts.transparent).toBe(true);
    expect(opts.depthWrite).toBe(false);
    expect(opts.depthTest).toBe(false);
    expect(opts.blending).toBe(1); // NormalBlending
    system.dispose();
  });

  it("setCount 重建实例数：旧 geometry dispose（不泄漏），material 复用（不闪断）", () => {
    const { three, geometries, materialDispose } = makeFakeParticleThree();
    const system = createParticleSystem({ three, count: 4000 });
    system.setCount(800);
    expect(geometries).toHaveLength(2);
    expect(geometries[0]!.dispose).toHaveBeenCalledTimes(1);
    expect(geometries[1]!.instanceCount).toBe(800);
    expect(geometries[1]!.getAttribute("aSeed")!.count).toBe(800);
    expect(materialDispose).not.toHaveBeenCalled(); // 材质不换 → uniform 保持，无闪断
    // 同 count 重建是 no-op（不折腾 GPU）
    system.setCount(800);
    expect(geometries).toHaveLength(2);
    system.dispose();
  });

  it("setShapeTargets 上传成形目标点；长度不匹配抛 RangeError", () => {
    const { three, geometries } = makeFakeParticleThree();
    const system = createParticleSystem({ three, count: 100 });
    const targets = new Float32Array(100 * 3).fill(0.5);
    system.setShapeTargets(targets);
    const attr = geometries[0]!.getAttribute("aTarget")!;
    expect(attr.array[0]).toBe(0.5);
    expect(attr.needsUpdate).toBe(true);
    expect(() => system.setShapeTargets(new Float32Array(10 * 3))).toThrow(RangeError);
    system.dispose();
  });

  it("setPalette 写入 6 槽色板 uniform；超过 6 色抛 RangeError（硬校验）", () => {
    const { three } = makeFakeParticleThree();
    const system = createParticleSystem({ three, count: 100 });
    const palette: Rgb[] = [
      [0.1, 0.2, 0.3],
      [0.4, 0.5, 0.6],
    ];
    system.setPalette(palette);
    const uPalette = system.uniforms.uPalette!.value as Float32Array;
    expect(uPalette.length).toBe(PALETTE_SLOTS * 3);
    expect(uPalette[0]).toBeCloseTo(0.1, 5);
    expect(uPalette[5]).toBeCloseTo(0.6, 5);
    const tooMany: Rgb[] = Array.from({ length: PALETTE_SLOTS + 1 }, () => [0, 0, 0] as Rgb);
    expect(() => system.setPalette(tooMany)).toThrow(RangeError);
    system.dispose();
  });

  it("dispose 释放 geometry / material / texture", () => {
    const { three, geometries, textures, materialDispose } = makeFakeParticleThree();
    const system = createParticleSystem({ three, count: 100 });
    system.dispose();
    expect(geometries[0]!.dispose).toHaveBeenCalledTimes(1);
    expect(materialDispose).toHaveBeenCalledTimes(1);
    expect(textures[0]!.dispose).toHaveBeenCalledTimes(1);
    // 幂等
    expect(() => system.dispose()).not.toThrow();
    expect(materialDispose).toHaveBeenCalledTimes(1);
  });
});

describe("createParticleSystem 形态动画 uniforms（四态粒子：pulse + helix rotation）", () => {
  it("默认 uniforms 含 uPulseStrength=0 与 uShapeRotAngle=0（初始无动画）", () => {
    const { three } = makeFakeParticleThree();
    const system = createParticleSystem({ three, count: 100 });
    expect(system.uniforms.uPulseStrength).toBeDefined();
    expect(system.uniforms.uPulseStrength!.value).toBe(0);
    expect(system.uniforms.uShapeRotAngle).toBeDefined();
    expect(system.uniforms.uShapeRotAngle!.value).toBe(0);
    system.dispose();
  });

  it("uPulseStrength 可由外部写入（0 无脉冲，1 最大脉冲），shader 侧按固定频率驱动心跳", () => {
    const { three } = makeFakeParticleThree();
    const system = createParticleSystem({ three, count: 100 });
    system.uniforms.uPulseStrength!.value = 0.6;
    expect(system.uniforms.uPulseStrength!.value).toBe(0.6);
    // 边界：钳制预期由调用方保证；uniform 接受任意数值（shader 内 clamp）
    system.uniforms.uPulseStrength!.value = 0;
    expect(system.uniforms.uPulseStrength!.value).toBe(0);
    system.dispose();
  });

  it("uShapeRotAngle 为累积旋转角（rad），由外部帧循环递增驱动螺旋自转", () => {
    const { three } = makeFakeParticleThree();
    const system = createParticleSystem({ three, count: 100 });
    // 初始为 0
    expect(system.uniforms.uShapeRotAngle!.value).toBe(0);
    // 模拟帧递增值
    system.uniforms.uShapeRotAngle!.value = 1.5;
    expect(system.uniforms.uShapeRotAngle!.value).toBe(1.5);
    system.uniforms.uShapeRotAngle!.value = 6.28;
    expect(system.uniforms.uShapeRotAngle!.value).toBe(6.28);
    system.dispose();
  });
});
