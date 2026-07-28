/**
 * M4-M7 显影场 E2E 测试（7 用例）。
 *
 * 覆盖维度：
 * 1. 状态标随 voice.state 变化显影（idle/wake_listening/speaking 等）
 * 2. 状态标 2.5s 后渐隐（CaptionLayer STATUS_MARK_LINGER_MS）
 * 3. speaking 态字幕显示 reply 文本（subtitleStore.begin + appendChunk）
 * 4. 离开 speaking → 字幕渐隐（subtitleStore.finish → fadingOut → 卸载）
 * 5. WellZone 在 idle 态可见（full 形态下 WellZone 恒挂载）
 * 6. WellZone 在 mini 形态不渲染（App.tsx mini 分支仅渲染 MiniBar）
 * 7. 4 态场语义切换（idle → wake_listening → thinking → speaking）
 *
 * 注意：
 * - ImmersiveSpace 懒加载 3D 场景，不依赖 WebGL canvas 内容，用 data-* 属性断言
 * - 状态标 2.5s 渐隐用 STATUS_MARK_LINGER_MS 常量对齐源码
 * - 字幕渐隐三阶段：finish 后 1200ms 展示 → 400ms 渐隐 → 卸载
 * - voice.state=idle 默认 windowMode=mini，需构造 idle+full 负载验证 full 形态下 WellZone
 */
import { test, expect } from "../support/fixture";
import { VOICE_STATUS_EVENT } from "../support/env";
import { HudApp } from "../pages/HudApp";
import {
  CaptionLayerPage,
  STATUS_MARK_LINGER_MS,
  SUBTITLE_FINAL_SHOW_MS,
  SUBTITLE_FADE_OUT_MS,
} from "../pages/CaptionLayer";
import { WellZonePage } from "../pages/WellZone";
import {
  VOICE_IDLE,
  VOICE_WAKE_LISTENING,
  VOICE_THINKING,
  VOICE_SPEAKING,
} from "../fixtures/voice";

/** idle 态但 windowMode=full：用于测试 full 形态下 WellZone 在 idle 态的可见性。 */
const VOICE_IDLE_FULL_WINDOW = { ...VOICE_IDLE, windowMode: "full" as const };

test.describe("M4-M7 显影场语义层", () => {
  test("状态标随 voice.state 变化显影（idle → wake_listening）", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);
    const caption = new CaptionLayerPage(appPage);

    // 进入 full 形态（wake_listening → windowMode=full → CaptionLayer 挂载）
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_WAKE_LISTENING);
    await hud.waitForVoiceState("wake_listening");
    await caption.waitForMounted();

    // voice.state 变化时 setMarkVisible(true) → data-visible="true"
    // 初次进入 wake_listening 已触发状态标显影
    await caption.waitForStatusMarkVisible(true);
    expect(await caption.getStatusMarkText()).toBe("wake_listening");

    // 切到 thinking → 状态标再次显影（state 变化触发 setMarkVisible(true)）
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_THINKING);
    await hud.waitForVoiceState("thinking");
    await caption.waitForStatusMarkVisible(true);
    expect(await caption.getStatusMarkText()).toBe("thinking");
  });

  test("状态标 2.5s 后渐隐（STATUS_MARK_LINGER_MS）", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);
    const caption = new CaptionLayerPage(appPage);

    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_WAKE_LISTENING);
    await hud.waitForVoiceState("wake_listening");
    await caption.waitForMounted();
    await caption.waitForStatusMarkVisible(true);

    // 等待 2.5s 计时器到期 → setMarkVisible(false) → data-visible="false"
    // 留 5s 缓冲（React 重渲染 + Playwright 轮询间隔）
    await caption.waitForStatusMarkVisible(false, STATUS_MARK_LINGER_MS + 5_000);
    expect(await caption.getStatusMarkVisible()).toBe(false);
  });

  test("speaking 态字幕显示 reply 文本（begin + appendChunk）", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);
    const caption = new CaptionLayerPage(appPage);

    // VOICE_SPEAKING 携带 reply="你好，我在" + replySeq=1
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_SPEAKING);
    await hud.waitForVoiceState("speaking");

    // CaptionLayer useEffect: speaking + 新 replySeq → subtitleStore.begin + appendChunk(reply)
    // → subtitle.visible=true → caption-subtitle 挂载 + data-revealed="true"
    await caption.waitForSubtitleMounted();
    await caption.waitForSubtitleRevealedState(true);

    // 字幕文本应包含 reply 内容
    const text = await caption.getSubtitleText();
    expect(text).toContain("你好，我在");
  });

  test("离开 speaking → 字幕渐隐（finish → fadingOut → 卸载）", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);
    const caption = new CaptionLayerPage(appPage);

    // 先进入 speaking 让字幕挂载
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_SPEAKING);
    await hud.waitForVoiceState("speaking");
    await caption.waitForSubtitleMounted();
    await caption.waitForSubtitleRevealedState(true);

    // 切到 thinking（离开 speaking，仍为 full 形态保留 CaptionLayer）
    // CaptionLayer useEffect: prevState==="speaking" → subtitleStore.finish()
    // finish 三阶段：finalShowMs(1200ms) 展示 → fadingOut(400ms) → visible=false 卸载
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_THINKING);
    await hud.waitForVoiceState("thinking");

    // 等待进入 fadingOut 阶段（1200ms 后，400ms 窗口内捕获）
    // 使用 waitForFunction 自定义条件：data-fading="true" 或元素已卸载（fading 已完成）
    // 避免 400ms 窗口太窄 Playwright 轮询错过
    await appPage.waitForFunction(
      () => {
        const el = document.querySelector('[data-testid="caption-subtitle"]');
        if (el === null) return true; // 已卸载 = fading 已完成
        return el.getAttribute("data-fading") === "true";
      },
      undefined,
      { timeout: SUBTITLE_FINAL_SHOW_MS + 3_000 },
    );

    // 等待字幕卸载（fadingOut 400ms 后 visible=false → DOM 卸载）
    // 若上方因已卸载提前返回，此处立即通过；否则等待剩余 fading 阶段完成
    await caption.waitForSubtitleUnmounted(SUBTITLE_FADE_OUT_MS + 3_000);
  });

  test("WellZone 在 idle 态可见（full 形态下 WellZone 恒挂载）", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);
    const well = new WellZonePage(appPage);

    // 构造 idle + windowMode=full：验证 full 形态下 WellZone 不依赖 voice.state
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_IDLE_FULL_WINDOW);
    await hud.waitForVoiceState("idle");
    await hud.waitForWindowMode("full");

    // WellZone 在 full 形态下恒挂载（App.tsx:320 渲染 WellZone，无 voice.state 条件）
    await well.waitForMounted();
    expect(await well.getSleeping()).toBe(false);
  });

  test("WellZone 在 mini 形态不渲染（App.tsx mini 分支仅渲染 MiniBar）", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);
    const well = new WellZonePage(appPage);

    // VOICE_IDLE 的 windowMode=mini → App.tsx mini 分支仅渲染 MiniBar
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_IDLE);
    await hud.waitForVoiceState("idle");
    expect(await hud.isMiniMode()).toBe(true);

    // WellZone 在 mini 形态不挂载
    await well.waitForUnmounted();
  });

  test("4 态场语义切换（idle → wake_listening → thinking → speaking）", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);
    const caption = new CaptionLayerPage(appPage);

    // 1. idle（full 形态）：状态标显示 "idle"
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_IDLE_FULL_WINDOW);
    await hud.waitForVoiceState("idle");
    await caption.waitForMounted();
    await caption.waitForStatusMarkVisible(true);
    expect(await caption.getStatusMarkText()).toBe("idle");

    // 2. wake_listening：状态标更新为 "wake_listening"
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_WAKE_LISTENING);
    await hud.waitForVoiceState("wake_listening");
    await caption.waitForStatusMarkVisible(true);
    expect(await caption.getStatusMarkText()).toBe("wake_listening");

    // 3. thinking：状态标更新为 "thinking"
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_THINKING);
    await hud.waitForVoiceState("thinking");
    await caption.waitForStatusMarkVisible(true);
    expect(await caption.getStatusMarkText()).toBe("thinking");

    // 4. speaking：状态标更新为 "speaking" + 字幕挂载显示 reply
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_SPEAKING);
    await hud.waitForVoiceState("speaking");
    await caption.waitForStatusMarkVisible(true);
    expect(await caption.getStatusMarkText()).toBe("speaking");
    await caption.waitForSubtitleMounted();
    expect(await caption.getSubtitleText()).toContain("你好，我在");
  });
});
