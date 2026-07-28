/**
 * identityStore 运行时单例：非 Tauri 环境自动降级，测试经 vi.mock 替换。
 */
import { invoke } from "@tauri-apps/api/core";

import { isTauri } from "../lib/window";
import { loadIdentity, identityStore } from "./identityStore";

let initialized = false;

export function getIdentityStore(): typeof identityStore {
  if (!initialized) {
    initialized = true;
    const invokeFn = isTauri()
      ? (cmd: string) => invoke(cmd)
      : undefined;
    void loadIdentity(invokeFn);
  }
  return identityStore;
}
