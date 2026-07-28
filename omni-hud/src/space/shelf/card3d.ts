/**
 * shelf/card3d 单张卡片组件（M20.2）。
 *
 * 设计决策 D20.2：
 * - Card3D = Mesh(PlaneGeometry + MeshBasicMaterial map=cover/title texture)。
 *   标题 / 副标题经 2D canvas → CanvasTexture 渲染（避免 CSS3DRenderer 第二 renderer）。
 *   封面 URL 异步加载（TextureLoader.load），加载完成替换 material.map；加载中显示标题兜底。
 * - 卡片正面朝向圆心（layout 计算 rotationY）；初始位置在 enterOffset.z 远方（reducedMotion 直挂）。
 * - 悬停 / 选中 scale 经 spring lerp 收敛（updateCardState 推进）；Film Atelier 风格克制有物理感。
 *
 * 与 shelfStage.ts 关系：card3d 提供 buildCardMesh / updateCardState / disposeCard 三个纯函数，
 * shelfStage 负责编排（layout + 状态机 + 帧循环），card3d 负责单卡资源生命周期。
 */
import type { CardData } from "./dataSource";
import type { CardPosition } from "./layout";
import { HOVER_SCALE, SELECT_SCALE } from "./shelfStage";
import type { ShelfGroup, ShelfMesh, ThreeModule } from "../createSpace";

/** 卡片宽度（世界单位）。 */
export const CARD_WIDTH = 1.4;
/** 卡片高度（世界单位，3:4 比例接近专辑封面）。 */
export const CARD_HEIGHT = 1.8;
/** 入场动画 spring 收敛率（/s）。 */
export const ENTER_SPRING_RATE = 4.0;

/** 单张卡片运行时状态。 */
export interface CardRuntime {
  readonly mesh: ShelfMesh;
  readonly target: CardPosition;
  /** 当前 z 偏移（从 enterOffset.z 收敛到 0）。 */
  currentEnterZ: number;
  /** 当前 scale（从 1 收敛到 HOVER_SCALE / SELECT_SCALE）。 */
  currentScale: number;
  /** 封面纹理（异步加载完成后注入；null = 加载中或无封面）。 */
  coverTexture: { dispose?: () => void } | null;
  /** 标题 canvas 纹理（始终存在）。 */
  titleTexture: unknown;
  /** geometry dispose 句柄。 */
  geometryDispose: () => void;
  /** material dispose 句柄。 */
  materialDispose: () => void;
  /** 所有 texture dispose 句柄。 */
  textureDisposers: Array<() => void>;
  /** 标记是否已 dispose（防止异步加载回调操作已释放资源）。 */
  disposed: boolean;
}

/**
 * 为单张卡片构建 Mesh（PlaneGeometry + MeshBasicMaterial，封面异步加载）。
 *
 * @param three three.js 命名空间
 * @param group 父 Group（mesh 添加到此）
 * @param pos layout 计算的位置
 * @param card 卡片数据
 * @param reducedMotion true 时直挂目标位置（无入场偏移）
 */
export function buildCardMesh(
  three: ThreeModule,
  group: ShelfGroup,
  pos: CardPosition,
  card: CardData,
  reducedMotion: boolean,
): CardRuntime {
  const geometry = new three.PlaneGeometry(CARD_WIDTH, CARD_HEIGHT, 1, 1);
  const title = buildTitleTexture(three, card.title, card.subtitle);
  // 初始材质：标题纹理兜底；封面加载完成后替换 map
  const material = new three.MeshBasicMaterial({
    map: title.texture,
    transparent: true,
    opacity: 0.95,
  });
  const mesh = new three.Mesh(geometry, material);
  mesh.position.set(
    pos.position.x,
    pos.position.y,
    pos.position.z + (reducedMotion ? 0 : pos.enterOffset.z),
  );
  mesh.rotation.set(0, pos.rotationY, 0);
  mesh.scale.set(1, 1, 1);
  group.add(mesh);

  const textureDisposers: Array<() => void> = [title.dispose];
  let coverTexture: { dispose?: () => void } | null = null;
  let disposed = false;

  if (card.coverUrl) {
    try {
      const loader = new three.TextureLoader();
      loader.load(card.coverUrl, (tex: unknown) => {
        if (disposed) {
          // 加载完成时卡片已释放：直接 dispose 新纹理避免泄漏
          (tex as { dispose?: () => void } | null)?.dispose?.();
          return;
        }
        coverTexture?.dispose?.();
        const texDisposable = tex as { dispose: () => void };
        coverTexture = texDisposable;
        (material as unknown as { map: unknown }).map = tex;
        (material as unknown as { needsUpdate: boolean }).needsUpdate = true;
        textureDisposers.push(() => texDisposable.dispose());
      });
    } catch {
      // TextureLoader 不可用 / URL 非法 → 静默保留标题兜底
    }
  }

  return {
    mesh,
    target: pos,
    currentEnterZ: reducedMotion ? 0 : pos.enterOffset.z,
    currentScale: 1,
    coverTexture,
    titleTexture: title.texture,
    geometryDispose: () => (geometry as { dispose(): void }).dispose(),
    materialDispose: () => (material as { dispose(): void }).dispose(),
    textureDisposers,
    disposed: false,
  };
}

/**
 * 推进单张卡片动画状态（入场偏移收敛 + scale 收敛）。
 *
 * @param rt 卡片运行时
 * @param hover 当前是否悬停
 * @param selected 当前是否选中
 * @param dt 帧时长（秒）
 */
export function updateCardState(
  rt: CardRuntime,
  hover: boolean,
  selected: boolean,
  dt: number,
): void {
  if (rt.disposed) return;
  const lerpFactor = Math.min(1, dt * ENTER_SPRING_RATE);

  // 入场偏移 z 收敛到 0
  if (rt.currentEnterZ !== 0) {
    rt.currentEnterZ += (0 - rt.currentEnterZ) * lerpFactor;
    if (Math.abs(rt.currentEnterZ) < 0.001) rt.currentEnterZ = 0;
  }

  // 目标 scale：选中 > 悬停 > 默认
  let targetScale = 1;
  if (selected) targetScale = SELECT_SCALE;
  else if (hover) targetScale = HOVER_SCALE;
  rt.currentScale += (targetScale - rt.currentScale) * lerpFactor;

  // 写入 mesh
  const pos = rt.target.position;
  rt.mesh.position.set(pos.x, pos.y, pos.z + rt.currentEnterZ);
  rt.mesh.rotation.set(0, rt.target.rotationY, 0);
  rt.mesh.scale.set(rt.currentScale, rt.currentScale, 1);
}

/**
 * 释放单张卡片资源（geometry / material / texture）并从 group 移除 mesh。
 * 标记 disposed 防止异步加载回调操作已释放资源。
 */
export function disposeCard(group: ShelfGroup, rt: CardRuntime): void {
  if (rt.disposed) return;
  rt.disposed = true;
  rt.geometryDispose();
  rt.materialDispose();
  for (const dispose of rt.textureDisposers) dispose();
  rt.textureDisposers.length = 0;
  group.remove(rt.mesh);
}

/**
 * 构建 2D canvas 标题纹理（Film Atelier 暗房风格）。
 * 半透明暗房底条 + 标题（fog 主前景色）+ 副标题（dim 次前景色）。
 */
function buildTitleTexture(
  three: ThreeModule,
  title: string,
  subtitle: string,
): { texture: unknown; dispose: () => void } {
  const canvas = document.createElement("canvas");
  canvas.width = 256;
  canvas.height = 128;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    // 半透明暗房底条（不遮挡封面主体）
    ctx.fillStyle = "rgba(11, 12, 14, 0.78)";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    // 标题（fog 主前景色 #d8d9dc，与 DEVELOPER_AMBER 主题对齐）
    ctx.fillStyle = "#d8d9dc";
    ctx.font = "600 22px -apple-system, system-ui, sans-serif";
    ctx.textBaseline = "top";
    ctx.fillText(title.slice(0, 14), 12, 14);
    // 副标题（dim 次前景色 #83878f）
    ctx.fillStyle = "#83878f";
    ctx.font = "400 16px -apple-system, system-ui, sans-serif";
    ctx.fillText(subtitle.slice(0, 18), 12, 50);
  }
  const texture = new three.CanvasTexture(canvas);
  return { texture, dispose: () => (texture as { dispose(): void }).dispose() };
}
