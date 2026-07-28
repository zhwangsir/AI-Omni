/**
 * LyricsDisplay 组件测试（M18 TDD）。
 *
 * 覆盖：空状态占位 / 行渲染 / 当前行高亮 / 翻译渲染 / 逐字高亮 /
 * 自动滚动（typeof guard）/ 偏移显示 / prefers-reduced-motion /
 * 无 emoji / Icon 组件使用 / pointer-events / positionS 驱动 refreshCurrentLine。
 */
import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  LyricsLine,
  LyricsResult,
  LyricsState,
  LyricsStore,
} from "../../store/lyricsStore";
import { LyricsDisplay } from "./LyricsDisplay";

function makeLine(overrides: Partial<LyricsLine> = {}): LyricsLine {
  return {
    time_s: 1.0,
    text: "故事的小黄花",
    translation: null,
    words: null,
    ...overrides,
  };
}

function makeLyricsResult(overrides: Partial<LyricsResult> = {}): LyricsResult {
  return {
    lyrics: "[00:01.00]故事的小黄花",
    source: "local_file",
    parsed: [makeLine()],
    ...overrides,
  };
}

function makeFakeStore(initial: Partial<LyricsState> = {}): {
  store: LyricsStore;
  actions: Record<string, ReturnType<typeof vi.fn>>;
  setState: (next: Partial<LyricsState>) => void;
} {
  let state: LyricsState = {
    currentLyrics: null,
    currentIndex: -1,
    currentWordIndex: null,
    offsetS: 0,
    isLoading: false,
    error: null,
    ...initial,
  };
  const listeners = new Set<() => void>();
  const actions = {
    fetchLyrics: vi.fn(async () => {}),
    refreshCurrentLine: vi.fn(),
    setOffset: vi.fn(async () => {}),
    searchLyrics: vi.fn(async () => null),
    uploadLyrics: vi.fn(async () => null),
    clear: vi.fn(),
  };
  const store = {
    getState: () => state,
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    ...actions,
  } as unknown as LyricsStore;
  return {
    store,
    actions,
    setState(patch) {
      state = { ...state, ...patch };
      act(() => {
        for (const l of [...listeners]) l();
      });
    },
  };
}

describe("LyricsDisplay 空状态", () => {
  it("无 currentLyrics 时显示「暂无歌词」占位", () => {
    const { store } = makeFakeStore({ currentLyrics: null });
    render(<LyricsDisplay store={store} />);
    expect(screen.getByTestId("lyrics-display")).toHaveAttribute("data-empty", "true");
    expect(screen.getByTestId("lyrics-display").textContent).toContain("暂无歌词");
  });

  it("空状态渲染 FileText 图标（svg）", () => {
    const { store } = makeFakeStore({ currentLyrics: null });
    const { container } = render(<LyricsDisplay store={store} />);
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("currentLyrics 存在但 parsed 为空时也显示空状态", () => {
    const { store } = makeFakeStore({
      currentLyrics: makeLyricsResult({ parsed: [], source: "none", lyrics: null }),
    });
    render(<LyricsDisplay store={store} />);
    expect(screen.getByTestId("lyrics-display")).toHaveAttribute("data-empty", "true");
  });
});

describe("LyricsDisplay 行渲染", () => {
  it("渲染所有歌词行", () => {
    const { store } = makeFakeStore({
      currentLyrics: makeLyricsResult({
        parsed: [
          makeLine({ time_s: 0, text: "第一行" }),
          makeLine({ time_s: 2, text: "第二行" }),
          makeLine({ time_s: 4, text: "第三行" }),
        ],
      }),
      currentIndex: 1,
    });
    render(<LyricsDisplay store={store} />);
    const rows = screen.getAllByTestId("lyrics-row");
    expect(rows).toHaveLength(3);
    expect(rows[0]?.textContent).toContain("第一行");
    expect(rows[1]?.textContent).toContain("第二行");
    expect(rows[2]?.textContent).toContain("第三行");
  });

  it("当前行标记 data-current=true，其他行 data-current=false", () => {
    const { store } = makeFakeStore({
      currentLyrics: makeLyricsResult({
        parsed: [
          makeLine({ time_s: 0, text: "A" }),
          makeLine({ time_s: 2, text: "B" }),
          makeLine({ time_s: 4, text: "C" }),
        ],
      }),
      currentIndex: 1,
    });
    render(<LyricsDisplay store={store} />);
    const rows = screen.getAllByTestId("lyrics-row");
    expect(rows[0]).toHaveAttribute("data-current", "false");
    expect(rows[1]).toHaveAttribute("data-current", "true");
    expect(rows[2]).toHaveAttribute("data-current", "false");
  });

  it("currentIndex 为 -1 时无高亮行", () => {
    const { store } = makeFakeStore({
      currentLyrics: makeLyricsResult({
        parsed: [makeLine({ text: "A" })],
      }),
      currentIndex: -1,
    });
    render(<LyricsDisplay store={store} />);
    const rows = screen.getAllByTestId("lyrics-row");
    expect(rows[0]).toHaveAttribute("data-current", "false");
  });
});

describe("LyricsDisplay 翻译渲染", () => {
  it("有 translation 时在原文下方渲染翻译", () => {
    const { store } = makeFakeStore({
      currentLyrics: makeLyricsResult({
        parsed: [
          makeLine({ time_s: 0, text: "原文", translation: "Translation" }),
        ],
      }),
      currentIndex: 0,
    });
    render(<LyricsDisplay store={store} />);
    expect(screen.getByTestId("lyrics-row-translation").textContent).toBe("Translation");
  });

  it("无 translation 时不渲染翻译元素", () => {
    const { store } = makeFakeStore({
      currentLyrics: makeLyricsResult({
        parsed: [makeLine({ time_s: 0, text: "原文", translation: null })],
      }),
      currentIndex: 0,
    });
    render(<LyricsDisplay store={store} />);
    expect(screen.queryByTestId("lyrics-row-translation")).toBeNull();
  });
});

describe("LyricsDisplay 逐字高亮", () => {
  it("currentWordIndex 不为 null 时高亮当前字", () => {
    const { store } = makeFakeStore({
      currentLyrics: makeLyricsResult({
        parsed: [
          makeLine({
            time_s: 0,
            text: "故事",
            words: [
              { time_s: 0, char: "故" },
              { time_s: 0.5, char: "事" },
            ],
          }),
        ],
      }),
      currentIndex: 0,
      currentWordIndex: 1,
    });
    render(<LyricsDisplay store={store} />);
    // 当前字（事）应被高亮标记
    const highlighted = screen.getByTestId("lyrics-word-current");
    expect(highlighted.textContent).toBe("事");
    // 非当前字（故）应存在但不标记为 current
    const allWords = screen.getAllByTestId("lyrics-word");
    expect(allWords).toHaveLength(2);
  });

  it("currentWordIndex 为 null 时不渲染逐字标记", () => {
    const { store } = makeFakeStore({
      currentLyrics: makeLyricsResult({
        parsed: [
          makeLine({
            time_s: 0,
            text: "故事",
            words: [
              { time_s: 0, char: "故" },
              { time_s: 0.5, char: "事" },
            ],
          }),
        ],
      }),
      currentIndex: 0,
      currentWordIndex: null,
    });
    render(<LyricsDisplay store={store} />);
    expect(screen.queryByTestId("lyrics-word-current")).toBeNull();
    // 整行文本仍渲染
    expect(screen.getByTestId("lyrics-row").textContent).toContain("故事");
  });

  it("非当前行不渲染逐字标记（即使有 words）", () => {
    const { store } = makeFakeStore({
      currentLyrics: makeLyricsResult({
        parsed: [
          makeLine({
            time_s: 0,
            text: "故事",
            words: [
              { time_s: 0, char: "故" },
              { time_s: 0.5, char: "事" },
            ],
          }),
          makeLine({ time_s: 5, text: "其他", words: null }),
        ],
      }),
      currentIndex: 1, // 当前在第二行（无 words）
      currentWordIndex: null,
    });
    render(<LyricsDisplay store={store} />);
    expect(screen.queryByTestId("lyrics-word-current")).toBeNull();
  });
});

describe("LyricsDisplay 偏移显示", () => {
  it("正偏移显示 +N.Ns", () => {
    const { store } = makeFakeStore({
      currentLyrics: makeLyricsResult(),
      offsetS: 0.3,
    });
    render(<LyricsDisplay store={store} />);
    expect(screen.getByTestId("lyrics-offset").textContent).toBe("+0.3s");
  });

  it("负偏移显示 -N.Ns", () => {
    const { store } = makeFakeStore({
      currentLyrics: makeLyricsResult(),
      offsetS: -1.2,
    });
    render(<LyricsDisplay store={store} />);
    expect(screen.getByTestId("lyrics-offset").textContent).toBe("-1.2s");
  });

  it("零偏移显示 +0.0s", () => {
    const { store } = makeFakeStore({
      currentLyrics: makeLyricsResult(),
      offsetS: 0,
    });
    render(<LyricsDisplay store={store} />);
    expect(screen.getByTestId("lyrics-offset").textContent).toBe("+0.0s");
  });

  it("无歌词时不显示偏移", () => {
    const { store } = makeFakeStore({ currentLyrics: null, offsetS: 0.5 });
    render(<LyricsDisplay store={store} />);
    expect(screen.queryByTestId("lyrics-offset")).toBeNull();
  });
});

describe("LyricsDisplay 自动滚动", () => {
  it("当前行变化时调用 scrollIntoView（typeof guard 通过时）", () => {
    // jsdom 不实现 scrollIntoView，补一个 spy
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    const { store, setState } = makeFakeStore({
      currentLyrics: makeLyricsResult({
        parsed: Array.from({ length: 5 }, (_, i) =>
          makeLine({ time_s: i, text: `line-${i}` }),
        ),
      }),
      currentIndex: 0,
    });
    render(<LyricsDisplay store={store} />);
    expect(scrollIntoView).toHaveBeenCalled();
    // 切换当前行 → 再次滚动
    scrollIntoView.mockClear();
    setState({ currentIndex: 3 });
    expect(scrollIntoView).toHaveBeenCalled();
  });

  it("无 scrollIntoView 时不报错（typeof guard）", () => {
    // 删除 scrollIntoView 模拟非 jsdom / 降级环境
    const original = Element.prototype.scrollIntoView;
    // @ts-expect-error 测试故意置空
    Element.prototype.scrollIntoView = undefined;
    const { store } = makeFakeStore({
      currentLyrics: makeLyricsResult({
        parsed: [makeLine({ text: "A" })],
      }),
      currentIndex: 0,
    });
    expect(() => render(<LyricsDisplay store={store} />)).not.toThrow();
    Element.prototype.scrollIntoView = original;
  });
});

describe("LyricsDisplay positionS 驱动 refreshCurrentLine", () => {
  it("positionS 变化时调 store.refreshCurrentLine", () => {
    const { store, actions } = makeFakeStore({
      currentLyrics: makeLyricsResult({
        parsed: [makeLine({ time_s: 0, text: "A" })],
      }),
      currentIndex: 0,
    });
    const { rerender } = render(<LyricsDisplay store={store} positionS={1.0} />);
    expect(actions.refreshCurrentLine).toHaveBeenCalledWith(1.0);
    rerender(<LyricsDisplay store={store} positionS={3.5} />);
    expect(actions.refreshCurrentLine).toHaveBeenCalledWith(3.5);
  });

  it("未传 positionS 时不调 refreshCurrentLine", () => {
    const { store, actions } = makeFakeStore({
      currentLyrics: makeLyricsResult(),
      currentIndex: 0,
    });
    render(<LyricsDisplay store={store} />);
    expect(actions.refreshCurrentLine).not.toHaveBeenCalled();
  });
});

describe("LyricsDisplay 风格约束", () => {
  it("渲染内容不含 emoji（Film Atelier 红线）", () => {
    const { store } = makeFakeStore({
      currentLyrics: makeLyricsResult({
        parsed: [makeLine({ text: "歌词文本" })],
      }),
      currentIndex: 0,
    });
    const { container } = render(<LyricsDisplay store={store} />);
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u);
  });

  it("容器设置 pointer-events:none（非交互展示）", () => {
    const { store } = makeFakeStore({
      currentLyrics: makeLyricsResult(),
      currentIndex: 0,
    });
    render(<LyricsDisplay store={store} />);
    const root = screen.getByTestId("lyrics-display");
    expect(root.style.pointerEvents).toBe("none");
  });

  it("暴露 data-source / data-current-index 属性便于调试", () => {
    const { store } = makeFakeStore({
      currentLyrics: makeLyricsResult({ source: "online" }),
      currentIndex: 2,
    });
    render(<LyricsDisplay store={store} />);
    const root = screen.getByTestId("lyrics-display");
    expect(root).toHaveAttribute("data-source", "online");
    expect(root).toHaveAttribute("data-current-index", "2");
  });

  it("respects prefers-reduced-motion（添加 data-reduced-motion 属性）", () => {
    const matchMediaSpy = vi
      .spyOn(window, "matchMedia")
      .mockImplementation((query: string) => ({
        matches: query.includes("reduce"),
        media: query,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      }));
    const { store } = makeFakeStore({
      currentLyrics: makeLyricsResult(),
      currentIndex: 0,
    });
    render(<LyricsDisplay store={store} />);
    expect(screen.getByTestId("lyrics-display")).toHaveAttribute(
      "data-reduced-motion",
      "true",
    );
    matchMediaSpy.mockRestore();
  });

  it("prefers-reduced-motion 关闭时 data-reduced-motion=false", () => {
    const matchMediaSpy = vi
      .spyOn(window, "matchMedia")
      .mockImplementation((query: string) => ({
        matches: false,
        media: query,
        onchange: null,
        addListener: () => {},
        removeListener: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        dispatchEvent: () => false,
      }));
    const { store } = makeFakeStore({
      currentLyrics: makeLyricsResult(),
      currentIndex: 0,
    });
    render(<LyricsDisplay store={store} />);
    expect(screen.getByTestId("lyrics-display")).toHaveAttribute(
      "data-reduced-motion",
      "false",
    );
    matchMediaSpy.mockRestore();
  });

  it("错误状态显示错误信息（data-error）", () => {
    const { store } = makeFakeStore({
      currentLyrics: null,
      error: "未找到歌曲",
    });
    render(<LyricsDisplay store={store} />);
    expect(screen.getByTestId("lyrics-display")).toHaveAttribute(
      "data-empty",
      "true",
    );
    expect(screen.getByTestId("lyrics-display").textContent).toContain("未找到歌曲");
  });
});
