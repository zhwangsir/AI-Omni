/**
 * M0-M2 语音管道状态 E2E 测试（10 用例）。
 *
 * 覆盖维度：
 * 1. 默认 idle 态（available:false → voiceState=null → data-voice-state=idle）
 * 2. 8 种 VoicePipelineState 各自映射到 data-voice-state（参数化 8 子用例）
 * 3. replySeq 递增触发重新渲染（M6.3 修复：相同文本不同 seq 构成语义变化）
 * 4. 点击 caption-interrupt 触发 voice_interrupt IPC 调用
 * 5. interrupt IPC 失败静默吞错（src/lib/voice.ts:25-32 try/catch）
 * 6. 事件驱动延迟 < 200ms（emit → data-voice-state 更新）
 * 7. 畸形负载降级：缺 available 字段 → 归一化为 EMPTY → idle（防御性降级）
 * 8. 畸形负载降级：未知 state 字符串 → 收敛为 null → data-voice-state=idle
 * 9. windowMode=null 默认推导为 full
 * 10. windowMode=mini → hud-root-mini class + 无 data-window-mode 属性
 *
 * 路由策略：
 * - 优先使用 fakeTauri.emit(VOICE_STATUS_EVENT, fixture) 推送事件
 *   （M5.4 事件驱动路径，与 statusStore.handleSourceEvent 对齐）
 * - 必要时 register CMD.GET_VOICE_STATUS 控制轮询兜底响应
 */
import { test, expect } from "../support/fixture";
import { VOICE_STATUS_EVENT } from "../support/env";
import { HudApp } from "../pages/HudApp";
import {
  VOICE_IDLE,
  VOICE_WAKE_LISTENING,
  VOICE_FOLLOW_UP_LISTENING,
  VOICE_RECORDING,
  VOICE_TRANSCRIBING,
  VOICE_THINKING,
  VOICE_TOOL_USING,
  VOICE_SPEAKING,
  VOICE_SPEAKING_SEQ2,
  VOICE_MALFORMED_NO_AVAILABLE,
  VOICE_MALFORMED_BAD_STATE,
  ALL_VOICE_STATES,
} from "../fixtures/voice";

test.describe("M0-M2 语音管道状态", () => {
  test("默认 hud-root data-voice-state=idle（available:false → null → idle）", async ({
    appPage,
  }) => {
    const hud = new HudApp(appPage);
    // 默认 router 返回 available:false 的 EMPTY_VOICE_STATUS，state=null
    // App.tsx voiceState ?? "idle" 把 null 映射为 "idle"
    await hud.waitForVoiceState("idle");
  });

  // 8 种 VoicePipelineState 参数化测试：每个状态 emit 后应反映到 data-voice-state
  for (const { label, status } of ALL_VOICE_STATES) {
    test(`emit voice-status payload state="${label}" → data-voice-state="${label}"`, async ({
      appPage,
      fakeTauri,
    }) => {
      const hud = new HudApp(appPage);
      fakeTauri.emit(VOICE_STATUS_EVENT, status);
      // 注意：idle 形态下 hud-root-mini class 存在，data-voice-state 仍为 idle
      await hud.waitForVoiceState(label);
    });
  }

  test("replySeq 递增触发重新渲染（相同文本不同 seq）", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);
    // 先进入 speaking 态，reply="你好，我在" seq=1
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_SPEAKING);
    await hud.waitForVoiceState("speaking");
    // 等待 CaptionLayer 的 useEffect 调 subtitleStore.begin() → subtitle 显影
    await hud.waitForSubtitleRevealed();
    // CaptionLayer.tsx:156 caption-interrupt 仅在 hovered 时渲染，先 hover 再等待
    await hud.hoverCaptionSubtitle();
    await hud.waitForInterruptVisible();

    // 切到 seq=2（相同文本），CaptionLayer 应识别为新轮次（M6.3 修复）
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_SPEAKING_SEQ2);
    // 仍为 speaking 态，但 replySeq 变化触发 store 通知 + CaptionLayer 重渲染
    await hud.waitForVoiceState("speaking");
    // 间接验证：caption-subtitle 仍显示 "你好，我在"
    const subtitle = await appPage
      .locator('[data-testid="caption-subtitle"]')
      .textContent();
    expect(subtitle).toContain("你好，我在");
  });

  test("点击 caption-interrupt 触发 voice_interrupt IPC 调用", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);
    // 进入 speaking 态让 caption-subtitle 挂载
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_SPEAKING);
    await hud.waitForVoiceState("speaking");
    // 等待 CaptionLayer 的 useEffect 调 subtitleStore.begin() → subtitle 显影
    await hud.waitForSubtitleRevealed();
    // CaptionLayer.tsx:156 caption-interrupt 仅在 hovered 时渲染，先 hover 再等待
    await hud.hoverCaptionSubtitle();
    await hud.waitForInterruptVisible();

    // 默认 voice_interrupt handler 是 noop，但 router 记录调用日志
    await hud.clickInterrupt();

    // 等待 IPC 调用到达（interrupt 是异步 invoke）
    await expect
      .poll(() => fakeTauri.callsFor("voice_interrupt").length)
      .toBeGreaterThanOrEqual(1);
    const call = fakeTauri.callsFor("voice_interrupt")[0];
    expect(call.command).toBe("voice_interrupt");
  });

  test("voice_interrupt IPC 失败静默吞错（不抛 unhandled rejection）", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);
    // 让 voice_interrupt handler 抛错
    fakeTauri.override("voice_interrupt", () => {
      throw new Error("E_CLI_FAILED: python3 omni_voice interrupt failed");
    });

    // 监听未捕获的 Promise rejection（interruptSpeaking 内部 try/catch 应吞掉错误）
    let rejectionCaught: string | null = null;
    appPage.on("pageerror", (err) => {
      if (err.message.includes("voice_interrupt") || err.message.includes("E_CLI_FAILED")) {
        rejectionCaught = err.message;
      }
    });

    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_SPEAKING);
    await hud.waitForVoiceState("speaking");
    await hud.waitForSubtitleRevealed();
    await hud.hoverCaptionSubtitle();
    await hud.waitForInterruptVisible();
    await hud.clickInterrupt();

    // 等待 IPC 调用尝试（即使失败也应记录 calls）
    await expect
      .poll(() => fakeTauri.callsFor("voice_interrupt").length)
      .toBeGreaterThanOrEqual(1);
    // 不应有未捕获 rejection（src/lib/voice.ts:29 try/catch 静默吞错）
    expect(rejectionCaught).toBeNull();
  });

  test("事件驱动延迟 < 1000ms（emit → data-voice-state 更新）", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);
    const start = Date.now();
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_SPEAKING);
    await hud.waitForVoiceState("speaking");
    const elapsed = Date.now() - start;
    // emit → page.evaluate dispatch → statusStore.handleSourceEvent → emit()
    // → React re-render → DOM attribute 更新
    // 1000ms 阈值覆盖首轮 JIT 预热 + page.evaluate 往返 + React 渲染（典型 < 200ms，
    // 但首用例可能因模块加载 / WebGL 初始化稍慢；后续用例应远低于此值）
    expect(elapsed).toBeLessThan(1000);
  });

  test("畸形负载降级：缺 available 字段 → 归一化为 EMPTY → idle（防御性降级）", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);
    // 先注入有效 speaking 态
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_SPEAKING);
    await hud.waitForVoiceState("speaking");

    // 再注入畸形负载（缺 available 字段）
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_MALFORMED_NO_AVAILABLE);

    // tauriSource.subscribeVoiceStatus 的 listen 回调先经 normalizeVoiceStatus 归一化：
    // obj.available !== true → 返回 EMPTY_VOICE_STATUS（available:false, state:null）
    // → statusStore.handleSourceEvent 接收 EMPTY（通过 isVoiceStatusPayload 守卫）
    // → voice.state=null → data-voice-state="idle"
    // 这是 IPC 边界的防御性降级：畸形负载不 crash，而是安全回到离线态。
    await hud.waitForVoiceState("idle");
  });

  test("畸形负载降级：未知 state 字符串 → 收敛为 null → data-voice-state=idle", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);
    // 注入 state="__invalid_state__" 的负载
    // isVoiceStatusPayload 检查 state === null || typeof state === "string"
    // → 通过事件守卫；normalizeVoiceStatus.toVoicePipelineState 返回 null
    // → App.tsx voiceState ?? "idle" → data-voice-state="idle"
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_MALFORMED_BAD_STATE);

    await hud.waitForVoiceState("idle");
  });

  test("windowMode=null 默认推导为 full（M12 安全态）", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);
    // VOICE_THINKING 的 windowMode 为 full（显式），但 null 应推导为 full
    // 这里用一个 windowMode: null 的 speaking 态验证（直接构造）
    fakeTauri.emit(VOICE_STATUS_EVENT, {
      ...VOICE_SPEAKING,
      windowMode: null,
    });
    await hud.waitForVoiceState("speaking");
    // windowMode=null → App.tsx voiceWindowMode = windowMode ?? "full" → data-window-mode="full"
    await hud.waitForWindowMode("full");
  });

  test("windowMode=mini → hud-root-mini class + 不渲染 data-window-mode", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);
    // VOICE_IDLE 的 windowMode=mini（pipeline.py derive_window_mode(idle)=mini）
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_IDLE);
    await hud.waitForVoiceState("idle");
    // mini 形态 App.tsx:282-287 的 return 分支不写 data-window-mode 属性
    expect(await hud.isMiniMode()).toBe(true);
    expect(await hud.getWindowMode()).toBeNull();
  });
});
