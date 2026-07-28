/**
 * M13 Agent 面板 E2E 测试（8 用例）。
 *
 * 覆盖维度：
 * 1. 默认空对话面板：agent-panel-empty 显示「雪莉待命中」
 * 2. speaking + reply → 消息出现在面板（agentRuntime 同步）
 * 3. tool_using + toolCalls → speaking 转换后 ToolCallCard 显示
 * 4. 工具调用状态变化（pending → success）：tool_using 阶段 pending，speaking 阶段 success
 * 5. 多轮对话消息顺序：replySeq 1 → 2 → 3，消息按序追加
 * 6. 消息滚动到底部：新消息追加后 scrollIntoView 触发
 * 7. agentStore 清空：clearSession 后回到空状态
 * 8. tool_using → speaking 转换时工具结果保留：speaking 消息携带 toolCalls
 *
 * 路由策略：
 * - voice-status 事件推送（fakeTauri.emit）模拟 Rust voice_watch 状态变化
 * - agentRuntime.bindAgentSync（App.tsx 挂载时绑定）监听 speaking + replySeq 变化
 *   → addAssistantMessage(reply, toolCalls) → AgentPanel 渲染 MessageBubble
 * - 不直接操作 agentStore（经 voice 状态驱动，与生产路径一致）
 */
import { test, expect } from "../support/fixture";
import { VOICE_STATUS_EVENT } from "../support/env";
import { HudApp } from "../pages/HudApp";
import { AgentPanel } from "../pages/AgentPanel/AgentPanel";
import { ToolCallCard } from "../pages/AgentPanel/ToolCallCard";
import {
  VOICE_SPEAKING_PLAIN,
  VOICE_TOOL_USING_HOME_LIGHT_ON,
  VOICE_SPEAKING_WITH_TOOLS_SUCCESS,
  VOICE_SPEAKING_WITH_TOOLS_ERROR,
  VOICE_SPEAKING_ROUND_2,
  VOICE_SPEAKING_ROUND_3,
} from "../fixtures/agent";

test.describe("M13 Agent 面板", () => {
  test("默认空对话面板：显示「雪莉待命中」空状态", async ({ appPage }) => {
    const hud = new HudApp(appPage);
    const panel = new AgentPanel(appPage);

    // appPage fixture 等待首轮轮询完成，voice=idle，windowMode=null→full
    // AgentPanel 在 full 模式下挂载
    await panel.waitForMounted();

    // 空状态：无消息气泡
    expect(await panel.getBubbleCount()).toBe(0);
    // 空状态提示显示
    await panel.waitForEmpty();
    const emptyText = await appPage
      .locator('[data-testid="agent-panel-empty"]')
      .textContent();
    expect(emptyText).toContain("雪莉待命中");
  });

  test("speaking + reply → 消息出现在面板（agentRuntime 同步）", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);
    const panel = new AgentPanel(appPage);

    // 确认初始为空状态
    await panel.waitForMounted();
    expect(await panel.getBubbleCount()).toBe(0);

    // 推送 speaking + reply="你好，我在" replySeq=1
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_SPEAKING_PLAIN);
    await hud.waitForVoiceState("speaking");

    // agentRuntime.bindAgentSync 检测 speaking + 新 replySeq → addAssistantMessage
    // 等待消息出现
    await panel.waitForBubbleCount(1);

    // 验证消息内容
    expect(await panel.getBubbleRole(0)).toBe("assistant");
    const text = await panel.getBubbleText(0);
    expect(text).toContain("你好，我在");

    // 空状态应消失
    expect(await panel.isEmpty()).toBe(false);
  });

  test("tool_using + toolCalls → speaking 转换后 ToolCallCard 显示", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);
    const panel = new AgentPanel(appPage);

    // 先推送 tool_using（pending 工具调用）
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_TOOL_USING_HOME_LIGHT_ON);
    await hud.waitForVoiceState("tool_using");

    // tool_using 态不直接同步消息（仅 speaking + 新 replySeq 才同步）
    // 但 voice.toolCalls 已更新，待 speaking 时携带
    expect(await panel.getBubbleCount()).toBe(0);

    // 推送 speaking + 回复 + 工具结果（success）
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_SPEAKING_WITH_TOOLS_SUCCESS);
    await hud.waitForVoiceState("speaking");
    await panel.waitForBubbleCount(1);

    // 验证 ToolCallCard 渲染
    const cardCount = await panel.getBubbleToolCallCardCount(0);
    expect(cardCount).toBe(1);

    const card = new ToolCallCard(appPage, 0, 0);
    await card.waitForMounted();
    expect(await card.getName()).toBe("home_call_service");
    expect(await card.getStatus()).toBe("success");
    expect(await card.getStatusText()).toBe("已完成");
  });

  test("工具调用状态变化（pending → success）", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);
    const panel = new AgentPanel(appPage);

    // 推送 tool_using + pending 工具调用
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_TOOL_USING_HOME_LIGHT_ON);
    await hud.waitForVoiceState("tool_using");

    // tool_using 态无消息（不同步到 agentStore）
    expect(await panel.getBubbleCount()).toBe(0);

    // 推送 speaking + success 工具结果
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_SPEAKING_WITH_TOOLS_SUCCESS);
    await hud.waitForVoiceState("speaking");
    await panel.waitForBubbleCount(1);

    // 验证工具卡片状态为 success
    const card = new ToolCallCard(appPage, 0, 0);
    await card.waitForMounted();
    expect(await card.getStatus()).toBe("success");
    expect(await card.getStatusText()).toBe("已完成");
    // 结果文本存在
    const resultText = await card.getResultText();
    expect(resultText).toContain('"ok":true');
  });

  test("工具调用状态变化（pending → error）", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);
    const panel = new AgentPanel(appPage);

    // 推送 tool_using + pending 工具调用
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_TOOL_USING_HOME_LIGHT_ON);
    await hud.waitForVoiceState("tool_using");

    // 推送 speaking + error 工具结果
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_SPEAKING_WITH_TOOLS_ERROR);
    await hud.waitForVoiceState("speaking");
    await panel.waitForBubbleCount(1);

    // 验证工具卡片状态为 error
    const card = new ToolCallCard(appPage, 0, 0);
    await card.waitForMounted();
    expect(await card.getStatus()).toBe("error");
    expect(await card.getStatusText()).toBe("失败");
    // 结果文本包含错误信息
    const resultText = await card.getResultText();
    expect(resultText).toContain("HA 不可达");
  });

  test("多轮对话消息顺序：replySeq 1 → 2 → 3 按序追加", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);
    const panel = new AgentPanel(appPage);

    // 第一轮：reply="已为你打开客厅主灯" seq=1
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_SPEAKING_WITH_TOOLS_SUCCESS);
    await hud.waitForVoiceState("speaking");
    await panel.waitForBubbleCount(1);

    // 第二轮：reply="好的，我已经帮你关掉了" seq=2
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_SPEAKING_ROUND_2);
    await hud.waitForVoiceState("speaking");
    await panel.waitForBubbleCount(2);

    // 第三轮：reply="还有什么可以帮你的吗？" seq=3
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_SPEAKING_ROUND_3);
    await hud.waitForVoiceState("speaking");
    await panel.waitForBubbleCount(3);

    // 验证消息顺序（按追加顺序）
    const text0 = await panel.getBubbleText(0);
    const text1 = await panel.getBubbleText(1);
    const text2 = await panel.getBubbleText(2);
    expect(text0).toContain("已为你打开客厅主灯");
    expect(text1).toContain("好的，我已经帮你关掉了");
    expect(text2).toContain("还有什么可以帮你的吗？");

    // 所有消息都是 assistant 角色
    expect(await panel.getBubbleRole(0)).toBe("assistant");
    expect(await panel.getBubbleRole(1)).toBe("assistant");
    expect(await panel.getBubbleRole(2)).toBe("assistant");
  });

  test("消息滚动到底部：新消息追加后 scrollIntoView 触发", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);
    const panel = new AgentPanel(appPage);

    // 注入 scrollIntoView spy（在 emit 前注入，确保捕获所有调用）
    // AgentPanel 的 useEffect 调 bottomRef.scrollIntoView({ behavior: "smooth", block: "end" })
    // Chromium 真实实现会滚动容器；这里用 spy 验证调用本身（不依赖容器溢出）
    await appPage.evaluate(() => {
      const calls: unknown[] = [];
      const original = Element.prototype.scrollIntoView;
      Element.prototype.scrollIntoView = function (this: Element, ...args: unknown[]) {
        calls.push({ testid: this.getAttribute("data-testid"), args });
        return original.apply(this, args as never[]);
      };
      (window as unknown as Record<string, unknown>).__omniE2E_scrollIntoViewCalls = calls;
    });

    // 第一轮消息
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_SPEAKING_PLAIN);
    await hud.waitForVoiceState("speaking");
    await panel.waitForBubbleCount(1);

    // 第二轮消息
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_SPEAKING_ROUND_2);
    await hud.waitForVoiceState("speaking");
    await panel.waitForBubbleCount(2);

    // 验证 scrollIntoView 被调用（新消息追加触发 useEffect → scrollIntoView）
    await expect
      .poll(async () => {
        const calls = await appPage.evaluate(() => {
          return (window as unknown as Record<string, unknown[]>)
            .__omniE2E_scrollIntoViewCalls as unknown[];
        });
        return calls.length;
      })
      .toBeGreaterThanOrEqual(1);

    // 第三轮消息
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_SPEAKING_ROUND_3);
    await hud.waitForVoiceState("speaking");
    await panel.waitForBubbleCount(3);

    // 再次验证 scrollIntoView 被调用（消息数从 2 → 3 触发）
    await expect
      .poll(async () => {
        const calls = await appPage.evaluate(() => {
          return (window as unknown as Record<string, unknown[]>)
            .__omniE2E_scrollIntoViewCalls as unknown[];
        });
        return calls.length;
      })
      .toBeGreaterThanOrEqual(2);
  });

  test("agentStore 清空：经 __omniDebug.agent.clearSession 回到空状态", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);
    const panel = new AgentPanel(appPage);

    // 先添加一条消息
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_SPEAKING_PLAIN);
    await hud.waitForVoiceState("speaking");
    await panel.waitForBubbleCount(1);
    expect(await panel.isEmpty()).toBe(false);

    // 经 __omniDebug.agent.clearSession 触发清空（续听超时 / 用户主动清空的模拟）
    const cleared = await appPage.evaluate(() => {
      const w = window as unknown as {
        __omniDebug?: {
          agent?: {
            clearSession?: () => void;
          };
        };
      };
      if (w.__omniDebug?.agent?.clearSession) {
        w.__omniDebug.agent.clearSession();
        return true;
      }
      return false;
    });
    expect(cleared).toBe(true);

    // clearSession 后应回到空状态
    await panel.waitForEmpty();
    expect(await panel.getBubbleCount()).toBe(0);
  });

  test("tool_using → speaking 转换时工具结果保留", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);
    const panel = new AgentPanel(appPage);

    // tool_using 阶段：pending 工具调用
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_TOOL_USING_HOME_LIGHT_ON);
    await hud.waitForVoiceState("tool_using");
    expect(await panel.getBubbleCount()).toBe(0); // 不同步消息

    // speaking 阶段：携带工具结果（success）
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_SPEAKING_WITH_TOOLS_SUCCESS);
    await hud.waitForVoiceState("speaking");
    await panel.waitForBubbleCount(1);

    // 验证工具卡片仍存在（结果保留）
    const cardCount = await panel.getBubbleToolCallCardCount(0);
    expect(cardCount).toBe(1);

    const card = new ToolCallCard(appPage, 0, 0);
    await card.waitForMounted();
    expect(await card.getName()).toBe("home_call_service");
    expect(await card.getStatus()).toBe("success");
    expect(await card.getStatusText()).toBe("已完成");

    // 切到 thinking 态（windowMode 仍为 full，AgentPanel 保持挂载）
    // 验证消息与工具卡片仍保留（不丢失）
    fakeTauri.emit(VOICE_STATUS_EVENT, {
      ...VOICE_TOOL_USING_HOME_LIGHT_ON,
      state: "thinking",
    });
    await hud.waitForVoiceState("thinking");
    // AgentPanel 仍挂载（full 模式），消息保留
    expect(await panel.getBubbleCount()).toBe(1);
    const cardCountAfterTransition = await panel.getBubbleToolCallCardCount(0);
    expect(cardCountAfterTransition).toBe(1);
  });
});
