/**
 * libraryStore 运行时单例（M20.6 接线）。
 *
 * 进程内唯一 libraryStore 实例，供 App.tsx / ShelfView 等共享同一份
 * 本地音乐库状态。与 musicRuntime / lyricsRuntime / agentRuntime 同款
 * 懒构造单例——测试经 ``createLibraryStore({ invoker })`` 自建实例，
 * 不读本单例。
 *
 * M20.6 ShelfView 订阅 libraryStore.playlists 变化触发 shelfStage.setCards()
 * 重建卡片架内容。
 */
import { createLibraryStore, type LibraryStore } from "./libraryStore";

let singleton: LibraryStore | null = null;

/** 获取进程内 libraryStore 单例（首次调用懒构造）。 */
export function getLibraryStore(): LibraryStore {
  singleton ??= createLibraryStore();
  return singleton;
}
