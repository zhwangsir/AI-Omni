/**
 * LoginQrDialog 组件测试（M17.10 TDD）。
 *
 * 覆盖：4 种 loginStatus 渲染对应文案 / 二维码图渲染 / 重新获取按钮（expired）/
 * 关闭按钮 / 点击遮罩关闭 / stopLoginPolling 调用 / 无 emoji / Icon svg。
 */
import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { LoginQr, LoginStatus, MusicState, MusicStore } from "../../store/musicStore";
import { LoginQrDialog } from "./LoginQrDialog";

const FAKE_QR: LoginQr = { key: "k1", qr_url: "http://example.com/qr.png", source: "netease" };

function makeFakeStore(opts: {
  loginQr?: LoginQr | null;
  loginStatus?: LoginStatus;
} = {}): {
  store: MusicStore;
  actions: Record<string, ReturnType<typeof vi.fn>>;
} {
  const state: MusicState = {
    playerState: null,
    isLoading: false,
    error: null,
    // 显式区分 undefined（用默认）与 null（无二维码）
    loginQr: opts.loginQr !== undefined ? opts.loginQr : FAKE_QR,
    loginStatus: opts.loginStatus ?? "waiting",
    onlineResults: null,
  };
  const listeners = new Set<() => void>();
  const actions = {
    fetchPlayerState: vi.fn(async () => {}),
    play: vi.fn(async () => {}),
    pause: vi.fn(async () => {}),
    resume: vi.fn(async () => {}),
    stop: vi.fn(async () => {}),
    next: vi.fn(async () => {}),
    previous: vi.fn(async () => {}),
    seek: vi.fn(async () => {}),
    setRepeatMode: vi.fn(async () => {}),
    startLogin: vi.fn(async () => {}),
    stopLoginPolling: vi.fn(),
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
  } as unknown as MusicStore;
  return { store, actions };
}

describe("LoginQrDialog 4 种状态文案", () => {
  it("waiting 显示「请用手机扫码」", () => {
    const { store } = makeFakeStore({ loginStatus: "waiting" });
    render(<LoginQrDialog store={store} onClose={vi.fn()} />);
    expect(screen.getByTestId("login-qr-dialog")).toHaveAttribute("data-login-status", "waiting");
    expect(screen.getByTestId("login-qr-status").textContent).toBe("请用手机扫码");
  });

  it("scanned 显示「已扫描，请在手机确认」", () => {
    const { store } = makeFakeStore({ loginStatus: "scanned" });
    render(<LoginQrDialog store={store} onClose={vi.fn()} />);
    expect(screen.getByTestId("login-qr-status").textContent).toBe("已扫描，请在手机确认");
  });

  it("confirmed 显示「登录成功」", () => {
    const { store } = makeFakeStore({ loginStatus: "confirmed" });
    render(<LoginQrDialog store={store} onClose={vi.fn()} />);
    expect(screen.getByTestId("login-qr-status").textContent).toBe("登录成功");
  });

  it("expired 显示「二维码过期，请重新获取」", () => {
    const { store } = makeFakeStore({ loginStatus: "expired" });
    render(<LoginQrDialog store={store} onClose={vi.fn()} />);
    expect(screen.getByTestId("login-qr-status").textContent).toBe("二维码过期，请重新获取");
  });

  it("idle 显示「准备中」", () => {
    const { store } = makeFakeStore({ loginStatus: "idle" });
    render(<LoginQrDialog store={store} onClose={vi.fn()} />);
    expect(screen.getByTestId("login-qr-status").textContent).toBe("准备中");
  });
});

describe("LoginQrDialog 二维码渲染", () => {
  it("有 qr_url 时渲染 img", () => {
    const { store } = makeFakeStore({ loginStatus: "waiting" });
    render(<LoginQrDialog store={store} onClose={vi.fn()} />);
    const img = screen.getByTestId("login-qr-image");
    expect(img.tagName).toBe("IMG");
    expect((img as HTMLImageElement).src).toContain("qr.png");
  });

  it("无 qr_url 时渲染图标占位", () => {
    const { store } = makeFakeStore({ loginQr: null, loginStatus: "waiting" });
    render(<LoginQrDialog store={store} onClose={vi.fn()} />);
    expect(screen.queryByTestId("login-qr-image")).toBeNull();
    const wrap = screen.getByTestId("login-qr-image-wrap");
    expect(wrap.querySelector("svg")).not.toBeNull();
  });

  it("显示来源标签 source", () => {
    const { store } = makeFakeStore({ loginStatus: "waiting" });
    render(<LoginQrDialog store={store} onClose={vi.fn()} />);
    expect(screen.getByTestId("login-qr-source").textContent).toBe("netease");
  });

  it("无 loginQr 时不渲染 source 标签", () => {
    const { store } = makeFakeStore({ loginQr: null, loginStatus: "waiting" });
    render(<LoginQrDialog store={store} onClose={vi.fn()} />);
    expect(screen.queryByTestId("login-qr-source")).toBeNull();
  });
});

describe("LoginQrDialog 重新获取按钮", () => {
  it("expired 时显示重新获取按钮", () => {
    const { store } = makeFakeStore({ loginStatus: "expired" });
    render(<LoginQrDialog store={store} onClose={vi.fn()} />);
    expect(screen.getByTestId("login-qr-refresh")).toBeInTheDocument();
  });

  it("非 expired 时不显示重新获取按钮", () => {
    const { store } = makeFakeStore({ loginStatus: "waiting" });
    render(<LoginQrDialog store={store} onClose={vi.fn()} />);
    expect(screen.queryByTestId("login-qr-refresh")).toBeNull();
  });

  it("点击重新获取调 store.startLogin", () => {
    const { store, actions } = makeFakeStore({ loginStatus: "expired" });
    render(<LoginQrDialog store={store} onClose={vi.fn()} />);
    act(() => screen.getByTestId("login-qr-refresh").click());
    expect(actions.startLogin).toHaveBeenCalled();
  });
});

describe("LoginQrDialog 关闭行为", () => {
  it("渲染关闭按钮（X 图标）", () => {
    const { store } = makeFakeStore({ loginStatus: "waiting" });
    render(<LoginQrDialog store={store} onClose={vi.fn()} />);
    expect(screen.getByTestId("login-qr-close")).toBeInTheDocument();
  });

  it("点击关闭按钮调 stopLoginPolling + onClose", () => {
    const { store, actions } = makeFakeStore({ loginStatus: "waiting" });
    const onClose = vi.fn();
    render(<LoginQrDialog store={store} onClose={onClose} />);
    act(() => screen.getByTestId("login-qr-close").click());
    expect(actions.stopLoginPolling).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it("点击遮罩（dialog 容器）触发关闭", () => {
    const { store, actions } = makeFakeStore({ loginStatus: "waiting" });
    const onClose = vi.fn();
    render(<LoginQrDialog store={store} onClose={onClose} />);
    const dialog = screen.getByTestId("login-qr-dialog");
    act(() => dialog.click());
    expect(actions.stopLoginPolling).toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
  });

  it("点击卡片内部不触发关闭（stopPropagation）", () => {
    const { store } = makeFakeStore({ loginStatus: "waiting" });
    const onClose = vi.fn();
    render(<LoginQrDialog store={store} onClose={onClose} />);
    const card = screen.getByTestId("login-qr-card");
    act(() => card.click());
    expect(onClose).not.toHaveBeenCalled();
  });
});

describe("LoginQrDialog 风格约束", () => {
  it("不含 emoji", () => {
    const { store } = makeFakeStore({ loginStatus: "waiting" });
    const { container } = render(<LoginQrDialog store={store} onClose={vi.fn()} />);
    expect(container.textContent ?? "").not.toMatch(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u);
  });

  it("图标渲染为 svg（关闭按钮等）", () => {
    const { store } = makeFakeStore({ loginStatus: "waiting" });
    const { container } = render(<LoginQrDialog store={store} onClose={vi.fn()} />);
    expect(container.querySelectorAll("svg").length).toBeGreaterThan(0);
  });

  it("dialog 有 role=dialog 与 aria-modal", () => {
    const { store } = makeFakeStore({ loginStatus: "waiting" });
    render(<LoginQrDialog store={store} onClose={vi.fn()} />);
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
  });
});
