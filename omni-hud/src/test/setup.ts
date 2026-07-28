import "@testing-library/jest-dom/vitest";

// jsdom 未实现 matchMedia，补一个默认不匹配的最小实现，
// 组件据此安全地读取 prefers-reduced-motion。
if (typeof window !== "undefined" && typeof window.matchMedia !== "function") {
  window.matchMedia = ((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  })) as unknown as typeof window.matchMedia;
}

// jsdom 的 HTMLCanvasElement.prototype.getContext 对 "2d" 类型会打印 not-implemented 警告
// 并返回 null（M20 shelf 标题 canvas 纹理需要 2d context）。覆盖为最小 stub：
// 所有绘制方法 no-op，仅提供属性读写接口。真实 canvas 像素测试不在 vitest 范围（需 canvas npm 包）。
if (typeof HTMLCanvasElement !== "undefined") {
  HTMLCanvasElement.prototype.getContext = function getContext(
    this: HTMLCanvasElement,
    _type: string,
  ): CanvasRenderingContext2D | null {
    // 返回 stub 作为 CanvasRenderingContext2D（jsdom 不实现真实 canvas 像素）
    const stub = {
      canvas: this,
      fillStyle: "",
      strokeStyle: "",
      font: "",
      textAlign: "start",
      textBaseline: "alphabetic",
      lineWidth: 1,
      globalAlpha: 1,
      globalCompositeOperation: "source-over",
      fillRect: () => {},
      strokeRect: () => {},
      clearRect: () => {},
      beginPath: () => {},
      closePath: () => {},
      moveTo: () => {},
      lineTo: () => {},
      arc: () => {},
      fill: () => {},
      stroke: () => {},
      fillText: () => {},
      strokeText: () => {},
      measureText: () => ({ width: 0 }),
      save: () => {},
      restore: () => {},
      translate: () => {},
      rotate: () => {},
      scale: () => {},
      drawImage: () => {},
      getImageData: () => ({ data: new Uint8ClampedArray(0), width: 0, height: 0 }),
      putImageData: () => {},
      createLinearGradient: () => ({ addColorStop: () => {} }),
      createRadialGradient: () => ({ addColorStop: () => {} }),
    } as unknown as CanvasRenderingContext2D;
    return stub;
  } as HTMLCanvasElement["getContext"];
}

