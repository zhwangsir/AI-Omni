/**
 * visibilitychange 接线（M4.4，M4.3 遗留）：页面隐藏时暂停状态轮询，
 * 重新可见时立即恢复（resume 内部会补拉一轮）。
 * 文档对象抽象成最小接口，测试注入 fake，不依赖真实 document。
 */

export interface VisibilityDocumentLike {
  readonly hidden: boolean;
  addEventListener: (type: "visibilitychange", listener: () => void) => void;
  removeEventListener: (type: "visibilitychange", listener: () => void) => void;
}

export interface Pausable {
  pause: () => void;
  resume: () => void;
}

/**
 * 绑定可见性联动，返回解绑函数。
 * 绑定时若页面已隐藏，立即 pause 一次（不错过启动前的隐藏态）。
 */
export function bindVisibilityPause(
  store: Pausable,
  doc: VisibilityDocumentLike = document,
): () => void {
  const onVisibilityChange = (): void => {
    if (doc.hidden) store.pause();
    else store.resume();
  };
  doc.addEventListener("visibilitychange", onVisibilityChange);
  if (doc.hidden) store.pause();
  return () => doc.removeEventListener("visibilitychange", onVisibilityChange);
}
