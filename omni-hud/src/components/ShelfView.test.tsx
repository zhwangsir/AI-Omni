/**
 * ShelfView 组件测试（M20.6）：
 * - fieldMode="space" 时不挂载 ShelfStage（不调 getShelfHost）；
 * - fieldMode="shelf" 时获取 ShelfHost 并创建 ShelfStage，注入卡片数据；
 * - fieldMode 切回 "space" 时 dispose ShelfStage（幂等）；
 * - 右键 contextmenu 事件触发 toggleFieldMode；
 * - 空间未就绪（spaceRef.current=null 或 getShelfHost 返回 null）时静默跳过不抛错。
 *
 * 全 fake 后端：注入 mock Space / mock libraryStore / fake ShelfHost，
 * 不创建真实 WebGL 上下文（jsdom 无 GPU）。
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { act, cleanup, fireEvent, render } from "@testing-library/react";
import type { MutableRefObject } from "react";

import { ShelfView } from "./ShelfView";
import { createHudStore } from "../store/hudStore";
import type { Space } from "../space/createSpace";
import type { LibraryStore, Playlist } from "../store/libraryStore";

/** 构造 mock Space：getShelfHost 返回 null（未就绪）或 fake host。 */
function makeMockSpace(shelfHost: unknown | null = null): {
  space: Space;
  getShelfHost: ReturnType<typeof vi.fn>;
  setMood: ReturnType<typeof vi.fn>;
} {
  const getShelfHost = vi.fn(() => shelfHost);
  const setMood = vi.fn();
  const space = {
    getShelfHost,
    setMood,
  } as unknown as Space;
  return { space, getShelfHost, setMood };
}

/** 构造 mock libraryStore：返回固定 playlists。 */
function makeMockLibraryStore(playlists: Playlist[] = []): LibraryStore {
  let state = { playlists } as { playlists: Playlist[] };
  const listeners = new Set<() => void>();
  return {
    getState: () => state as never,
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    fetchPlaylists: vi.fn(async () => {
      state = { playlists };
      for (const l of listeners) l();
    }),
  } as unknown as LibraryStore;
}

/** fake ShelfHost：足够 ShelfStage 构造（Group/Scene/Mesh 等）。 */
function makeFakeShelfHost(): {
  host: unknown;
  sceneAdd: ReturnType<typeof vi.fn>;
  sceneRemove: ReturnType<typeof vi.fn>;
  groupAdd: ReturnType<typeof vi.fn>;
  groupRemove: ReturnType<typeof vi.fn>;
} {
  const sceneAdd = vi.fn();
  const sceneRemove = vi.fn();
  const groupAdd = vi.fn();
  const groupRemove = vi.fn();
  const fakeThree = {
    Group: class {
      add = groupAdd;
      remove = groupRemove;
    },
    Scene: class {},
    Mesh: class {
      position = { set: vi.fn() };
      rotation = { set: vi.fn() };
      scale = { set: vi.fn() };
    },
    PlaneGeometry: class {
      dispose = vi.fn();
    },
    MeshBasicMaterial: class {
      dispose = vi.fn();
      map: unknown = null;
      needsUpdate = false;
    },
    CanvasTexture: class {
      dispose = vi.fn();
    },
    TextureLoader: class {
      load = vi.fn();
    },
  };
  const host = {
    scene: { add: sceneAdd, remove: sceneRemove },
    camera: { position: { x: 0, y: 0, z: 8 } },
    three: fakeThree,
    now: () => 0,
    requestFrame: (_cb: FrameRequestCallback) => {
      // 不自动泵帧；测试手动控制
      return 0;
    },
    cancelFrame: vi.fn(),
  };
  return { host, sceneAdd, sceneRemove, groupAdd, groupRemove };
}

describe("ShelfView 场景模式挂载（M20.6）", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("fieldMode='space' 时不调 getShelfHost（不挂载卡片架）", () => {
    const hudStore = createHudStore();
    const { space, getShelfHost } = makeMockSpace(null);
    const spaceRef: MutableRefObject<Space | null> = { current: space };
    const libraryStore = makeMockLibraryStore([]);

    render(
      <ShelfView
        spaceRef={spaceRef}
        hudStore={hudStore}
        libraryStore={libraryStore}
      />,
    );

    expect(getShelfHost).not.toHaveBeenCalled();
  });

  it("fieldMode='shelf' 时获取 ShelfHost 并创建 ShelfStage（scene.add 被调用）", () => {
    const hudStore = createHudStore();
    const { host, sceneAdd } = makeFakeShelfHost();
    const { space } = makeMockSpace(host);
    const spaceRef: MutableRefObject<Space | null> = { current: space };
    const playlists: Playlist[] = [
      { id: 1, name: "夜曲", created_at: 0, updated_at: 0, song_count: 5 },
    ];
    const libraryStore = makeMockLibraryStore(playlists);

    hudStore.setFieldMode("shelf");
    render(
      <ShelfView
        spaceRef={spaceRef}
        hudStore={hudStore}
        libraryStore={libraryStore}
      />,
    );

    expect(sceneAdd).toHaveBeenCalled(); // Group 加入 scene
  });

  it("fieldMode 从 shelf 切回 space 时 dispose ShelfStage（scene.remove 被调用）", () => {
    const hudStore = createHudStore();
    const { host, sceneRemove } = makeFakeShelfHost();
    const { space } = makeMockSpace(host);
    const spaceRef: MutableRefObject<Space | null> = { current: space };
    const libraryStore = makeMockLibraryStore([]);

    hudStore.setFieldMode("shelf");
    const { unmount } = render(
      <ShelfView
        spaceRef={spaceRef}
        hudStore={hudStore}
        libraryStore={libraryStore}
      />,
    );

    // 切回 space
    act(() => hudStore.setFieldMode("space"));
    expect(sceneRemove).toHaveBeenCalled();
    unmount();
  });

  it("空间未就绪（spaceRef.current=null）时静默跳过不抛错", () => {
    const hudStore = createHudStore();
    const spaceRef: MutableRefObject<Space | null> = { current: null };
    const libraryStore = makeMockLibraryStore([]);

    hudStore.setFieldMode("shelf");
    expect(() =>
      render(
        <ShelfView
          spaceRef={spaceRef}
          hudStore={hudStore}
          libraryStore={libraryStore}
        />,
      ),
    ).not.toThrow();
  });

  it("getShelfHost 返回 null（已 dispose）时静默跳过不抛错", () => {
    const hudStore = createHudStore();
    const { space } = makeMockSpace(null); // getShelfHost 返回 null
    const spaceRef: MutableRefObject<Space | null> = { current: space };
    const libraryStore = makeMockLibraryStore([]);

    hudStore.setFieldMode("shelf");
    expect(() =>
      render(
        <ShelfView
          spaceRef={spaceRef}
          hudStore={hudStore}
          libraryStore={libraryStore}
        />,
      ),
    ).not.toThrow();
  });

  it("右键 contextmenu 触发 toggleFieldMode（space → shelf）", () => {
    const hudStore = createHudStore();
    const { space } = makeMockSpace(null);
    const spaceRef: MutableRefObject<Space | null> = { current: space };
    const libraryStore = makeMockLibraryStore([]);

    const { getByTestId } = render(
      <ShelfView
        spaceRef={spaceRef}
        hudStore={hudStore}
        libraryStore={libraryStore}
      />,
    );

    const shelfView = getByTestId("shelf-view");

    // 右键触发 toggle
    act(() => {
      fireEvent.contextMenu(shelfView);
    });
    expect(hudStore.getState().fieldMode).toBe("shelf");

    // 再右键切回
    act(() => {
      fireEvent.contextMenu(shelfView);
    });
    expect(hudStore.getState().fieldMode).toBe("space");
  });

  it("libraryStore playlists 变化时 setCards 被调用（cardCount 更新）", () => {
    const hudStore = createHudStore();
    const { host } = makeFakeShelfHost();
    const { space } = makeMockSpace(host);
    const spaceRef: MutableRefObject<Space | null> = { current: space };
    const playlists: Playlist[] = [
      { id: 1, name: "歌单一", created_at: 0, updated_at: 0, song_count: 3 },
      { id: 2, name: "歌单二", created_at: 0, updated_at: 0, song_count: 7 },
    ];
    const libraryStore = makeMockLibraryStore(playlists);

    hudStore.setFieldMode("shelf");
    const { getByTestId } = render(
      <ShelfView
        spaceRef={spaceRef}
        hudStore={hudStore}
        libraryStore={libraryStore}
      />,
    );

    // data-testid="shelf-card-count" 显示当前卡片数
    const countEl = getByTestId("shelf-card-count");
    expect(countEl.textContent).toBe("2");
  });
});
