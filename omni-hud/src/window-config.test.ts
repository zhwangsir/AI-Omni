import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const conf = JSON.parse(
  readFileSync(resolve(process.cwd(), "src-tauri/tauri.conf.json"), "utf-8"),
) as {
  productName: string;
  identifier: string;
  build: { frontendDist: string };
  app: { windows: Array<Record<string, unknown>> };
};

describe("Tauri 窗口契约（tauri.conf.json 五项）", () => {
  it("productName 为 omni-hud，identifier 为 com.ai-omni.hud", () => {
    expect(conf.productName).toBe("omni-hud");
    expect(conf.identifier).toBe("com.ai-omni.hud");
  });

  it("透明背景 transparent: true", () => {
    expect(conf.app.windows[0]!.transparent).toBe(true);
  });

  it("无边框 decorations: false", () => {
    expect(conf.app.windows[0]!.decorations).toBe(false);
  });

  it("置顶 alwaysOnTop: true", () => {
    expect(conf.app.windows[0]!.alwaysOnTop).toBe(true);
  });

  it("跳过任务栏 skipTaskbar: true", () => {
    expect(conf.app.windows[0]!.skipTaskbar).toBe(true);
  });

  it("前端产物目录指向 ../dist", () => {
    expect(conf.build.frontendDist).toBe("../dist");
  });
});
