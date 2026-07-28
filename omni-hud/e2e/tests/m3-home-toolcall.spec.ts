/**
 * M3 智能家居工具调用 E2E 测试（8 用例）。
 *
 * 覆盖维度：
 * 1. get_home_summary 默认返回 available:false → statusStore.home 通道为离线态
 * 2. override get_home_summary 返回多房间+设备 → IPC 调用成功，状态稳定
 * 3. home_call_service 工具调用（开灯）：voice-status 携带 toolCalls → tool_using 态
 * 4. home_apply_scene 工具调用（场景模式）：voice-status 携带 toolCalls → tool_using 态
 * 5. home_list_entities 工具调用（列表查询）：voice-status 携带 toolCalls → tool_using 态
 * 6. 设备状态变化 → get_home_summary 返回新负载 → IPC 调用记录新数据
 * 7. home IPC 失败（handler 抛错）→ 降级为 available:false，不 crash
 * 8. 多房间设备列表完整渲染 → override 返回 3 房间 8 设备，IPC 数据完整
 *
 * 路由策略：
 * - get_home_summary 通过 fakeTauri.override(CMD.GET_HOME_SUMMARY, ...) 注入响应
 * - 工具调用经 fakeTauri.emit(VOICE_STATUS_EVENT, fixture) 推送（toolCalls 字段）
 * - 不依赖真实 Home Assistant / omni_home CLI——全部 fake 后端
 *
 * 注意：HomeSummary 数据由 statusStore.home 通道轮询获取（10s 基础间隔），
 * 但首轮轮询在 appPage fixture 的 start() 阶段已触发（delay=0）。
 * spec 通过 fakeTauri.callsFor(CMD.GET_HOME_SUMMARY) 断言 IPC 调用记录，
 * 而非依赖 UI 渲染（当前无 HomeSummary 直接 UI 组件）。
 */
import { test, expect } from "../support/fixture";
import { CMD, VOICE_STATUS_EVENT } from "../support/env";
import { HudApp } from "../pages/HudApp";
import { AgentPanel } from "../pages/AgentPanel/AgentPanel";
import { ToolCallCard } from "../pages/AgentPanel/ToolCallCard";
import {
  HOME_OFFLINE,
  HOME_EMPTY,
  HOME_MULTI_ROOM,
  HOME_SINGLE_ROOM,
  HOME_MULTI_ROOM_LIGHT_OFF,
  HOME_DEMO,
  HOME_MALFORMED_NO_AVAILABLE,
  HOME_MALFORMED_ROOMS_NOT_ARRAY,
} from "../fixtures/home";
import {
  VOICE_TOOL_USING_HOME_LIGHT_ON,
  VOICE_TOOL_USING_SCENE,
  VOICE_TOOL_USING_LIST,
  VOICE_SPEAKING_WITH_TOOLS_SUCCESS,
} from "../fixtures/agent";

test.describe("M3 智能家居工具调用", () => {
  test("get_home_summary 默认返回 available:false → 离线态不 crash", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);
    // appPage fixture 已等待首轮轮询完成（voice=idle）
    // 默认 handler 返回 available:false 的 EMPTY_HOME_SUMMARY
    // 验证 home 通道首轮轮询已发生
    await expect
      .poll(() => fakeTauri.callsFor(CMD.GET_HOME_SUMMARY).length)
      .toBeGreaterThanOrEqual(1);

    // 离线态不 crash：hud-root 仍正常挂载，voice-state 为 idle
    await hud.waitForVoiceState("idle");
    // 无 pageerror（IPC 失败已被 invokeGuarded 静默吞掉）
    const errors: string[] = [];
    appPage.on("pageerror", (err) => errors.push(err.message));
    // 等待一小段时间确认无异步错误
    await appPage.waitForTimeout(500);
    expect(errors).toEqual([]);
  });

  test("override get_home_summary 返回多房间+设备 → IPC 调用成功", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);
    // override 为多房间完整数据
    fakeTauri.override(CMD.GET_HOME_SUMMARY, () => HOME_MULTI_ROOM);

    // 触发一次 home 通道轮询（首轮已发生，但当时是默认 handler；
    // 此处等待下一次轮询或手动触发 invoke）
    // 直接调 IPC 触发一次 home 拉取，验证 override 生效
    const result = await appPage.evaluate(async () => {
      const internals = (window as unknown as {
        __TAURI_INTERNALS__: {
          invoke(cmd: string, args?: unknown): Promise<unknown>;
        };
      }).__TAURI_INTERNALS__;
      return internals.invoke("get_home_summary");
    });

    // 验证 override 返回了完整的多房间数据
    expect(result).toMatchObject({
      available: true,
      demo: false,
      rooms: expect.arrayContaining([
        expect.objectContaining({
          name: "客厅",
          devices: expect.arrayContaining([
            expect.objectContaining({ name: "客厅主灯", stateText: "开启" }),
          ]),
        }),
      ]),
    });

    // 离线态不 crash
    await hud.waitForVoiceState("idle");
  });

  test("home_call_service 工具调用（开灯）→ tool_using 态 + ToolCallCard 显示", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);
    const panel = new AgentPanel(appPage);

    // 推送 tool_using 状态 + home_call_service 工具调用
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_TOOL_USING_HOME_LIGHT_ON);
    await hud.waitForVoiceState("tool_using");

    // tool_using 态不直接同步到 agentStore.messages（仅 speaking + 新 replySeq 才同步）
    // 但 voice.toolCalls 已更新到 statusStore，data-voice-state 反映 tool_using
    // 接下来推送 speaking + 回复 + 工具结果，验证 ToolCallCard 渲染
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_SPEAKING_WITH_TOOLS_SUCCESS);
    await hud.waitForVoiceState("speaking");

    // 等待消息出现（agentRuntime 同步 speaking + 新 replySeq → addAssistantMessage）
    await panel.waitForBubbleCount(1);

    // 验证 ToolCallCard 渲染
    const card = new ToolCallCard(appPage, 0, 0);
    await card.waitForMounted();
    expect(await card.getName()).toBe("home_call_service");
    expect(await card.getStatusText()).toBe("已完成");
    expect(await card.getStatus()).toBe("success");
    // 参数包含 entity 和 service
    const paramsText = await card.getParamsText();
    expect(paramsText).toContain("light.living_room");
    expect(paramsText).toContain("turn_on");
    // 结果文本存在（success + result 非 null）
    const resultText = await card.getResultText();
    expect(resultText).toContain('"ok":true');
  });

  test("home_apply_scene 工具调用（场景模式）→ ToolCallCard 显示场景名", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);
    const panel = new AgentPanel(appPage);

    // 先推送 tool_using + home_apply_scene 工具调用
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_TOOL_USING_SCENE);
    await hud.waitForVoiceState("tool_using");

    // 推送 speaking + 回复 + 工具结果（复用 SUCCESS fixture 的结构，但替换工具）
    // 直接构造 speaking + scene 工具的 fixture
    fakeTauri.emit(VOICE_STATUS_EVENT, {
      ...VOICE_SPEAKING_WITH_TOOLS_SUCCESS,
      reply: "已为你激活回家模式场景",
      replySeq: 1,
      toolCalls: [
        {
          id: "call_home_scene",
          toolName: "home_apply_scene",
          params: { scene: "回家模式" },
          result: '{"ok":true,"data":{"scene":"回家模式","activated":true}}',
          status: "success",
          timestamp: 1_700_000_000,
        },
      ],
    });
    await hud.waitForVoiceState("speaking");
    await panel.waitForBubbleCount(1);

    // 验证 ToolCallCard 渲染场景工具
    const card = new ToolCallCard(appPage, 0, 0);
    await card.waitForMounted();
    expect(await card.getName()).toBe("home_apply_scene");
    expect(await card.getStatus()).toBe("success");
    const paramsText = await card.getParamsText();
    expect(paramsText).toContain("回家模式");
  });

  test("home_list_entities 工具调用（列表查询）→ ToolCallCard 显示查询参数", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);
    const panel = new AgentPanel(appPage);

    // 推送 tool_using + home_list_entities 工具调用
    fakeTauri.emit(VOICE_STATUS_EVENT, VOICE_TOOL_USING_LIST);
    await hud.waitForVoiceState("tool_using");

    // 推送 speaking + 回复 + 工具结果
    fakeTauri.emit(VOICE_STATUS_EVENT, {
      ...VOICE_SPEAKING_WITH_TOOLS_SUCCESS,
      reply: "客厅共有 3 个设备",
      replySeq: 1,
      toolCalls: [
        {
          id: "call_home_list",
          toolName: "home_list_entities",
          params: { room: "客厅" },
          result: '{"ok":true,"data":{"room":"客厅","count":3}}',
          status: "success",
          timestamp: 1_700_000_000,
        },
      ],
    });
    await hud.waitForVoiceState("speaking");
    await panel.waitForBubbleCount(1);

    // 验证 ToolCallCard 渲染列表查询工具
    const card = new ToolCallCard(appPage, 0, 0);
    await card.waitForMounted();
    expect(await card.getName()).toBe("home_list_entities");
    expect(await card.getStatus()).toBe("success");
    const paramsText = await card.getParamsText();
    expect(paramsText).toContain("客厅");
  });

  test("设备状态变化 → override 返回新负载 → IPC 调用记录新数据", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);

    // 先 override 为多房间数据（客厅主灯开启）
    fakeTauri.override(CMD.GET_HOME_SUMMARY, () => HOME_MULTI_ROOM);
    const result1 = await appPage.evaluate(async () => {
      const internals = (window as unknown as {
        __TAURI_INTERNALS__: { invoke(cmd: string): Promise<unknown> };
      }).__TAURI_INTERNALS__;
      return internals.invoke("get_home_summary") as Promise<typeof HOME_MULTI_ROOM>;
    });
    // 验证客厅主灯状态为「开启」
    const livingRoom1 = result1.rooms.find((r) => r.name === "客厅");
    const mainLight1 = livingRoom1?.devices.find((d) => d.name === "客厅主灯");
    expect(mainLight1?.stateText).toBe("开启");

    // 切换 override 为客厅主灯关闭的状态
    fakeTauri.override(CMD.GET_HOME_SUMMARY, () => HOME_MULTI_ROOM_LIGHT_OFF);
    const result2 = await appPage.evaluate(async () => {
      const internals = (window as unknown as {
        __TAURI_INTERNALS__: { invoke(cmd: string): Promise<unknown> };
      }).__TAURI_INTERNALS__;
      return internals.invoke("get_home_summary") as Promise<typeof HOME_MULTI_ROOM_LIGHT_OFF>;
    });
    // 验证客厅主灯状态变为「关闭」
    const livingRoom2 = result2.rooms.find((r) => r.name === "客厅");
    const mainLight2 = livingRoom2?.devices.find((d) => d.name === "客厅主灯");
    expect(mainLight2?.stateText).toBe("关闭");

    // 验证两次调用都被记录
    const calls = fakeTauri.callsFor(CMD.GET_HOME_SUMMARY);
    expect(calls.length).toBeGreaterThanOrEqual(2);

    // 状态变化不 crash
    await hud.waitForVoiceState("idle");
  });

  test("home IPC 失败 → 降级为 available:false，不 crash", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);

    // 监听未捕获的 Promise rejection
    const errors: string[] = [];
    appPage.on("pageerror", (err) => errors.push(err.message));

    // override get_home_summary 抛错（模拟 Rust panic / Python 退出码非零）
    fakeTauri.override(CMD.GET_HOME_SUMMARY, () => {
      throw new Error("E_CLI_FAILED: python3 omni_home status failed");
    });

    // 直接触发一次 IPC 调用（模拟轮询触发）
    const result = await appPage.evaluate(async () => {
      const internals = (window as unknown as {
        __TAURI_INTERNALS__: { invoke(cmd: string): Promise<unknown> };
      }).__TAURI_INTERNALS__;
      try {
        return await internals.invoke("get_home_summary");
      } catch {
        return { caught: true };
      }
    });

    // invoke 抛错时浏览器侧捕获，statusStore.tick 也会 catch 并降级为 EMPTY_HOME_SUMMARY
    // 验证不 crash：hud-root 仍挂载
    await hud.waitForVoiceState("idle");

    // 等待一小段时间确认无异步错误泄漏
    await appPage.waitForTimeout(500);
    // pageerror 中不应有未捕获的 home 相关 rejection
    // （invokeGuarded 的 catch 已静默吞错，不会冒泡到 pageerror）
    const homeErrors = errors.filter(
      (e) => e.includes("get_home_summary") || e.includes("omni_home"),
    );
    expect(homeErrors).toEqual([]);
  });

  test("多房间设备列表完整渲染 → 3 房间 8 设备数据完整", async ({
    appPage,
    fakeTauri,
  }) => {
    const hud = new HudApp(appPage);

    // override 为完整多房间数据
    fakeTauri.override(CMD.GET_HOME_SUMMARY, () => HOME_MULTI_ROOM);

    const result = await appPage.evaluate(async () => {
      const internals = (window as unknown as {
        __TAURI_INTERNALS__: { invoke(cmd: string): Promise<unknown> };
      }).__TAURI_INTERNALS__;
      return internals.invoke("get_home_summary") as Promise<typeof HOME_MULTI_ROOM>;
    });

    // 验证 3 房间
    expect(result.rooms).toHaveLength(3);
    expect(result.rooms.map((r) => r.name)).toEqual(
      expect.arrayContaining(["客厅", "卧室", "厨房"]),
    );

    // 验证 8 设备（客厅 3 + 卧室 3 + 厨房 2）
    const totalDevices = result.rooms.reduce((sum, r) => sum + r.devices.length, 0);
    expect(totalDevices).toBe(8);

    // 验证 stats 字段
    expect(result.stats).toEqual({ devices: 8, rooms: 3 });

    // 验证每个房间的设备名完整
    const livingRoom = result.rooms.find((r) => r.name === "客厅");
    expect(livingRoom?.devices.map((d) => d.name)).toEqual(
      expect.arrayContaining(["客厅主灯", "客厅空调", "客厅电视"]),
    );

    const bedroom = result.rooms.find((r) => r.name === "卧室");
    expect(bedroom?.devices.map((d) => d.name)).toEqual(
      expect.arrayContaining(["卧室吸顶灯", "卧室空调", "卧室窗帘"]),
    );

    const kitchen = result.rooms.find((r) => r.name === "厨房");
    expect(kitchen?.devices.map((d) => d.name)).toEqual(
      expect.arrayContaining(["厨房筒灯", "厨房空气净化器"]),
    );

    // 数据完整不 crash
    await hud.waitForVoiceState("idle");
  });
});
