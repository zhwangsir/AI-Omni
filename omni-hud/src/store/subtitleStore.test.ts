/**
 * subtitleStore 测试（M6.3 建，M7.2 随 store 迁入 src/store/，M7.5 重构为三阶段）：
 * 全 fake：定时器经 vitest fake timers 控制，不触碰网络 / SSE / DOM。
 * 验证点：增量累计、final 展示→渐隐→隐藏、新 turn 取消挂起、hide 幂等、订阅通知。
 *
 * 三阶段时序（M7.5）：
 *   begin/appendChunk → streaming（visible=true, isFinal=false, fadingOut=false）
 *   finish(finalShowMs) → final_show（visible=true, isFinal=true, fadingOut=false）
 *   finish 后 finalShowMs → fading_out（visible=true, isFinal=true, fadingOut=true）
 *   再 fadeOutMs → hidden（visible=false）
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  SUBTITLE_FADE_OUT_MS,
  SUBTITLE_FINAL_SHOW_MS,
  createSubtitleStore,
} from "./subtitleStore";

describe("subtitleStore 字幕状态机（M6.3，M7.5 三阶段重构）", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("初始为隐藏空字幕", () => {
    const store = createSubtitleStore();
    expect(store.getState()).toEqual({
      text: "",
      isFinal: false,
      fadingOut: false,
      visible: false,
    });
  });

  it("begin（speech.started）开启新 turn：清空旧文并显示", () => {
    const store = createSubtitleStore();
    store.begin();
    store.appendChunk("旧 turn 残留");
    store.finish();
    vi.advanceTimersByTime(10_000); // 旧 turn 完全隐藏

    store.begin();
    expect(store.getState()).toEqual({
      text: "",
      isFinal: false,
      fadingOut: false,
      visible: true,
    });
  });

  it("appendChunk 按增量分片语义累计（依据见 subtitleStore 文件注释）", () => {
    const store = createSubtitleStore();
    store.begin();
    store.appendChunk("客厅灯");
    expect(store.getState().text).toBe("客厅灯");
    store.appendChunk("已经打开");
    store.appendChunk("了。");
    expect(store.getState().text).toBe("客厅灯已经打开了。");
    expect(store.getState().isFinal).toBe(false);
    expect(store.getState().fadingOut).toBe(false);
    expect(store.getState().visible).toBe(true);
  });

  it("finish（speech.ended）定稿：isFinal=true，展示期内保持可见锐利", () => {
    const store = createSubtitleStore();
    store.begin();
    store.appendChunk("分片一");
    store.finish();

    expect(store.getState()).toEqual({
      text: "分片一",
      isFinal: true,
      fadingOut: false,
      visible: true,
    });
    // final_show 期内（差 1ms）：fadingOut 仍为 false，文字锐利
    vi.advanceTimersByTime(SUBTITLE_FINAL_SHOW_MS - 1);
    expect(store.getState().visible).toBe(true);
    expect(store.getState().fadingOut).toBe(false);
  });

  it("finish 展示期结束进入 fading_out，渐隐完成后 hidden", () => {
    expect(SUBTITLE_FINAL_SHOW_MS).toBe(1200);
    expect(SUBTITLE_FADE_OUT_MS).toBe(400);
    const store = createSubtitleStore();
    store.begin();
    store.appendChunk("完整回复");
    store.finish();

    // 到达 finalShowMs：进入 fading_out
    vi.advanceTimersByTime(SUBTITLE_FINAL_SHOW_MS);
    expect(store.getState().fadingOut).toBe(true);
    expect(store.getState().visible).toBe(true); // 仍在 DOM 上，CSS 过渡中

    // fadeOutMs 后：hidden
    vi.advanceTimersByTime(SUBTITLE_FADE_OUT_MS);
    expect(store.getState().visible).toBe(false);
    expect(store.getState().text).toBe("完整回复"); // 文本保留
  });

  it("finish 携带完整文本时以权威全文替换累计（纠正分片丢失）", () => {
    const store = createSubtitleStore();
    store.begin();
    store.appendChunk("残缺的累计");
    store.finish("完整回复全文。");
    expect(store.getState().text).toBe("完整回复全文。");
    expect(store.getState().isFinal).toBe(true);
    expect(store.getState().fadingOut).toBe(false);
  });

  it("finish 未携带文本时保留累计分片", () => {
    const store = createSubtitleStore();
    store.begin();
    store.appendChunk("累计文本");
    store.finish();
    expect(store.getState().text).toBe("累计文本");
  });

  it("展示/渐隐期内新 turn begin 取消挂起计时器，字幕不被误清", () => {
    const store = createSubtitleStore();
    store.begin();
    store.appendChunk("第一轮");
    store.finish();

    vi.advanceTimersByTime(600); // final_show 中
    store.begin(); // 新一轮播报开始
    store.appendChunk("第二轮");

    vi.advanceTimersByTime(10_000); // 旧计时器若残留会误隐藏新 turn
    expect(store.getState()).toEqual({
      text: "第二轮",
      isFinal: false,
      fadingOut: false,
      visible: true,
    });
  });

  it("fading_out 期间新 turn begin 同样取消渐隐计时器", () => {
    const store = createSubtitleStore();
    store.begin();
    store.appendChunk("第一轮");
    store.finish();

    vi.advanceTimersByTime(SUBTITLE_FINAL_SHOW_MS); // 进入 fading_out
    expect(store.getState().fadingOut).toBe(true);

    store.begin(); // 新一轮打断渐隐
    store.appendChunk("第二轮");
    expect(store.getState()).toEqual({
      text: "第二轮",
      isFinal: false,
      fadingOut: false,
      visible: true,
    });

    vi.advanceTimersByTime(10_000);
    expect(store.getState().visible).toBe(true); // 不被误隐
  });

  it("hide（打断 / 卸载）立即隐藏并取消挂起计时器", () => {
    const store = createSubtitleStore();
    store.begin();
    store.appendChunk("被打断的播报");
    store.finish();

    store.hide();
    expect(store.getState().visible).toBe(false);
    expect(store.getState().fadingOut).toBe(false);

    vi.advanceTimersByTime(60_000); // 不得再有状态翻转（无悬挂计时器）
    expect(store.getState().visible).toBe(false);
  });

  it("hide 幂等：空态重复调用不抛错、状态不变", () => {
    const store = createSubtitleStore();
    store.hide();
    store.hide();
    expect(store.getState()).toEqual({
      text: "",
      isFinal: false,
      fadingOut: false,
      visible: false,
    });
  });

  it("状态迁移通知订阅者：begin/append/finish/fadeStart/hide 各发一次", () => {
    const store = createSubtitleStore();
    const listener = vi.fn();
    store.subscribe(listener);

    store.begin(); // 1
    expect(listener).toHaveBeenCalledTimes(1);
    store.appendChunk("片段"); // 2
    expect(listener).toHaveBeenCalledTimes(2);
    store.finish(); // 3
    expect(listener).toHaveBeenCalledTimes(3);

    // finalShowMs 到 → fadingOut（第 4 次）
    vi.advanceTimersByTime(SUBTITLE_FINAL_SHOW_MS);
    expect(listener).toHaveBeenCalledTimes(4);
    expect(store.getState().fadingOut).toBe(true);

    // fadeOutMs 到 → hidden（第 5 次）
    vi.advanceTimersByTime(SUBTITLE_FADE_OUT_MS);
    expect(listener).toHaveBeenCalledTimes(5);
    expect(store.getState().visible).toBe(false);
  });

  it("退订后不再通知", () => {
    const store = createSubtitleStore();
    const listener = vi.fn();
    const unsubscribe = store.subscribe(listener);

    store.begin();
    expect(listener).toHaveBeenCalledTimes(1);

    unsubscribe();
    store.appendChunk("x");
    store.finish();
    vi.advanceTimersByTime(10_000);
    // 退订后仅 begin 那次
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("展示/渐隐时长可经 deps 覆盖", () => {
    const store = createSubtitleStore({ finalShowMs: 300, fadeOutMs: 100 });
    store.begin();
    store.appendChunk("短周期");
    store.finish();

    vi.advanceTimersByTime(299);
    expect(store.getState().fadingOut).toBe(false); // 仍在展示
    vi.advanceTimersByTime(1);
    expect(store.getState().fadingOut).toBe(true); // 开始渐隐
    expect(store.getState().visible).toBe(true);
    vi.advanceTimersByTime(99);
    expect(store.getState().visible).toBe(true); // 渐隐中
    vi.advanceTimersByTime(1);
    expect(store.getState().visible).toBe(false); // 完成
  });
});
