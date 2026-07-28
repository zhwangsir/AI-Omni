/**
 * DecryptDialog 组件测试（M19 TDD，D19.1 合规）。
 *
 * 覆盖：
 * - 初始渲染 / 合规警告条
 * - 路径输入 / 输出路径输入
 * - 确认安全门（未勾选时按钮禁用）
 * - 解密按钮调 store.decryptFile(path, output, confirm=true)
 * - 成功状态显示结果
 * - 错误状态显示错误信息
 * - 关闭按钮调 store.clearError + onClose
 * - isLoading 时按钮禁用
 * - 无 emoji / Icon svg
 */
import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  DecryptResult,
  LibraryStore,
  LibraryStoreState,
} from "../../store/libraryStore";
import { EMPTY_LIBRARY_STATE } from "../../store/libraryStore";
import { DecryptDialog } from "./DecryptDialog";

// ---------------------------------------------------------------------------
// fake 数据
// ---------------------------------------------------------------------------

function makeDecryptResult(overrides: Partial<DecryptResult> = {}): DecryptResult {
  return {
    output_path: "/music/a.decrypted.mp3",
    source_path: "/music/a.qmc0",
    compliance: "D19.1: 仅用于已合法购买内容的格式转换",
    notice: "请确保你已合法购买该音频内容",
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// fake store
// ---------------------------------------------------------------------------

function makeFakeStore(initialState: Partial<LibraryStoreState> = {}): {
  store: LibraryStore;
  actions: Record<string, ReturnType<typeof vi.fn>>;
  setState: (patch: Partial<LibraryStoreState>) => void;
} {
  let state: LibraryStoreState = { ...EMPTY_LIBRARY_STATE, ...initialState };
  const listeners = new Set<() => void>();
  const actions = {
    scanLibrary: vi.fn(async () => null),
    searchLibrary: vi.fn(async () => null),
    fetchStatus: vi.fn(async () => {}),
    fetchPlaylists: vi.fn(async () => {}),
    fetchPlaylistSongs: vi.fn(async () => {}),
    selectPlaylist: vi.fn(async () => {}),
    createPlaylist: vi.fn(async () => null),
    addToPlaylist: vi.fn(async () => false),
    removeFromPlaylist: vi.fn(async () => false),
    decryptFile: vi.fn(async () => makeDecryptResult() as DecryptResult | null),
    setSearchQuery: vi.fn(),
    clearError: vi.fn(),
  };
  const store = {
    getState: () => state,
    subscribe: (l: () => void) => {
      listeners.add(l);
      return () => {
        listeners.delete(l);
      };
    },
    ...actions,
  } as unknown as LibraryStore;
  const setState = (patch: Partial<LibraryStoreState>): void => {
    state = { ...state, ...patch };
    for (const l of listeners) l();
  };
  return { store, actions, setState };
}

// ---------------------------------------------------------------------------
// 初始渲染
// ---------------------------------------------------------------------------

describe("DecryptDialog 初始渲染", () => {
  it("渲染弹窗根容器", () => {
    const { store } = makeFakeStore();
    render(<DecryptDialog store={store} onClose={vi.fn()} />);
    expect(screen.getByTestId("decrypt-dialog")).toBeTruthy();
    expect(screen.getByTestId("decrypt-dialog").getAttribute("data-state")).toBe("idle");
  });

  it("显示 D19.1 合规警告条", () => {
    const { store } = makeFakeStore();
    render(<DecryptDialog store={store} onClose={vi.fn()} />);
    const notice = screen.getByTestId("decrypt-compliance-notice");
    expect(notice.textContent).toContain("D19.1");
    expect(notice.textContent).toContain("合法购买");
  });

  it("渲染路径输入框与输出路径输入框", () => {
    const { store } = makeFakeStore();
    render(<DecryptDialog store={store} onClose={vi.fn()} />);
    expect(screen.getByTestId("decrypt-path-input")).toBeTruthy();
    expect(screen.getByTestId("decrypt-output-input")).toBeTruthy();
  });

  it("渲染确认安全门 checkbox（默认未勾选）", () => {
    const { store } = makeFakeStore();
    render(<DecryptDialog store={store} onClose={vi.fn()} />);
    const cb = screen.getByTestId("decrypt-confirm-checkbox") as HTMLInputElement;
    expect(cb.checked).toBe(false);
  });

  it("渲染 svg 图标", () => {
    const { store } = makeFakeStore();
    const { container } = render(<DecryptDialog store={store} onClose={vi.fn()} />);
    expect(container.querySelector("svg")).not.toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 安全门 / 按钮禁用逻辑
// ---------------------------------------------------------------------------

describe("DecryptDialog 安全门", () => {
  it("未输入路径 + 未确认时按钮禁用", () => {
    const { store } = makeFakeStore();
    render(<DecryptDialog store={store} onClose={vi.fn()} />);
    const btn = screen.getByTestId("decrypt-submit-btn") as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it("输入路径但未确认时按钮禁用", () => {
    const { store } = makeFakeStore();
    render(<DecryptDialog store={store} onClose={vi.fn()} />);
    act(() => {
      fireEvent.change(screen.getByTestId("decrypt-path-input"), {
        target: { value: "/music/a.qmc0" },
      });
    });
    const btn = screen.getByTestId("decrypt-submit-btn") as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it("确认但未输入路径时按钮禁用", () => {
    const { store } = makeFakeStore();
    render(<DecryptDialog store={store} onClose={vi.fn()} />);
    act(() => {
      fireEvent.click(screen.getByTestId("decrypt-confirm-checkbox"));
    });
    const btn = screen.getByTestId("decrypt-submit-btn") as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it("输入路径 + 勾选确认后按钮启用", () => {
    const { store } = makeFakeStore();
    render(<DecryptDialog store={store} onClose={vi.fn()} />);
    act(() => {
      fireEvent.change(screen.getByTestId("decrypt-path-input"), {
        target: { value: "/music/a.qmc0" },
      });
      fireEvent.click(screen.getByTestId("decrypt-confirm-checkbox"));
    });
    const btn = screen.getByTestId("decrypt-submit-btn") as HTMLButtonElement;
    expect(btn.disabled).toBe(false);
  });

  it("isLoading=true 时按钮禁用（即使路径+确认都满足）", () => {
    const { store } = makeFakeStore({ isLoading: true });
    render(<DecryptDialog store={store} onClose={vi.fn()} />);
    act(() => {
      fireEvent.change(screen.getByTestId("decrypt-path-input"), {
        target: { value: "/music/a.qmc0" },
      });
      fireEvent.click(screen.getByTestId("decrypt-confirm-checkbox"));
    });
    const btn = screen.getByTestId("decrypt-submit-btn") as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// 解密调用
// ---------------------------------------------------------------------------

describe("DecryptDialog 解密调用", () => {
  it("点击解密按钮调 store.decryptFile(path, output, true)", async () => {
    const { store, actions } = makeFakeStore();
    render(<DecryptDialog store={store} onClose={vi.fn()} />);
    act(() => {
      fireEvent.change(screen.getByTestId("decrypt-path-input"), {
        target: { value: "/music/a.qmc0" },
      });
      fireEvent.change(screen.getByTestId("decrypt-output-input"), {
        target: { value: "/custom/out.mp3" },
      });
      fireEvent.click(screen.getByTestId("decrypt-confirm-checkbox"));
    });
    await act(async () => {
      screen.getByTestId("decrypt-submit-btn").click();
      await vi.waitFor(() => expect(actions.decryptFile).toHaveBeenCalled());
    });
    expect(actions.decryptFile).toHaveBeenCalledWith("/music/a.qmc0", "/custom/out.mp3", true);
  });

  it("输出路径为空时传 undefined（使用后端默认）", async () => {
    const { store, actions } = makeFakeStore();
    render(<DecryptDialog store={store} onClose={vi.fn()} />);
    act(() => {
      fireEvent.change(screen.getByTestId("decrypt-path-input"), {
        target: { value: "/music/a.qmc0" },
      });
      fireEvent.click(screen.getByTestId("decrypt-confirm-checkbox"));
    });
    await act(async () => {
      screen.getByTestId("decrypt-submit-btn").click();
      await vi.waitFor(() => expect(actions.decryptFile).toHaveBeenCalled());
    });
    expect(actions.decryptFile).toHaveBeenCalledWith("/music/a.qmc0", undefined, true);
  });

  it("确认安全门始终传 confirm=true（store 侧不绕过 D19.1）", async () => {
    const { store, actions } = makeFakeStore();
    render(<DecryptDialog store={store} onClose={vi.fn()} />);
    act(() => {
      fireEvent.change(screen.getByTestId("decrypt-path-input"), {
        target: { value: "/x.qmc0" },
      });
      fireEvent.click(screen.getByTestId("decrypt-confirm-checkbox"));
    });
    await act(async () => {
      screen.getByTestId("decrypt-submit-btn").click();
      await vi.waitFor(() => expect(actions.decryptFile).toHaveBeenCalled());
    });
    // 第三个参数（confirm）必须为 true
    const call = actions.decryptFile.mock.calls[0];
    expect(call?.[2]).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// 成功 / 错误状态
// ---------------------------------------------------------------------------

describe("DecryptDialog 成功状态", () => {
  it("lastDecryptResult 存在时显示成功面板（data-state=success）", () => {
    const { store } = makeFakeStore({
      lastDecryptResult: makeDecryptResult({
        source_path: "/music/a.qmc0",
        output_path: "/music/a.decrypted.mp3",
      }),
    });
    render(<DecryptDialog store={store} onClose={vi.fn()} />);
    expect(screen.getByTestId("decrypt-dialog").getAttribute("data-state")).toBe("success");
    expect(screen.getByTestId("decrypt-success")).toBeTruthy();
    expect(screen.getByTestId("decrypt-success").textContent).toContain("/music/a.qmc0");
    expect(screen.getByTestId("decrypt-success").textContent).toContain("/music/a.decrypted.mp3");
  });

  it("成功面板显示合规声明文案", () => {
    const { store } = makeFakeStore({
      lastDecryptResult: makeDecryptResult({
        notice: "请确保你已合法购买该音频内容",
      }),
    });
    render(<DecryptDialog store={store} onClose={vi.fn()} />);
    expect(screen.getByTestId("decrypt-success").textContent).toContain("合法购买");
  });
});

describe("DecryptDialog 错误状态", () => {
  it("error 非 null 时显示错误条（data-state=error）", () => {
    const { store } = makeFakeStore({ error: "缺密钥" });
    render(<DecryptDialog store={store} onClose={vi.fn()} />);
    expect(screen.getByTestId("decrypt-dialog").getAttribute("data-state")).toBe("error");
    expect(screen.getByTestId("decrypt-error").textContent).toContain("缺密钥");
  });

  it("error 为 null 时不显示错误条", () => {
    const { store } = makeFakeStore({ error: null });
    render(<DecryptDialog store={store} onClose={vi.fn()} />);
    expect(screen.queryByTestId("decrypt-error")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// 关闭
// ---------------------------------------------------------------------------

describe("DecryptDialog 关闭", () => {
  it("点击关闭按钮调 clearError + onClose", () => {
    const onClose = vi.fn();
    const { store, actions } = makeFakeStore({ error: "err" });
    render(<DecryptDialog store={store} onClose={onClose} />);
    act(() => screen.getByTestId("decrypt-close").click());
    expect(actions.clearError).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("点击遮罩区域调 clearError + onClose", () => {
    const onClose = vi.fn();
    const { store, actions } = makeFakeStore();
    render(<DecryptDialog store={store} onClose={onClose} />);
    act(() => screen.getByTestId("decrypt-dialog").click());
    expect(actions.clearError).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("点击卡片内部不关闭（stopPropagation）", () => {
    const onClose = vi.fn();
    const { store, actions } = makeFakeStore();
    render(<DecryptDialog store={store} onClose={onClose} />);
    act(() => screen.getByTestId("decrypt-dialog-card").click());
    expect(actions.clearError).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// 风格约束
// ---------------------------------------------------------------------------

describe("DecryptDialog 风格约束", () => {
  it("不含 emoji", () => {
    const { store } = makeFakeStore();
    const { container } = render(<DecryptDialog store={store} onClose={vi.fn()} />);
    expect(container.textContent ?? "").not.toMatch(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u);
  });
});
