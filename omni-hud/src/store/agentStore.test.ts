/**
 * agentStore 测试（M13.1 TDD）：Agent 可视化会话状态。
 *
 * 框架无关订阅模式（与 hudStore/statusStore 同款），React 侧经
 * useSyncExternalStore 绑定。单元测试不依赖 React 渲染。
 */
import { describe, expect, it, vi } from "vitest";

import { createAgentStore } from "./agentStore";

describe("Agent 可视化会话状态（M13.1）", () => {
  describe("初始状态", () => {
    it("初始 messages 为空数组", () => {
      const store = createAgentStore();
      expect(store.getState().messages).toEqual([]);
    });

    it("初始 currentToolCalls 为空数组", () => {
      const store = createAgentStore();
      expect(store.getState().currentToolCalls).toEqual([]);
    });
  });

  describe("addUserMessage", () => {
    it("添加用户消息到 messages 末尾，role=user", () => {
      const store = createAgentStore();
      store.addUserMessage("打开客厅的灯");
      const state = store.getState();
      expect(state.messages.length).toBe(1);
      expect(state.messages[0].role).toBe("user");
      expect(state.messages[0].text).toBe("打开客厅的灯");
    });

    it("用户消息不附带 toolCalls", () => {
      const store = createAgentStore();
      store.addUserMessage("你好");
      expect(store.getState().messages[0].toolCalls).toBeUndefined();
    });

    it("连续添加多条用户消息保持顺序", () => {
      const store = createAgentStore();
      store.addUserMessage("第一条");
      store.addUserMessage("第二条");
      store.addUserMessage("第三条");
      const msgs = store.getState().messages;
      expect(msgs.map((m) => m.text)).toEqual(["第一条", "第二条", "第三条"]);
    });

    it("每条消息获得唯一 id 与时间戳", () => {
      const store = createAgentStore();
      store.addUserMessage("a");
      store.addUserMessage("b");
      const [m1, m2] = store.getState().messages;
      expect(m1.id).not.toBe(m2.id);
      expect(m1.timestamp).toBeLessThanOrEqual(m2.timestamp);
    });
  });

  describe("addAssistantMessage", () => {
    it("添加雪莉回复消息，role=assistant", () => {
      const store = createAgentStore();
      store.addAssistantMessage("好的，已为你打开客厅灯");
      const msg = store.getState().messages[0];
      expect(msg.role).toBe("assistant");
      expect(msg.text).toBe("好的，已为你打开客厅灯");
    });

    it("添加 assistant 消息后清空 currentToolCalls（本轮已结束）", () => {
      const store = createAgentStore();
      store.addToolCall({
        id: "t1",
        toolName: "home_control_light",
        params: { room: "客厅" },
        result: null,
        status: "pending",
        timestamp: 1,
      });
      expect(store.getState().currentToolCalls.length).toBe(1);
      store.addAssistantMessage("已完成");
      expect(store.getState().currentToolCalls).toEqual([]);
    });

    it("可携带本轮完成的 toolCalls 列表（追加到 assistant 消息）", () => {
      const store = createAgentStore();
      const toolCall = {
        id: "t1",
        toolName: "home_control_light",
        params: { room: "客厅" },
        result: '{"ok":true}',
        status: "success" as const,
        timestamp: 1,
      };
      store.addAssistantMessage("已开灯", [toolCall]);
      const msg = store.getState().messages[0];
      expect(msg.toolCalls?.length).toBe(1);
      expect(msg.toolCalls?.[0].toolName).toBe("home_control_light");
    });
  });

  describe("addToolCall", () => {
    it("添加 pending 工具调用到 currentToolCalls", () => {
      const store = createAgentStore();
      store.addToolCall({
        id: "t1",
        toolName: "home_control_light",
        params: {},
        result: null,
        status: "pending",
        timestamp: 1,
      });
      expect(store.getState().currentToolCalls.length).toBe(1);
      expect(store.getState().currentToolCalls[0].status).toBe("pending");
    });

    it("多个工具调用按顺序追加（多轮工具链）", () => {
      const store = createAgentStore();
      store.addToolCall({
        id: "t1",
        toolName: "tool_a",
        params: {},
        result: null,
        status: "pending",
        timestamp: 1,
      });
      store.addToolCall({
        id: "t2",
        toolName: "tool_b",
        params: {},
        result: null,
        status: "pending",
        timestamp: 2,
      });
      const calls = store.getState().currentToolCalls;
      expect(calls.map((c) => c.toolName)).toEqual(["tool_a", "tool_b"]);
    });
  });

  describe("updateToolCall", () => {
    it("更新工具调用结果：pending → success", () => {
      const store = createAgentStore();
      store.addToolCall({
        id: "t1",
        toolName: "tool_a",
        params: {},
        result: null,
        status: "pending",
        timestamp: 1,
      });
      store.updateToolCall("t1", {
        result: '{"ok":true}',
        status: "success",
      });
      const call = store.getState().currentToolCalls[0];
      expect(call.status).toBe("success");
      expect(call.result).toBe('{"ok":true}');
    });

    it("更新工具调用结果：pending → error", () => {
      const store = createAgentStore();
      store.addToolCall({
        id: "t1",
        toolName: "tool_a",
        params: {},
        result: null,
        status: "pending",
        timestamp: 1,
      });
      store.updateToolCall("t1", {
        result: "错误：HA 不可达",
        status: "error",
      });
      expect(store.getState().currentToolCalls[0].status).toBe("error");
    });

    it("更新不存在的 toolCall id 静默忽略（不抛错）", () => {
      const store = createAgentStore();
      expect(() =>
        store.updateToolCall("nonexistent", { result: "x", status: "success" }),
      ).not.toThrow();
      expect(store.getState().currentToolCalls).toEqual([]);
    });

    it("保留未更新字段（仅改 status 时 params/toolName 不变）", () => {
      const store = createAgentStore();
      store.addToolCall({
        id: "t1",
        toolName: "tool_a",
        params: { room: "客厅" },
        result: null,
        status: "pending",
        timestamp: 1,
      });
      store.updateToolCall("t1", { status: "success", result: "ok" });
      const call = store.getState().currentToolCalls[0];
      expect(call.toolName).toBe("tool_a");
      expect(call.params).toEqual({ room: "客厅" });
      expect(call.timestamp).toBe(1);
    });
  });

  describe("clearSession", () => {
    it("清空所有消息与当前工具调用", () => {
      const store = createAgentStore();
      store.addUserMessage("hello");
      store.addToolCall({
        id: "t1",
        toolName: "tool_a",
        params: {},
        result: null,
        status: "pending",
        timestamp: 1,
      });
      store.addAssistantMessage("hi");
      store.clearSession();
      const state = store.getState();
      expect(state.messages).toEqual([]);
      expect(state.currentToolCalls).toEqual([]);
    });
  });

  describe("订阅与通知", () => {
    it("状态变化通知订阅者", () => {
      const store = createAgentStore();
      const listener = vi.fn();
      store.subscribe(listener);
      store.addUserMessage("hello");
      expect(listener).toHaveBeenCalledTimes(1);
    });

    it("退订后不再通知", () => {
      const store = createAgentStore();
      const listener = vi.fn();
      const unsubscribe = store.subscribe(listener);
      unsubscribe();
      store.addUserMessage("hello");
      expect(listener).not.toHaveBeenCalled();
    });

    it("多个订阅者均被通知", () => {
      const store = createAgentStore();
      const l1 = vi.fn();
      const l2 = vi.fn();
      store.subscribe(l1);
      store.subscribe(l2);
      store.addUserMessage("hello");
      expect(l1).toHaveBeenCalledTimes(1);
      expect(l2).toHaveBeenCalledTimes(1);
    });
  });

  describe("完整轮次流程", () => {
    it("用户问 → 工具调用 → 工具结果 → 雪莉回复（currentToolCalls 周期）", () => {
      const store = createAgentStore();
      store.addUserMessage("打开客厅的灯");
      expect(store.getState().currentToolCalls).toEqual([]);

      store.addToolCall({
        id: "t1",
        toolName: "home_control_light",
        params: { room: "客厅", action: "on" },
        result: null,
        status: "pending",
        timestamp: 100,
      });
      expect(store.getState().currentToolCalls.length).toBe(1);

      store.updateToolCall("t1", { result: '{"ok":true}', status: "success" });
      expect(store.getState().currentToolCalls[0].status).toBe("success");

      const completedCalls = [...store.getState().currentToolCalls];
      store.addAssistantMessage("已为你打开客厅灯", completedCalls);
      const state = store.getState();
      expect(state.messages.length).toBe(2);
      expect(state.messages[1].toolCalls?.length).toBe(1);
      expect(state.currentToolCalls).toEqual([]);
    });
  });
});
