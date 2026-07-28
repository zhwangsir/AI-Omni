/**
 * identityStore：助手身份配置 store。
 *
 * 通过 IPC get_assistant_identity 从 Rust 后端获取助手身份（名字、唤醒词等），
 * 避免 UI 组件硬编码名字字符串。非 Tauri 环境降级使用默认值（"雪莉"）。
 */
import { createStore } from "./storeUtils";

export interface AssistantIdentity {
  readonly display_name: string;
  readonly english_name: string;
  readonly wake_aliases: readonly string[];
  readonly wake_response: string;
  readonly idle_label: string;
}

export const DEFAULT_IDENTITY: AssistantIdentity = {
  display_name: "雪莉",
  english_name: "Sherry",
  wake_aliases: ["雪莉", "sherry"],
  wake_response: "我在",
  idle_label: "雪莉 · 待命",
};

interface IdentityState {
  identity: AssistantIdentity;
  loaded: boolean;
}

export const identityStore = createStore<IdentityState>({
  identity: DEFAULT_IDENTITY,
  loaded: false,
});

export async function loadIdentity(
  invoke?: (cmd: string, args?: Record<string, unknown>) => Promise<unknown>,
): Promise<void> {
  if (identityStore.getState().loaded) return;
  try {
    if (invoke) {
      const result = await invoke("get_assistant_identity");
      if (result && typeof result === "object" && "ok" in result && (result as { ok: boolean }).ok) {
        const data = (result as { data?: Record<string, unknown> }).data;
        if (data && typeof data.display_name === "string") {
          identityStore.setState({
            identity: { ...DEFAULT_IDENTITY, ...data } as AssistantIdentity,
            loaded: true,
          });
          return;
        }
      }
    }
  } catch {
    // 非 Tauri 环境或调用失败，使用默认值
  }
  identityStore.setState({ identity: DEFAULT_IDENTITY, loaded: true });
}

export function getAssistantLabel(role: "user" | "assistant"): string {
  if (role === "user") return "用户";
  return identityStore.getState().identity.display_name;
}

export function getIdleLabel(): string {
  return identityStore.getState().identity.idle_label;
}

export function getWakeResponse(): string {
  return identityStore.getState().identity.wake_response;
}

export function getWakeAliases(): readonly string[] {
  return identityStore.getState().identity.wake_aliases;
}
