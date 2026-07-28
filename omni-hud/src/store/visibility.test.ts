/**
 * visibilitychange → statusStore pause/resume 接线测试（M4.4，M4.3 遗留）。
 * 页面隐藏暂停轮询、重新可见立即恢复；全 fake：fake document + fake store。
 */
import { describe, expect, it, vi } from "vitest";

import { bindVisibilityPause, type VisibilityDocumentLike } from "./visibility";

function makeDoc(initialHidden = false) {
  const listeners = new Set<() => void>();
  const doc: VisibilityDocumentLike & {
    setHidden: (hidden: boolean) => void;
    listenerCount: () => number;
  } = {
    hidden: initialHidden,
    addEventListener: (_type: "visibilitychange", listener: () => void) => {
      listeners.add(listener);
    },
    removeEventListener: (_type: "visibilitychange", listener: () => void) => {
      listeners.delete(listener);
    },
    setHidden(hidden: boolean) {
      (doc as { hidden: boolean }).hidden = hidden;
      for (const listener of [...listeners]) listener();
    },
    listenerCount: () => listeners.size,
  };
  return doc;
}

describe("visibilitychange 接线", () => {
  it("页面隐藏时 pause，重新可见时 resume", () => {
    const doc = makeDoc(false);
    const store = { pause: vi.fn(), resume: vi.fn() };
    bindVisibilityPause(store, doc);
    doc.setHidden(true);
    expect(store.pause).toHaveBeenCalledTimes(1);
    expect(store.resume).not.toHaveBeenCalled();
    doc.setHidden(false);
    expect(store.resume).toHaveBeenCalledTimes(1);
  });

  it("绑定时若页面已隐藏，立即 pause 一次", () => {
    const doc = makeDoc(true);
    const store = { pause: vi.fn(), resume: vi.fn() };
    bindVisibilityPause(store, doc);
    expect(store.pause).toHaveBeenCalledTimes(1);
  });

  it("绑定时页面可见则不打扰轮询", () => {
    const doc = makeDoc(false);
    const store = { pause: vi.fn(), resume: vi.fn() };
    bindVisibilityPause(store, doc);
    expect(store.pause).not.toHaveBeenCalled();
    expect(store.resume).not.toHaveBeenCalled();
  });

  it("返回的解绑函数移除监听，之后可见性变化不再触发", () => {
    const doc = makeDoc(false);
    const store = { pause: vi.fn(), resume: vi.fn() };
    const unbind = bindVisibilityPause(store, doc);
    expect(doc.listenerCount()).toBe(1);
    unbind();
    expect(doc.listenerCount()).toBe(0);
    doc.setHidden(true);
    expect(store.pause).not.toHaveBeenCalled();
  });
});
