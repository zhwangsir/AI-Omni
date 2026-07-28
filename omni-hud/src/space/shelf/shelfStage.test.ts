/**
 * shelf/shelfStage 卡片架场景装配（M20.1 TDD 红）：
 * - 接收 ShelfHost（scene + camera + three 模块 + 时序注入），创建 Group 挂到 scene；
 * - setCards 替换卡片数据（旧卡片 dispose，新卡片按 layout 排布）；
 * - 帧循环驱动卡片动画推进（stagger 入场 / 悬停放大 / 选中居中）；
 * - dispose 幂等：从 scene 移除 Group，释放所有 geometry/material/texture；
 * - reducedMotion 静态降级：卡片直挂目标位置，无入场偏移动画。
 *
 * 全 fake three 模块：不创建真实 WebGL 上下文，断言 scene.add / remove 调用次数。
 */
import { describe, expect, it, vi } from "vitest";

import type { CardData } from "./dataSource";
import { createShelfStage, type ShelfHost } from "./shelfStage";
import type { ThreeModule } from "../createSpace";

/** fake three 模块：捕获 Group / Mesh / Material / Texture / Geometry 创建与 dispose。 */
function makeFakeThree() {
  const created = {
    groups: [] as FakeGroup[],
    meshes: [] as FakeMesh[],
    planeGeometries: [] as FakePlaneGeometry[],
    shaderMaterials: [] as FakeShaderMaterial[],
    canvasTextures: [] as FakeCanvasTexture[],
    basicMaterials: [] as FakeBasicMaterial[],
  };

  class FakeVector3 {
    constructor(public x = 0, public y = 0, public z = 0) {}
    set(x: number, y: number, z: number) {
      this.x = x; this.y = y; this.z = z;
      return this;
    }
    copy(v: { x: number; y: number; z: number }) {
      this.x = v.x; this.y = v.y; this.z = v.z;
      return this;
    }
  }
  class FakeEuler {
    constructor(public x = 0, public y = 0, public z = 0) {}
    set(x: number, y: number, z: number) {
      this.x = x; this.y = y; this.z = z;
      return this;
    }
  }
  class FakeGroup {
    position = new FakeVector3();
    rotation = new FakeEuler();
    children: unknown[] = [];
    addedTo: unknown = null;
    add = vi.fn((obj: unknown) => { this.children.push(obj); });
    remove = vi.fn((obj: unknown) => {
      const i = this.children.indexOf(obj);
      if (i >= 0) this.children.splice(i, 1);
    });
  }
  class FakePlaneGeometry {
    dispose = vi.fn();
  }
  class FakeShaderMaterial {
    uniforms: Record<string, { value: unknown }>;
    dispose = vi.fn();
    constructor(opts: { uniforms: Record<string, { value: unknown }> }) {
      this.uniforms = opts.uniforms;
    }
  }
  class FakeBasicMaterial {
    dispose = vi.fn();
    constructor(public opts: unknown) {}
  }
  class FakeCanvasTexture {
    needsUpdate = false;
    dispose = vi.fn();
  }
  class FakeMesh {
    position = new FakeVector3();
    rotation = new FakeEuler();
    scale = new FakeVector3(1, 1, 1);
    geometry: FakePlaneGeometry;
    material: FakeShaderMaterial | FakeBasicMaterial;
    constructor(geometry: FakePlaneGeometry, material: FakeShaderMaterial | FakeBasicMaterial) {
      this.geometry = geometry;
      this.material = material;
    }
  }
  class FakeTextureLoader {
    load = vi.fn((_url: string, onLoad?: (t: unknown) => void) => {
      // 同步回调 fake texture
      const tex = new FakeCanvasTexture();
      onLoad?.(tex);
      return tex;
    });
  }

  const three = {
    Group: FakeGroup,
    Mesh: FakeMesh,
    PlaneGeometry: FakePlaneGeometry,
    ShaderMaterial: FakeShaderMaterial,
    MeshBasicMaterial: FakeBasicMaterial,
    CanvasTexture: FakeCanvasTexture,
    TextureLoader: FakeTextureLoader,
    Vector3: FakeVector3,
    Euler: FakeEuler,
  } as unknown as ThreeModule;

  return { three, created, classes: { FakeGroup, FakeMesh, FakePlaneGeometry, FakeShaderMaterial } };
}

function makeFakeHost(three: ThreeModule): ShelfHost {
  const sceneState = {
    add: vi.fn(),
    remove: vi.fn(),
  };
  const cameraState = {
    position: { x: 0, y: 0, z: 8 },
    aspect: 1,
    lookAt: vi.fn(),
    updateProjectionMatrix: vi.fn(),
  };
  return {
    scene: sceneState as unknown as ShelfHost["scene"],
    camera: cameraState as unknown as ShelfHost["camera"],
    three,
    now: () => 0,
    requestFrame: vi.fn((_cb: FrameRequestCallback) => {
      // 测试中不自动循环；调用方手动驱动 step
      return 0;
    }),
    cancelFrame: vi.fn(),
  } as ShelfHost;
}

const SAMPLE_CARDS: CardData[] = [
  { id: "c1", kind: "playlist", title: "夜行", subtitle: "12 首", coverUrl: null, payload: {} },
  { id: "c2", kind: "playlist", title: "晨光", subtitle: "8 首", coverUrl: null, payload: {} },
  { id: "c3", kind: "playlist", title: "雨夜", subtitle: "15 首", coverUrl: null, payload: {} },
];

describe("ShelfStage 生命周期", () => {
  it("创建时 Group 挂到 scene（add 调用一次）", () => {
    const { three } = makeFakeThree();
    const host = makeFakeHost(three);
    const stage = createShelfStage(host, { reducedMotion: true });
    expect(host.scene.add).toHaveBeenCalledTimes(1);
    stage.dispose();
  });

  it("dispose 幂等：多次调用不抛错、scene.remove 仅触发一次", () => {
    const { three } = makeFakeThree();
    const host = makeFakeHost(three);
    const stage = createShelfStage(host, { reducedMotion: true });
    stage.dispose();
    expect(host.scene.remove).toHaveBeenCalledTimes(1);
    stage.dispose();
    stage.dispose();
    expect(host.scene.remove).toHaveBeenCalledTimes(1);
  });

  it("dispose 后 setCards 静默跳过（不抛错）", () => {
    const { three } = makeFakeThree();
    const host = makeFakeHost(three);
    const stage = createShelfStage(host, { reducedMotion: true });
    stage.dispose();
    expect(() => stage.setCards(SAMPLE_CARDS)).not.toThrow();
  });
});

describe("ShelfStage setCards", () => {
  it("setCards 创建对应数量的 Mesh（每张卡片一个 Mesh）", () => {
    const { three } = makeFakeThree();
    const host = makeFakeHost(three);
    const stage = createShelfStage(host, { reducedMotion: true });
    stage.setCards(SAMPLE_CARDS);
    // Group.children 应有 3 个 Mesh
    const group = (host.scene.add as ReturnType<typeof vi.fn>).mock.calls[0]![0] as {
      children: unknown[];
    };
    expect(group.children).toHaveLength(3);
    stage.dispose();
  });

  it("setCards 替换旧卡片（不累积）", () => {
    const { three } = makeFakeThree();
    const host = makeFakeHost(three);
    const stage = createShelfStage(host, { reducedMotion: true });
    stage.setCards(SAMPLE_CARDS);
    stage.setCards(SAMPLE_CARDS.slice(0, 2));
    const group = (host.scene.add as ReturnType<typeof vi.fn>).mock.calls[0]![0] as {
      children: unknown[];
    };
    expect(group.children).toHaveLength(2);
    stage.dispose();
  });

  it("setCards 空数组清空所有卡片", () => {
    const { three } = makeFakeThree();
    const host = makeFakeHost(three);
    const stage = createShelfStage(host, { reducedMotion: true });
    stage.setCards(SAMPLE_CARDS);
    stage.setCards([]);
    const group = (host.scene.add as ReturnType<typeof vi.fn>).mock.calls[0]![0] as {
      children: unknown[];
    };
    expect(group.children).toHaveLength(0);
    stage.dispose();
  });

  it("reducedMotion 卡片直挂目标位置（无入场偏移）", () => {
    const { three } = makeFakeThree();
    const host = makeFakeHost(three);
    const stage = createShelfStage(host, { reducedMotion: true });
    stage.setCards(SAMPLE_CARDS);
    const group = (host.scene.add as ReturnType<typeof vi.fn>).mock.calls[0]![0] as {
      children: { position: { z: number } }[];
    };
    // 中间卡片（index 1）应在 z = radius（=4）处，无偏移
    expect(group.children[1]!.position.z).toBeCloseTo(4, 5);
    stage.dispose();
  });
});

describe("ShelfStage 选中回调", () => {
  it("select(index) 触发 onSelect 回调（携带卡片数据）", () => {
    const { three } = makeFakeThree();
    const host = makeFakeHost(three);
    const onSelect = vi.fn();
    const stage = createShelfStage(host, { reducedMotion: true, onSelect });
    stage.setCards(SAMPLE_CARDS);
    stage.select(1);
    expect(onSelect).toHaveBeenCalledWith(SAMPLE_CARDS[1]);
    stage.dispose();
  });

  it("select 越界静默跳过（不抛错、不触发回调）", () => {
    const { three } = makeFakeThree();
    const host = makeFakeHost(three);
    const onSelect = vi.fn();
    const stage = createShelfStage(host, { reducedMotion: true, onSelect });
    stage.setCards(SAMPLE_CARDS);
    expect(() => stage.select(99)).not.toThrow();
    expect(onSelect).not.toHaveBeenCalled();
    stage.dispose();
  });
});

describe("ShelfStage step 动画推进", () => {
  it("step 推进入场动画（卡片 z 从偏移位置收敛到目标位置）", () => {
    const { three } = makeFakeThree();
    const host = makeFakeHost(three);
    let now = 0;
    (host as { now: () => number }).now = () => now;
    const stage = createShelfStage(host, { reducedMotion: false });
    stage.setCards(SAMPLE_CARDS);
    const group = (host.scene.add as ReturnType<typeof vi.fn>).mock.calls[0]![0] as {
      children: { position: { z: number } }[];
    };
    // 初始 z 应在目标 z + enterOffset.z（-2，即从远处推进）
    const targetZ = 4;
    const initialZ = group.children[1]!.position.z;
    expect(initialZ).toBeCloseTo(targetZ - 2, 2);
    // 推进若干帧后收敛到目标（spring 收敛率 4.0/s，~1.5s 内 99% 收敛）
    for (let i = 0; i < 200; i++) {
      now = i * 16;
      stage.step(now);
    }
    expect(group.children[1]!.position.z).toBeCloseTo(targetZ, 2);
    stage.dispose();
  });
});
