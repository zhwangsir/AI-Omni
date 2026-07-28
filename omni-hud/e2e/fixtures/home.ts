/**
 * HomeSummary 测试夹具（M3 家居工具调用 E2E）。
 *
 * 与 src/data/sources.ts 的 HomeSummary / HomeRoomBrief / HomeDeviceBrief 类型对齐，
 * 覆盖多房间 + 多设备类型 + 设备状态变化 + 空 / 离线态。
 *
 * 字段命名严格遵循 src/data/tauriSource.ts 的 normalizeHomeSummary 归一化结果
 * （camelCase），与 Rust 侧 serde 序列化对齐——保证 E2E 注入的负载与真实
 * Rust 推送的字段结构完全一致。
 */
import type { HomeSummary, HomeRoomBrief, HomeDeviceBrief } from "../../src/data/sources";

/**
 * 离线态 HomeSummary（router 默认 handler 返回值）。
 *
 * spec 不需要显式注入——fixture.ts 默认 handler 即返回此结构。
 * 这里导出供 spec 在断言「降级到 EMPTY」时比较。
 */
export const HOME_OFFLINE: HomeSummary = {
  available: false,
  demo: false,
  rooms: [],
  stats: null,
};

/**
 * 空房间 HomeSummary：available:true 但无房间 / 无设备。
 *
 * 用于测试 HA 可达但实体为空时的 UI 降级（不应 crash）。
 */
export const HOME_EMPTY: HomeSummary = {
  available: true,
  demo: false,
  rooms: [],
  stats: { devices: 0, rooms: 0 },
};

/** 构造设备 brief 的工厂函数（便于在多 fixture 中复用）。 */
function device(name: string, stateText: string): HomeDeviceBrief {
  return { name, stateText };
}

/** 客厅设备列表（灯 / 空调 / 电视）。 */
const LIVING_ROOM_DEVICES: readonly HomeDeviceBrief[] = [
  device("客厅主灯", "开启"),
  device("客厅空调", "制冷中（设定 26°C）"),
  device("客厅电视", "关闭"),
];

/** 卧室设备列表（灯 / 空调 / 窗帘）。 */
const BEDROOM_DEVICES: readonly HomeDeviceBrief[] = [
  device("卧室吸顶灯", "关闭"),
  device("卧室空调", "关闭"),
  device("卧室窗帘", "已打开 80%"),
];

/** 厨房设备列表（灯 / 空气净化器）。 */
const KITCHEN_DEVICES: readonly HomeDeviceBrief[] = [
  device("厨房筒灯", "开启"),
  device("厨房空气净化器", "自动模式"),
];

/**
 * 完整多房间 HomeSummary（3 房间 / 8 设备）。
 *
 * 用于测试「多房间设备列表完整渲染」与「override get_home_summary 返回房间+设备」。
 */
export const HOME_MULTI_ROOM: HomeSummary = {
  available: true,
  demo: false,
  rooms: [
    { name: "客厅", devices: LIVING_ROOM_DEVICES },
    { name: "卧室", devices: BEDROOM_DEVICES },
    { name: "厨房", devices: KITCHEN_DEVICES },
  ],
  stats: { devices: 8, rooms: 3 },
};

/**
 * 演示模式 HomeSummary（demo=true，与真实 HA 不可达时的降级一致）。
 *
 * 用于测试 UI 对 demo 模式的标注（若后续 UI 增加标注能力）。
 */
export const HOME_DEMO: HomeSummary = {
  available: true,
  demo: true,
  rooms: [
    {
      name: "客厅",
      devices: [
        device("演示灯", "开启"),
        device("演示空调", "关闭"),
      ],
    },
  ],
  stats: { devices: 2, rooms: 1 },
};

/**
 * 单房间 HomeSummary（客厅 + 3 设备）。
 *
 * 用于测试最小可用数据集下的渲染。
 */
export const HOME_SINGLE_ROOM: HomeSummary = {
  available: true,
  demo: false,
  rooms: [
    { name: "客厅", devices: LIVING_ROOM_DEVICES },
  ],
  stats: { devices: 3, rooms: 1 },
};

/**
 * 设备状态变化后的 HomeSummary：客厅主灯从「开启」→「关闭」。
 *
 * 用于测试「设备状态变化 → UI 更新」用例：先 override 为 HOME_MULTI_ROOM，
 * 再 override 为此 fixture，验证状态文字更新。
 */
export const HOME_MULTI_ROOM_LIGHT_OFF: HomeSummary = {
  available: true,
  demo: false,
  rooms: [
    {
      name: "客厅",
      devices: [
        device("客厅主灯", "关闭"),
        device("客厅空调", "制冷中（设定 26°C）"),
        device("客厅电视", "关闭"),
      ],
    },
    { name: "卧室", devices: BEDROOM_DEVICES },
    { name: "厨房", devices: KITCHEN_DEVICES },
  ],
  stats: { devices: 8, rooms: 3 },
};

/**
 * 畸形 HomeSummary：缺 available 字段，应被 normalizeHomeSummary 守卫拒绝。
 *
 * obj.available !== true → 返回 EMPTY_HOME_SUMMARY（available:false）。
 */
export const HOME_MALFORMED_NO_AVAILABLE = {
  demo: false,
  rooms: [],
  stats: null,
} as unknown as HomeSummary;

/**
 * 畸形 HomeSummary：rooms 字段非数组（字符串），应被 normalizeHomeSummary 归一化为 []。
 *
 * Array.isArray(obj.rooms) === false → rooms: []，但 available:true 保留。
 */
export const HOME_MALFORMED_ROOMS_NOT_ARRAY = {
  available: true,
  demo: false,
  rooms: "not-an-array",
  stats: null,
} as unknown as HomeSummary;
