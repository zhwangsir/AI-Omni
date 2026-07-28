import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Icon } from "./Icon";

describe("Icon 封装（lucide-react 唯一来源）", () => {
  it("渲染注册图标为 svg", () => {
    const { container } = render(<Icon name="activity" />);
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("size / strokeWidth / color 透传到 svg 属性", () => {
    const { container } = render(
      <Icon name="mic" size={24} strokeWidth={2.5} color="#ff0000" />,
    );
    const svg = container.querySelector("svg")!;
    expect(svg.getAttribute("width")).toBe("24");
    expect(svg.getAttribute("height")).toBe("24");
    expect(svg.getAttribute("stroke-width")).toBe("2.5");
    expect(svg.getAttribute("stroke")).toBe("#ff0000");
  });

  it("默认尺寸 16，无 label 时对辅助技术隐藏", () => {
    const { container } = render(<Icon name="house" />);
    const svg = container.querySelector("svg")!;
    expect(svg.getAttribute("width")).toBe("16");
    expect(svg.getAttribute("aria-hidden")).toBe("true");
  });

  it("提供 label 时暴露 role=img 与可访问名", () => {
    render(<Icon name="cpu" label="处理器" />);
    expect(screen.getByRole("img", { name: "处理器" })).toBeInTheDocument();
  });

  it("M7.4 睡眠切换图标 moon / sun 已登记且可渲染", () => {
    const { container: moonBox } = render(<Icon name="moon" label="睡眠" />);
    expect(moonBox.querySelector("svg")).not.toBeNull();
    expect(screen.getByRole("img", { name: "睡眠" })).toBeInTheDocument();

    const { container: sunBox } = render(<Icon name="sun" label="唤醒" />);
    expect(sunBox.querySelector("svg")).not.toBeNull();
  });

  it("M17.10 音乐控制图标全部已登记且可渲染", () => {
    const names = [
      "play",
      "pause",
      "skipForward",
      "skipBack",
      "repeat",
      "repeat1",
      "shuffle",
      "listMusic",
      "music",
      "music2",
      "x",
    ] as const;
    for (const name of names) {
      const { container } = render(<Icon name={name} label={name} />);
      expect(container.querySelector("svg"), `图标 ${name} 应渲染为 svg`).not.toBeNull();
    }
  });
});
