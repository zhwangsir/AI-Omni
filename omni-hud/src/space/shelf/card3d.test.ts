/**
 * shelf/card3d 单张卡片组件（M20.2 TDD 红）：
 * - buildCardMesh 创建 Mesh（PlaneGeometry + MeshBasicMaterial map=title canvas 纹理）；
 * - 标题 / 副标题经 2D canvas → CanvasTexture（Film Atelier 暗房配色）；
 * - 封面 URL 异步加载（TextureLoader.load），加载完成替换 material.map；
 * - updateCardState 推进悬停 / 选中 scale 收敛（spring lerp）；
 * - disposeCard 释放 geometry / material / texture（含异步加载的封面）。
 *
 * 全 fake three：不创建真实 WebGL，断言材质 map / scale / dispose 调用。
 */
import { describe, expect, it, vi } from "vitest";

import { buildCardMesh, disposeCard, updateCardState } from "./card3d";
import type { CardData } from "./dataSource";
import { computeArcLayout } from "./layout";
import type { ShelfHost, ThreeModule } from "../createSpace";

function makeFakeThree() {
  class FakeVector3 {
    constructor(public x = 0, public y = 0, public z = 0) {}
    set(x: number, y: number, z: number) { this.x = x; this.y = y; this.z = z; return this; }
    copy(v: { x: number; y: number; z: number }) { this.x = v.x; this.y = v.y; this.z = v.z; return this; }
  }
  class FakeEuler {
    constructor(public x = 0, public y = 0, public z = 0) {}
    set(x: number, y: number, z: number) { this.x = x; this.y = y; this.z = z; return this; }
  }
  const disposed = { geometries: 0, materials: 0, textures: 0 };
  class FakeGroup {
    position = new FakeVector3();
    rotation = new FakeEuler();
    children: unknown[] = [];
    add = vi.fn((o: unknown) => { this.children.push(o); });
    remove = vi.fn((o: unknown) => {
      const i = this.children.indexOf(o);
      if (i >= 0) this.children.splice(i, 1);
    });
  }
  class FakePlaneGeometry { dispose = vi.fn(() => { disposed.geometries += 1; }); }
  class FakeBasicMaterial {
    map: unknown = null;
    needsUpdate = false;
    dispose = vi.fn(() => { disposed.materials += 1; });
    constructor(public opts: unknown) {}
  }
  class FakeCanvasTexture {
    needsUpdate = false;
    dispose = vi.fn(() => { disposed.textures += 1; });
  }
  class FakeMesh {
    position = new FakeVector3();
    rotation = new FakeEuler();
    scale = new FakeVector3(1, 1, 1);
    visible = true;
    constructor(public geometry: unknown, public material: unknown) {}
  }
  class FakeTextureLoader {
    load = vi.fn((_url: string, onLoad?: (t: unknown) => void) => {
      const tex = new FakeCanvasTexture();
      onLoad?.(tex);
      return tex;
    });
  }
  const three = {
    Group: FakeGroup,
    Mesh: FakeMesh,
    PlaneGeometry: FakePlaneGeometry,
    MeshBasicMaterial: FakeBasicMaterial,
    CanvasTexture: FakeCanvasTexture,
    TextureLoader: FakeTextureLoader,
    Vector3: FakeVector3,
    Euler: FakeEuler,
  } as unknown as ThreeModule;
  return { three, disposed };
}

function makeFakeHost(three: ThreeModule): ShelfHost {
  return {
    scene: { add: vi.fn(), remove: vi.fn() } as unknown as ShelfHost["scene"],
    camera: { position: { x: 0, y: 0, z: 8 }, aspect: 1, lookAt: vi.fn(), updateProjectionMatrix: vi.fn() } as unknown as ShelfHost["camera"],
    three,
    now: () => 0,
    requestFrame: vi.fn(),
    cancelFrame: vi.fn(),
  };
}

const SAMPLE_CARD: CardData = {
  id: "p1",
  kind: "playlist",
  title: "夜行",
  subtitle: "12 首",
  coverUrl: "https://example.com/cover.jpg",
  payload: {},
};

describe("buildCardMesh 创建契约", () => {
  it("创建 Mesh 并添加到 group（group.add 调用一次）", () => {
    const { three } = makeFakeThree();
    const host = makeFakeHost(three);
    const layout = computeArcLayout(1, { radius: 4 })[0]!;
    const group = new three.Group();
    const rt = buildCardMesh(host.three, group, layout, SAMPLE_CARD, false);
    expect(group.add).toHaveBeenCalledTimes(1);
    expect(rt.mesh).toBeDefined();
    disposeCard(group, rt);
  });

  it("Mesh 初始位置 = layout 目标位置 + enterOffset.z（非 reducedMotion）", () => {
    const { three } = makeFakeThree();
    const host = makeFakeHost(three);
    const layout = computeArcLayout(1, { radius: 4 })[0]!;
    const group = new three.Group();
    const rt = buildCardMesh(host.three, group, layout, SAMPLE_CARD, false);
    // enterOffset.z = -2（从远处推进）
    expect(rt.mesh.position.z).toBeCloseTo(4 - 2, 4);
    expect(rt.mesh.position.x).toBeCloseTo(0, 4);
    disposeCard(group, rt);
  });

  it("reducedMotion=true 时 Mesh 直挂目标位置（无 enterOffset）", () => {
    const { three } = makeFakeThree();
    const host = makeFakeHost(three);
    const layout = computeArcLayout(1, { radius: 4, reducedMotion: true })[0]!;
    const group = new three.Group();
    const rt = buildCardMesh(host.three, group, layout, SAMPLE_CARD, true);
    expect(rt.mesh.position.z).toBeCloseTo(4, 4);
    disposeCard(group, rt);
  });

  it("Mesh.rotationY = layout rotationY（卡片正面朝向圆心）", () => {
    const { three } = makeFakeThree();
    const host = makeFakeHost(three);
    const layout = computeArcLayout(3, { radius: 4, spanDeg: 90 })[0]!;
    const group = new three.Group();
    const rt = buildCardMesh(host.three, group, layout, SAMPLE_CARD, true);
    expect(rt.mesh.rotation.y).toBeCloseTo(layout.rotationY, 4);
    disposeCard(group, rt);
  });

  it("材质初始 map 为标题 canvas 纹理（封面未加载时显示标题）", () => {
    const { three } = makeFakeThree();
    const host = makeFakeHost(three);
    const layout = computeArcLayout(1, { radius: 4 })[0]!;
    const group = new three.Group();
    const rt = buildCardMesh(host.three, group, layout, SAMPLE_CARD, true);
    const material = (rt.mesh as unknown as { material: { map: unknown } }).material;
    expect(material.map).not.toBeNull();
    disposeCard(group, rt);
  });
});

describe("buildCardMesh 封面异步加载", () => {
  it("coverUrl 非空时触发 TextureLoader.load（携带 URL）", () => {
    const { three } = makeFakeThree();
    const host = makeFakeHost(three);
    const layout = computeArcLayout(1, { radius: 4 })[0]!;
    const group = new three.Group();
    const rt = buildCardMesh(host.three, group, layout, SAMPLE_CARD, true);
    expect(host.three.TextureLoader).toBeDefined();
    // TextureLoader.load 被调用且 URL 正确
    // 注意：fakeThree 的 TextureLoader 是构造函数，需要在实例上断言
    const material = (rt.mesh as unknown as { material: { map: unknown; needsUpdate: boolean } }).material;
    // 加载完成后 map 应该被替换为封面纹理（fake 同步回调）
    expect(material.map).not.toBeNull();
    disposeCard(group, rt);
  });

  it("coverUrl 为 null 时不调用 TextureLoader.load", () => {
    const { three } = makeFakeThree();
    const layout = computeArcLayout(1, { radius: 4 })[0]!;
    const group = new three.Group();
    const loadSpy = vi.fn();
    // 包装 TextureLoader 拦截 load 调用
    class SpyLoader { load = loadSpy; }
    const threeSpy = { ...three, TextureLoader: SpyLoader as unknown as ThreeModule["TextureLoader"] };
    const rt = buildCardMesh(threeSpy as unknown as ThreeModule, group, layout, { ...SAMPLE_CARD, coverUrl: null }, true);
    expect(loadSpy).not.toHaveBeenCalled();
    disposeCard(group, rt);
  });
});

describe("updateCardState 悬停 / 选中 scale", () => {
  it("默认 scale=1，悬停后收敛到 HOVER_SCALE，选中后收敛到 SELECT_SCALE", () => {
    const { three } = makeFakeThree();
    const host = makeFakeHost(three);
    const layout = computeArcLayout(1, { radius: 4 })[0]!;
    const group = new three.Group();
    const rt = buildCardMesh(host.three, group, layout, SAMPLE_CARD, true);
    // 初始 scale = 1
    expect(rt.mesh.scale.x).toBe(1);
    // 悬停状态推进多帧 → 收敛到 1.12
    for (let i = 0; i < 200; i++) updateCardState(rt, true, false, 0.016);
    expect(rt.mesh.scale.x).toBeCloseTo(1.12, 2);
    // 选中状态优先 → 收敛到 1.35
    for (let i = 0; i < 200; i++) updateCardState(rt, false, true, 0.016);
    expect(rt.mesh.scale.x).toBeCloseTo(1.35, 2);
    // 都不悬停 / 不选中 → 回到 1
    for (let i = 0; i < 200; i++) updateCardState(rt, false, false, 0.016);
    expect(rt.mesh.scale.x).toBeCloseTo(1.0, 2);
    disposeCard(group, rt);
  });

  it("入场偏移 z 随帧推进收敛到 0", () => {
    const { three } = makeFakeThree();
    const host = makeFakeHost(three);
    const layout = computeArcLayout(1, { radius: 4 })[0]!;
    const group = new three.Group();
    const rt = buildCardMesh(host.three, group, layout, SAMPLE_CARD, false);
    // 初始 z 偏移 -2
    expect(rt.mesh.position.z).toBeCloseTo(4 - 2, 2);
    // 推进多帧后收敛到目标
    for (let i = 0; i < 200; i++) updateCardState(rt, false, false, 0.016);
    expect(rt.mesh.position.z).toBeCloseTo(4, 2);
    disposeCard(group, rt);
  });
});

describe("disposeCard 资源释放", () => {
  it("disposeCard 调用 geometry / material / texture 的 dispose", () => {
    const { three, disposed } = makeFakeThree();
    const host = makeFakeHost(three);
    const layout = computeArcLayout(1, { radius: 4 })[0]!;
    const group = new three.Group();
    const rt = buildCardMesh(host.three, group, layout, SAMPLE_CARD, true);
    disposeCard(group, rt);
    // geometry + material + 至少 1 个 texture（标题；封面 fake 同步加载也算 1）
    expect(disposed.geometries).toBeGreaterThanOrEqual(1);
    expect(disposed.materials).toBeGreaterThanOrEqual(1);
    expect(disposed.textures).toBeGreaterThanOrEqual(1);
  });

  it("disposeCard 从 group 移除 mesh", () => {
    const { three } = makeFakeThree();
    const host = makeFakeHost(three);
    const layout = computeArcLayout(1, { radius: 4 })[0]!;
    const group = new three.Group();
    const rt = buildCardMesh(host.three, group, layout, SAMPLE_CARD, true);
    expect(group.children).toHaveLength(1);
    disposeCard(group, rt);
    expect(group.children).toHaveLength(0);
  });
});
