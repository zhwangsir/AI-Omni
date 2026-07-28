/**
 * space 运行时装配（M5.1）：动态 import three 与后处理模块——
 * 首屏 bundle 不含 three（Vite 自动切 chunk），ImmersiveSpace 懒加载时调用。
 * 真实 three 命名空间 / examples 类在此收口转型为 space 层的最小结构契约。
 *
 * 注意：postfx（EffectComposer + UnrealBloomPass）当前因透明窗口 alpha 冲突暂不加载，
 * bloom 效果改由粒子 shader 双层自发光 sprite 实现；保留 PostfxModules 类型与加载路径，
 * 待 three.js bloom alpha 问题修复后可重新启用。
 */
import type { ThreeModule } from "./createSpace";
import type { PostfxModules } from "./postfx";

export interface SpaceRuntime {
  readonly three: ThreeModule;
  /** 后处理模块；当前禁用（透明窗口冲突），始终为 undefined。 */
  readonly postfx?: PostfxModules;
}

export async function loadSpaceRuntime(): Promise<SpaceRuntime> {
  const three = (await import("three")) as unknown as ThreeModule;
  return {
    three,
    postfx: undefined,
  };
}
