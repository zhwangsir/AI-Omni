/**
 * ImmersiveSpace 组件测试（M5.1 TDD 红）：
 * - 懒加载 three/createSpace（动态 import，首屏 bundle 不含 three）
 * - WebGL 可用时挂载 3D 画布；失败时回退 M4 的 2D ParticleField
 * - 主题切换转发 applyTheme；卸载时 dispose
 * 全部 mock：three 与 createSpace 模块都经 vi.mock 替换，不碰真实 WebGL。
 */
import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { getTheme } from "../theme/themes";

// ---- fake createSpace 模块（动态 import 被 vi.mock 拦截） ----
const disposeMock = vi.fn();
const applyThemeMock = vi.fn();
const setReducedMotionMock = vi.fn();
const createSpaceMock = vi.fn((..._args: unknown[]) => ({
  dispose: disposeMock,
  applyTheme: applyThemeMock,
  setReducedMotion: setReducedMotionMock,
}));

vi.mock("../space/createSpace", () => ({
  createSpace: (...args: unknown[]) => createSpaceMock(...args),
  PLACEHOLDER_POINT_COUNT: 50,
}));

// three 运行时装配也是懒加载依赖，测试里替换为空壳——组件不真正实例化 WebGL
vi.mock("../space/runtime", () => ({
  loadSpaceRuntime: () => ({ three: {}, postfx: undefined }),
}));

import { ImmersiveSpace } from "./ImmersiveSpace";

beforeEach(() => {
  disposeMock.mockClear();
  applyThemeMock.mockClear();
  setReducedMotionMock.mockClear();
  createSpaceMock.mockClear();
});

describe("ImmersiveSpace 懒加载与挂载", () => {
  it("渲染挂载容器（data-testid=immersive-space），初始无画布（懒加载异步完成）", async () => {
    render(<ImmersiveSpace theme={getTheme("developer-amber")} />);
    const host = screen.getByTestId("immersive-space");
    expect(host).toBeInTheDocument();
    await waitFor(() => expect(createSpaceMock).toHaveBeenCalledTimes(1));
  });

  it("懒加载完成后调用 createSpace，并传入主题与 reducedMotion", async () => {
    render(<ImmersiveSpace theme={getTheme("silver-gray")} reducedMotion />);
    await waitFor(() => expect(createSpaceMock).toHaveBeenCalledTimes(1));
    const opts = createSpaceMock.mock.calls[0]![2] as unknown as { reducedMotion?: boolean };
    expect(opts.reducedMotion).toBe(true);
  });

  it("挂载容器不拦截指针（pointer-events: none），aria-hidden", async () => {
    render(<ImmersiveSpace theme={getTheme("developer-amber")} />);
    const host = screen.getByTestId("immersive-space");
    expect(host.style.pointerEvents).toBe("none");
    expect(host).toHaveAttribute("aria-hidden", "true");
    await waitFor(() => expect(createSpaceMock).toHaveBeenCalled());
  });
});

describe("ImmersiveSpace 主题与卸载", () => {
  it("主题 prop 变化时转发 applyTheme", async () => {
    const { rerender } = render(<ImmersiveSpace theme={getTheme("developer-amber")} />);
    await waitFor(() => expect(createSpaceMock).toHaveBeenCalledTimes(1));
    rerender(<ImmersiveSpace theme={getTheme("safelight-red")} />);
    await waitFor(() =>
      expect(applyThemeMock).toHaveBeenCalledWith(getTheme("safelight-red")),
    );
  });

  it("reducedMotion 变化时转发 setReducedMotion", async () => {
    const { rerender } = render(<ImmersiveSpace theme={getTheme("developer-amber")} />);
    await waitFor(() => expect(createSpaceMock).toHaveBeenCalledTimes(1));
    rerender(<ImmersiveSpace theme={getTheme("developer-amber")} reducedMotion />);
    await waitFor(() => expect(setReducedMotionMock).toHaveBeenCalledWith(true));
  });

  it("卸载时调用 dispose", async () => {
    const { unmount } = render(<ImmersiveSpace theme={getTheme("developer-amber")} />);
    await waitFor(() => expect(createSpaceMock).toHaveBeenCalledTimes(1));
    unmount();
    expect(disposeMock).toHaveBeenCalledTimes(1);
  });
});

describe("ImmersiveSpace spaceRef 句柄透出（M5.3）", () => {
  it("懒加载完成后 spaceRef.current 指向场景实例", async () => {
    const spaceRef: { current: unknown } = { current: null };
    render(
      <ImmersiveSpace
        theme={getTheme("developer-amber")}
        spaceRef={spaceRef as never}
      />,
    );
    await waitFor(() => expect(spaceRef.current).not.toBeNull());
    expect((spaceRef.current as { applyTheme?: unknown }).applyTheme).toBe(applyThemeMock);
  });

  it("卸载时 spaceRef.current 置 null（杜绝悬挂引用）", async () => {
    const spaceRef: { current: unknown } = { current: null };
    const { unmount } = render(
      <ImmersiveSpace theme={getTheme("developer-amber")} spaceRef={spaceRef as never} />,
    );
    await waitFor(() => expect(spaceRef.current).not.toBeNull());
    unmount();
    expect(spaceRef.current).toBeNull();
  });

  it("未传 spaceRef 时挂载 / 卸载不报错", async () => {
    const { unmount } = render(<ImmersiveSpace theme={getTheme("developer-amber")} />);
    await waitFor(() => expect(createSpaceMock).toHaveBeenCalledTimes(1));
    expect(() => unmount()).not.toThrow();
  });
});

describe("ImmersiveSpace WebGL 失败降级", () => {
  it("createSpace 抛错（WebGL 不可用）时回退 2D ParticleField 画布", async () => {
    createSpaceMock.mockImplementationOnce(() => {
      throw new Error("WebGL context creation failed");
    });
    render(<ImmersiveSpace theme={getTheme("developer-amber")} />);
    await waitFor(() => {
      expect(document.querySelector("canvas.particle-field")).not.toBeNull();
    });
    // 降级后 3D 容器不再渲染
    expect(screen.queryByTestId("immersive-space")).toBeNull();
  });

  it("降级路径不抛出未捕获异常（组件保持渲染）", async () => {
    createSpaceMock.mockImplementationOnce(() => {
      throw new Error("no webgl");
    });
    await act(async () => {
      render(<ImmersiveSpace theme={getTheme("developer-amber")} />);
    });
    await waitFor(() => {
      expect(document.querySelector("canvas.particle-field")).not.toBeNull();
    });
  });
});
