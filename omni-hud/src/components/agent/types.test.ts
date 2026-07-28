/**
 * Agent 可视化数据模型类型契约测试（M13.1 TDD）。
 *
 * 校验 ToolCallRecord / Message / AgentSession 三层结构的字段存在性
 * 与字面量类型守卫——纯类型层契约，运行时只做最小 sanity check。
 */
import { describe, expect, it } from "vitest";

import {
  EMPTY_AGENT_SESSION,
  isToolCallRecord,
  isMessage,
  type AgentSession,
  type Message,
  type ToolCallRecord,
} from "./types";

describe("Agent 可视化数据模型（M13.1）", () => {
  describe("ToolCallRecord 类型契约", () => {
    it("合法 ToolCallRecord 通过 isToolCallRecord 守卫", () => {
      const record: ToolCallRecord = {
        id: "seq1-0",
        toolName: "home_control_light",
        params: { room: "客厅", action: "on" },
        result: null,
        status: "pending",
        timestamp: 1785088000,
      };
      expect(isToolCallRecord(record)).toBe(true);
    });

    it("pending 状态：result 为 null 表示加载中", () => {
      const record: ToolCallRecord = {
        id: "seq1-0",
        toolName: "home_control_light",
        params: {},
        result: null,
        status: "pending",
        timestamp: 1,
      };
      expect(record.status).toBe("pending");
      expect(record.result).toBeNull();
    });

    it("success 状态：result 为字符串（工具返回）", () => {
      const record: ToolCallRecord = {
        id: "seq1-1",
        toolName: "home_control_light",
        params: { room: "客厅" },
        result: '{"ok":true,"data":{"on":true}}',
        status: "success",
        timestamp: 2,
      };
      expect(isToolCallRecord(record)).toBe(true);
      expect(record.status).toBe("success");
      expect(typeof record.result).toBe("string");
    });

    it("error 状态：result 为错误描述字符串", () => {
      const record: ToolCallRecord = {
        id: "seq1-2",
        toolName: "home_control_light",
        params: {},
        result: "错误：HA 不可达",
        status: "error",
        timestamp: 3,
      };
      expect(record.status).toBe("error");
    });

    it("缺少 id 字段被守卫拒绝", () => {
      const bad = {
        toolName: "x",
        params: {},
        result: null,
        status: "pending",
        timestamp: 1,
      };
      expect(isToolCallRecord(bad)).toBe(false);
    });

    it("非法 status 字面量被守卫拒绝", () => {
      const bad = {
        id: "x",
        toolName: "x",
        params: {},
        result: null,
        status: "running",
        timestamp: 1,
      };
      expect(isToolCallRecord(bad)).toBe(false);
    });

    it("params 必须是对象（Record）", () => {
      const bad = {
        id: "x",
        toolName: "x",
        params: "not-an-object",
        result: null,
        status: "pending",
        timestamp: 1,
      };
      expect(isToolCallRecord(bad)).toBe(false);
    });
  });

  describe("Message 类型契约", () => {
    it("user 消息通过 isMessage 守卫", () => {
      const msg: Message = {
        id: "u-1",
        role: "user",
        text: "打开客厅的灯",
        timestamp: 100,
      };
      expect(isMessage(msg)).toBe(true);
    });

    it("assistant 消息带 toolCalls 通过 isMessage 守卫", () => {
      const msg: Message = {
        id: "a-1",
        role: "assistant",
        text: "好的，已为你打开客厅灯",
        timestamp: 200,
        toolCalls: [
          {
            id: "a-1-tc-0",
            toolName: "home_control_light",
            params: { room: "客厅" },
            result: '{"ok":true}',
            status: "success",
            timestamp: 180,
          },
        ],
      };
      expect(isMessage(msg)).toBe(true);
      expect(msg.toolCalls?.length).toBe(1);
    });

    it("缺少 role 被守卫拒绝", () => {
      const bad = { id: "x", text: "y", timestamp: 1 };
      expect(isMessage(bad)).toBe(false);
    });

    it("非法 role 字面量被守卫拒绝", () => {
      const bad = { id: "x", role: "system", text: "y", timestamp: 1 };
      expect(isMessage(bad)).toBe(false);
    });
  });

  describe("AgentSession 空态", () => {
    it("EMPTY_AGENT_SESSION 含空消息列表与空当前工具调用列表", () => {
      const session: AgentSession = EMPTY_AGENT_SESSION;
      expect(session.messages).toEqual([]);
      expect(session.currentToolCalls).toEqual([]);
    });

    it("EMPTY_AGENT_SESSION 是只读快照（每次引用同值不互相影响）", () => {
      const a = EMPTY_AGENT_SESSION;
      // 只读契约：通过字段访问不抛错
      expect(Array.isArray(a.messages)).toBe(true);
      expect(Array.isArray(a.currentToolCalls)).toBe(true);
    });
  });
});
