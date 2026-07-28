/**
 * LibraryView Page Object：本地音乐库浏览界面交互入口（M19 E2E）。
 *
 * 封装对 library-view 容器及其子组件的查询与交互：
 * - data-testid="library-view"：根容器（经 __omniDebug.mountLibraryView() 挂载）
 * - data-testid="library-status-bar" + library-status-counts：库状态
 * - data-testid="library-scan-btn"：扫描按钮
 * - data-testid="library-playlist-sidebar" + library-playlist-row：歌单列表
 * - data-testid="library-search-input" + library-search-btn：搜索框
 * - data-testid="library-song-list" + library-song-row：歌曲列表
 * - data-testid="library-song-empty"：空态占位
 * - data-testid="library-error"：错误显示
 *
 * 注意：LibraryView 默认不挂载（App.tsx 不直接渲染），E2E 经
 * __omniDebug.mountLibraryView() 在测试中动态挂载。生产构建不可用。
 */
import { expect, type Page, type Locator } from "@playwright/test";

import { GLOBAL_KEYS } from "../support/env";

/** __omniDebug 全局对象 key（inline 供 page.evaluate 使用）。 */
const OMNI_DEBUG_KEY = GLOBAL_KEYS.OMNI_DEBUG;

/** LibraryView 根容器选择器。 */
export const LIBRARY_VIEW_SELECTOR = '[data-testid="library-view"]';
/** 库状态栏选择器。 */
export const LIBRARY_STATUS_BAR_SELECTOR = '[data-testid="library-status-bar"]';
/** 库状态计数选择器（"X 首 / Y 歌单"）。 */
export const LIBRARY_STATUS_COUNTS_SELECTOR = '[data-testid="library-status-counts"]';
/** 扫描按钮选择器。 */
export const LIBRARY_SCAN_BTN_SELECTOR = '[data-testid="library-scan-btn"]';
/** 歌单侧栏选择器。 */
export const LIBRARY_PLAYLIST_SIDEBAR_SELECTOR = '[data-testid="library-playlist-sidebar"]';
/** 歌单行选择器。 */
export const LIBRARY_PLAYLIST_ROW_SELECTOR = '[data-testid="library-playlist-row"]';
/** 搜索输入框选择器。 */
export const LIBRARY_SEARCH_INPUT_SELECTOR = '[data-testid="library-search-input"]';
/** 搜索按钮选择器。 */
export const LIBRARY_SEARCH_BTN_SELECTOR = '[data-testid="library-search-btn"]';
/** 歌曲面板选择器。 */
export const LIBRARY_SONG_PANEL_SELECTOR = '[data-testid="library-song-panel"]';
/** 歌曲列表选择器。 */
export const LIBRARY_SONG_LIST_SELECTOR = '[data-testid="library-song-list"]';
/** 歌曲行选择器。 */
export const LIBRARY_SONG_ROW_SELECTOR = '[data-testid="library-song-row"]';
/** 歌曲空态选择器。 */
export const LIBRARY_SONG_EMPTY_SELECTOR = '[data-testid="library-song-empty"]';
/** 错误显示选择器。 */
export const LIBRARY_ERROR_SELECTOR = '[data-testid="library-error"]';
/** 扫描摘要选择器。 */
export const LIBRARY_SCAN_SUMMARY_SELECTOR = '[data-testid="library-scan-summary"]';
/** 新歌单输入框选择器。 */
export const LIBRARY_NEW_PLAYLIST_INPUT_SELECTOR = '[data-testid="library-new-playlist-input"]';
/** 创建歌单按钮选择器。 */
export const LIBRARY_CREATE_PLAYLIST_BTN_SELECTOR = '[data-testid="library-create-playlist-btn"]';

export class LibraryViewPage {
  readonly page: Page;
  readonly root: Locator;
  readonly statusBar: Locator;
  readonly statusCounts: Locator;
  readonly scanBtn: Locator;
  readonly playlistSidebar: Locator;
  readonly playlistRows: Locator;
  readonly searchInput: Locator;
  readonly searchBtn: Locator;
  readonly songPanel: Locator;
  readonly songList: Locator;
  readonly songRows: Locator;
  readonly songEmpty: Locator;
  readonly error: Locator;
  readonly scanSummary: Locator;
  readonly newPlaylistInput: Locator;
  readonly createPlaylistBtn: Locator;

  constructor(page: Page) {
    this.page = page;
    this.root = page.locator(LIBRARY_VIEW_SELECTOR);
    this.statusBar = page.locator(LIBRARY_STATUS_BAR_SELECTOR);
    this.statusCounts = page.locator(LIBRARY_STATUS_COUNTS_SELECTOR);
    this.scanBtn = page.locator(LIBRARY_SCAN_BTN_SELECTOR);
    this.playlistSidebar = page.locator(LIBRARY_PLAYLIST_SIDEBAR_SELECTOR);
    this.playlistRows = page.locator(LIBRARY_PLAYLIST_ROW_SELECTOR);
    this.searchInput = page.locator(LIBRARY_SEARCH_INPUT_SELECTOR);
    this.searchBtn = page.locator(LIBRARY_SEARCH_BTN_SELECTOR);
    this.songPanel = page.locator(LIBRARY_SONG_PANEL_SELECTOR);
    this.songList = page.locator(LIBRARY_SONG_LIST_SELECTOR);
    this.songRows = page.locator(LIBRARY_SONG_ROW_SELECTOR);
    this.songEmpty = page.locator(LIBRARY_SONG_EMPTY_SELECTOR);
    this.error = page.locator(LIBRARY_ERROR_SELECTOR);
    this.scanSummary = page.locator(LIBRARY_SCAN_SUMMARY_SELECTOR);
    this.newPlaylistInput = page.locator(LIBRARY_NEW_PLAYLIST_INPUT_SELECTOR);
    this.createPlaylistBtn = page.locator(LIBRARY_CREATE_PLAYLIST_BTN_SELECTOR);
  }

  /**
   * 经 __omniDebug.mountLibraryView() 挂载 LibraryView 组件。
   *
   * LibraryView 默认不在 App.tsx 中渲染（仅 ShelfView 订阅 libraryStore.playlists）。
   * E2E 测试通过此 debug API 动态挂载组件，验证库浏览 UI。
   * 挂载后 LibraryView 的 useEffect 自动调 fetchStatus + fetchPlaylists。
   */
  async mount(): Promise<void> {
    await this.page.evaluate((key) => {
      const api = (window as unknown as Record<string, unknown>)[
        key
      ] as { mountLibraryView(): void } | undefined;
      api?.mountLibraryView();
    }, OMNI_DEBUG_KEY);
    await this.root.waitFor({ state: "attached", timeout: 5_000 });
  }

  /** 经 __omniDebug.unmountLibraryView() 卸载 LibraryView 组件。 */
  async unmount(): Promise<void> {
    await this.page.evaluate((key) => {
      const api = (window as unknown as Record<string, unknown>)[
        key
      ] as { unmountLibraryView(): void } | undefined;
      api?.unmountLibraryView();
    }, OMNI_DEBUG_KEY);
  }

  /** 读取库状态计数文案（"X 首 / Y 歌单" 或 "—"）。 */
  async getStatusCountsText(): Promise<string> {
    return (await this.statusCounts.textContent()) ?? "";
  }

  /** 等待库状态计数包含指定文案。 */
  async waitForStatusCountsContains(
    substring: string,
    timeout = 5_000,
  ): Promise<void> {
    await expect(this.statusCounts).toContainText(substring, { timeout });
  }

  /** 点击扫描按钮触发 scanLibrary。 */
  async clickScan(): Promise<void> {
    await this.scanBtn.click();
  }

  /** 在搜索框输入关键词。 */
  async fillSearchQuery(query: string): Promise<void> {
    await this.searchInput.fill(query);
  }

  /** 点击搜索按钮触发 searchLibrary。 */
  async clickSearch(): Promise<void> {
    await this.searchBtn.click();
  }

  /** 在搜索框输入并回车触发搜索。 */
  async searchByEnter(query: string): Promise<void> {
    await this.searchInput.fill(query);
    await this.searchInput.press("Enter");
  }

  /** 等待歌曲列表挂载且 song-count 属性等于目标值。 */
  async waitForSongCount(count: number, timeout = 5_000): Promise<void> {
    await expect.poll(async () => await this.getSongCount(), { timeout }).toBe(count);
  }

  /** 等待歌曲列表挂载且 song-count 属性大于等于目标值。 */
  async waitForSongCountAtLeast(count: number, timeout = 5_000): Promise<void> {
    await expect.poll(async () => await this.getSongCount(), { timeout }).toBeGreaterThanOrEqual(count);
  }

  /** 读取歌曲列表 data-song-count 属性。 */
  async getSongCount(): Promise<number> {
    const attr = await this.songList.getAttribute("data-song-count");
    if (attr === null) return 0;
    const n = Number(attr);
    return Number.isFinite(n) ? n : 0;
  }

  /** 读取歌曲面板的 data-mode 属性（search / playlist / empty）。 */
  async getSongPanelMode(): Promise<string | null> {
    return await this.songPanel.getAttribute("data-mode");
  }

  /** 等待歌曲面板 data-mode 等于目标值。 */
  async waitForSongPanelMode(mode: string, timeout = 5_000): Promise<void> {
    await expect(this.songPanel).toHaveAttribute("data-mode", mode, { timeout });
  }

  /** 等待空态占位可见。 */
  async waitForEmpty(timeout = 5_000): Promise<void> {
    await this.songEmpty.waitFor({ state: "visible", timeout });
  }

  /** 等待错误显示包含指定文案。 */
  async waitForErrorContains(substring: string, timeout = 5_000): Promise<void> {
    await expect(this.error).toContainText(substring, { timeout });
  }

  /** 等待错误元素消失（无错误）。 */
  async waitForNoError(timeout = 5_000): Promise<void> {
    await this.error.waitFor({ state: "detached", timeout });
  }

  /** 读取歌单行数量。 */
  async getPlaylistRowCount(): Promise<number> {
    return await this.playlistRows.count();
  }

  /** 等待歌单行数量等于目标值。 */
  async waitForPlaylistRowCount(count: number, timeout = 5_000): Promise<void> {
    await expect.poll(async () => await this.getPlaylistRowCount(), { timeout }).toBe(count);
  }

  /** 点击指定 index 的歌单行（选中歌单）。 */
  async clickPlaylistRow(index: number): Promise<void> {
    await this.playlistRows.nth(index).click();
  }

  /** 读取指定 index 歌单行的 data-playlist-id 属性。 */
  async getPlaylistId(index: number): Promise<string | null> {
    return await this.playlistRows.nth(index).getAttribute("data-playlist-id");
  }

  /** 读取指定 index 歌单行的 textContent（歌单名 + 曲数）。 */
  async getPlaylistRowText(index: number): Promise<string> {
    return (await this.playlistRows.nth(index).textContent()) ?? "";
  }

  /** 在新歌单输入框输入名称并回车创建。 */
  async createPlaylistByEnter(name: string): Promise<void> {
    await this.newPlaylistInput.fill(name);
    await this.newPlaylistInput.press("Enter");
  }

  /** 在新歌单输入框输入名称并点击创建按钮。 */
  async createPlaylistByClick(name: string): Promise<void> {
    await this.newPlaylistInput.fill(name);
    await this.createPlaylistBtn.click();
  }

  /** 读取扫描摘要文案（"扫描 X / 新增 Y / 更新 Z"）。 */
  async getScanSummaryText(): Promise<string> {
    return (await this.scanSummary.textContent()) ?? "";
  }

  /** 等待扫描摘要可见且包含指定文案。 */
  async waitForScanSummaryContains(substring: string, timeout = 5_000): Promise<void> {
    await expect(this.scanSummary).toContainText(substring, { timeout });
  }
}
