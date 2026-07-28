// M6.1 spike 验证脚本：Playwright webkit + chromium 对照
// 用法：node verify.mjs [webkit|chromium|both]
import { webkit, chromium } from "playwright";
import { mkdirSync, writeFileSync } from "node:fs";

// 注意：localhost:5173 的 IPv6(::1) 被本机 UniHub Vite dev server 占用；
// 本页由 python http.server 绑在 127.0.0.1:5173(IPv4)，OpenTalking CORS 白名单放行此源。
const PAGE_URL = "http://127.0.0.1:5173/index.html";
const OUT_DIR = new URL("./", import.meta.url).pathname;

async function runOne(kind) {
  const type = kind === "webkit" ? webkit : chromium;
  const launchOpts = { headless: true };
  if (kind === "chromium") launchOpts.args = ["--autoplay-policy=no-user-gesture-required"];
  const browser = await type.launch(launchOpts);
  const page = await browser.newPage({ viewport: { width: 900, height: 1300 } });
  const consoleLines = [];
  page.on("console", (m) => consoleLines.push(m.text()));
  page.on("pageerror", (e) => consoleLines.push("PAGEERROR: " + e.message));

  const t0 = Date.now();
  const result = { browser: kind, checks: {}, ok: false };
  try {
    await page.goto(PAGE_URL, { waitUntil: "load", timeout: 15000 });
    await page.click("#connect");

    // 1) ICE connected/completed
    await page.waitForFunction(
      () => window.__SPIKE && (window.__SPIKE.iceState === "connected" || window.__SPIKE.iceState === "completed" || window.__SPIKE.error),
      { timeout: 30000 }
    );
    let s = await page.evaluate(() => window.__SPIKE);
    result.checks.iceState = s.iceState;
    if (s.error) throw new Error("page error: " + s.error);

    // 2) video track live + 尺寸 + 帧推进
    await page.waitForFunction(
      () => window.__SPIKE.videoWidth > 0 && window.__SPIKE.frames > 5,
      { timeout: 30000 }
    );
    const f1 = await page.evaluate(() => window.__SPIKE.frames);
    await page.waitForTimeout(2000);
    s = await page.evaluate(() => window.__SPIKE);
    const fps = (s.frames - f1) / 2;
    Object.assign(result.checks, {
      tracks: s.tracks, videoSize: `${s.videoWidth}x${s.videoHeight}`,
      framesTotal: s.frames, fpsMeasured: fps.toFixed(1),
      connState: s.connState, signalingState: s.signalingState,
    });

    // 3) 截图：视频渲染中
    await page.screenshot({ path: OUT_DIR + `shot-${kind}-video.png` });

    // 4) speak → 音频验证
    await page.click("#speak");
    await page.waitForTimeout(9000);
    s = await page.evaluate(() => window.__SPIKE);
    Object.assign(result.checks, {
      speakPosted: s.speakPosted, speakResponse: s.speakResponse,
      audioUnmuted: s.audioUnmuted,
      audioLevelPeak: s.audioLevelPeak,
      audioAlive: s.audioUnmuted || s.audioLevelPeak > 0.0005,
    });
    await page.screenshot({ path: OUT_DIR + `shot-${kind}-speak.png` });

    // 5) 判定
    const videoOk = s.videoWidth === 560 && s.videoHeight === 1024 && fps > 0;
    result.checks.verdicts = {
      ice: ["connected", "completed"].includes(result.checks.iceState),
      videoSize560x1024: s.videoWidth === 560 && s.videoHeight === 1024,
      fpsPositive: fps > 0,
      audio: result.checks.audioAlive,
    };
    result.ok = result.checks.verdicts.ice && videoOk && result.checks.audioAlive;
    result.elapsedMs = Date.now() - t0;
  } catch (e) {
    result.error = String(e.message || e);
    try { result.lastState = await page.evaluate(() => window.__SPIKE); } catch {}
    try { await page.screenshot({ path: OUT_DIR + `shot-${kind}-error.png` }); } catch {}
  } finally {
    result.consoleTail = consoleLines.slice(-60);
    await browser.close();
  }
  return result;
}

const which = process.argv[2] || "both";
const kinds = which === "both" ? ["webkit", "chromium"] : [which];
const results = [];
for (const k of kinds) {
  console.log(`\n===== ${k} =====`);
  const r = await runOne(k);
  results.push(r);
  console.log(JSON.stringify({ ...r, consoleTail: undefined }, null, 2));
  console.log("--- console tail ---");
  for (const l of r.consoleTail) console.log("  " + l);
}
const outFile = OUT_DIR + "verify-results.json";
writeFileSync(outFile, JSON.stringify(results, null, 2));
console.log("\nwritten:", outFile);
const anyFail = results.some((r) => !r.ok);
process.exit(anyFail ? 1 : 0);
