/**
 * Fake Tauri bootstrap 脚本（TEST_INFRA D1 决策）。
 *
 * 由 page.addInitScript 注入，在页面 navigation 前执行——确保 src/lib/window.ts:25
 * 的 isTauri() 检查在 store 初始化时已返回 true，进入 Tauri 分支（非降级轮询）。
 *
 * 注入内容：
 * - `window.__TAURI_INTERNALS__`：invoke / transformCallback / convertFileSrc /
 *   unregisterCallback —— @tauri-apps/api/core.js 实际依赖的全局对象
 * - `window.__TAURI_EVENT_PLUGIN_INTERNALS__`：unregisterListener —— event.js 依赖
 * - `window.__omniE2ERouter__`：dispatch(event, payload) —— 触发 listen() 注册的回调
 *
 * invoke 路由策略：
 * - `plugin:event|listen` / `unlisten` / `emit` 在浏览器本地拦截（不调用 Node router），
 *   维护 eventName → Set<callbackId> 注册表；
 * - 其他 command 经 `window.__omniE2E_callRouter('invoke', cmd, args)` 调用 Node 侧 router。
 *
 * transformCallback 实现：返回自增 numeric id，存入 Map<id, {cb, once}>；
 * dispatch(event, payload) 时遍历该事件的所有 callbackId 并调用，once=true 调后删除。
 *
 * 该文件导出一个返回字符串的函数 —— addInitScript 接收字符串，避免闭包序列化陷阱。
 */
import { GLOBAL_KEYS } from "./env";

/**
 * 生成 bootstrap 脚本字符串（注入浏览器侧）。
 *
 * 注意：脚本内的字符串字面量必须避免与源码冲突；
 * 全局对象 key 从 GLOBAL_KEYS 内联以保持单一信息源。
 */
export function buildBootstrapScript(): string {
  const TAURI_INTERNALS = GLOBAL_KEYS.TAURI_INTERNALS;
  const TAURI_EVENT_PLUGIN_INTERNALS = GLOBAL_KEYS.TAURI_EVENT_PLUGIN_INTERNALS;
  const OMNI_E2E_ROUTER = GLOBAL_KEYS.OMNI_E2E_ROUTER;
  const OMNI_E2E_CALL_ROUTER = GLOBAL_KEYS.OMNI_E2E_CALL_ROUTER;

  return `
(function bootstrapOmniE2E() {
  if (window[${JSON.stringify(TAURI_INTERNALS)}]) return; // 幂等：重复注入直接跳过

  var callbacks = new Map(); // callbackId -> { cb, once }
  var nextCallbackId = 1;
  // 事件订阅表：eventName -> Set<callbackId>
  var eventListeners = new Map();

  function getListenerSet(event) {
    var set = eventListeners.get(event);
    if (!set) { set = new Set(); eventListeners.set(event, set); }
    return set;
  }

  window[${JSON.stringify(TAURI_INTERNALS)}] = {
    invoke: function (cmd, args, options) {
      // 事件相关 command 在浏览器本地拦截（不调 Node router）
      if (cmd === 'plugin:event|listen') {
        var ev = (args && args.event) || '';
        var handlerId = (args && args.handler) || 0;
        getListenerSet(ev).add(handlerId);
        return Promise.resolve(handlerId); // 用 handlerId 作 eventId
      }
      if (cmd === 'plugin:event|unlisten') {
        var ev2 = (args && args.event) || '';
        var eventId = (args && args.eventId) || 0;
        var set2 = eventListeners.get(ev2);
        if (set2) set2.delete(eventId);
        return Promise.resolve(undefined);
      }
      if (cmd === 'plugin:event|emit') {
        var ev3 = (args && args.event) || '';
        var payload = (args && args.payload);
        window[${JSON.stringify(OMNI_E2E_ROUTER)}].dispatch(ev3, payload);
        return Promise.resolve(undefined);
      }
      // 其他 command 转发 Node 侧 router
      return window[${JSON.stringify(OMNI_E2E_CALL_ROUTER)}]('invoke', cmd, args || {});
    },
    transformCallback: function (cb, once) {
      var id = nextCallbackId++;
      callbacks.set(id, { cb: cb, once: !!once });
      return id;
    },
    unregisterCallback: function (id) {
      callbacks.delete(id);
    },
    convertFileSrc: function (filePath, protocol) {
      // 模拟 asset:// 协议；测试侧不依赖真实文件读取
      return 'http://asset.localhost/' + encodeURIComponent(String(filePath));
    },
    // 内部：由 dispatch 调用，触发某个 callbackId 对应的回调
    _invokeCallback: function (id, payload) {
      var entry = callbacks.get(id);
      if (!entry) return;
      try { entry.cb(payload); }
      catch (e) { console.error('[fake-tauri] callback error:', e); }
      if (entry.once) callbacks.delete(id);
    }
  };

  window[${JSON.stringify(TAURI_EVENT_PLUGIN_INTERNALS)}] = {
    unregisterListener: function (event, eventId) {
      var set = eventListeners.get(event);
      if (set) set.delete(eventId);
    }
  };

  window[${JSON.stringify(OMNI_E2E_ROUTER)}] = {
    // 触发某事件的所有 listen() 回调
    dispatch: function (event, payload) {
      var set = eventListeners.get(event);
      if (!set) return;
      set.forEach(function (callbackId) {
        window[${JSON.stringify(TAURI_INTERNALS)}]._invokeCallback(callbackId, {
          event: event,
          payload: payload,
          id: callbackId
        });
      });
    },
    // 测试侧调试用：返回当前订阅的事件名列表
    _listEvents: function () {
      return Array.from(eventListeners.keys());
    }
  };

  // 标记 E2E 注入完成，便于 spec 等待
  window.__omniE2EReady = true;
})();
`;
}
