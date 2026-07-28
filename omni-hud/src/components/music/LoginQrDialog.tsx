/**
 * LoginQrDialog 扫码登录二维码弹窗（M17.10）。
 *
 * 4 种 loginStatus 对应文案：
 * - waiting：「请用手机扫码」+ 二维码图；
 * - scanned：「已扫描，请在手机确认」；
 * - confirmed：「登录成功」+ 自动关闭提示；
 * - expired：「二维码过期，请重新获取」+ 重新获取按钮。
 *
 * 暗房风格半透明遮罩 + 居中卡片；关闭按钮（X）经 Icon.tsx。
 * 订阅 musicStore.loginQr / loginStatus；「重新获取」调 store.startLogin()
 * 重新发起；关闭按钮调 store.stopLoginPolling() + onClose 回调。
 *
 * 图标全经 Icon.tsx（CLAUDE.md §五）；无 emoji；Film Atelier 暗房风（§六）。
 */
import { useSyncExternalStore } from "react";

import type { LoginStatus, MusicStore } from "../../store/musicStore";
import { Icon } from "../ui/Icon";

export interface LoginQrDialogProps {
  store: MusicStore;
  /** 关闭回调（卸载弹窗）；组件内部先 stopLoginPolling 再调用。 */
  onClose: () => void;
}

/** loginStatus → 中文提示文案。 */
const STATUS_TEXT: Record<LoginStatus, string> = {
  idle: "准备中",
  waiting: "请用手机扫码",
  scanned: "已扫描，请在手机确认",
  confirmed: "登录成功",
  expired: "二维码过期，请重新获取",
};

/** loginStatus → 强调色（暗房安全灯系：waiting 琥珀 / scanned 蓝 / confirmed 绿 / expired 红）。 */
const STATUS_COLOR: Record<LoginStatus, string> = {
  idle: "var(--omni-dim)",
  waiting: "var(--omni-accent)",
  scanned: "#5b8def",
  confirmed: "#6fb58a",
  expired: "#b04a3a",
};

export function LoginQrDialog({ store, onClose }: LoginQrDialogProps): JSX.Element {
  const state = useSyncExternalStore(store.subscribe, store.getState);
  const { loginQr, loginStatus } = state;

  const handleClose = (): void => {
    store.stopLoginPolling();
    onClose();
  };

  const handleRefresh = (): void => {
    void store.startLogin();
  };

  return (
    <div
      data-testid="login-qr-dialog"
      data-login-status={loginStatus}
      role="dialog"
      aria-modal="true"
      aria-label="音乐源扫码登录"
      onClick={handleClose}
      style={{
        position: "fixed",
        inset: 0,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "rgba(11, 12, 14, 0.72)",
        backdropFilter: "blur(6px)",
        WebkitBackdropFilter: "blur(6px)",
        zIndex: 50,
        // 入场淡入：克制 200ms
        animation: "login-qr-fade-in 200ms ease-out",
      }}
    >
      <div
        data-testid="login-qr-card"
        onClick={(e) => e.stopPropagation()}
        style={{
          position: "relative",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          gap: "16px",
          padding: "28px 32px 24px",
          width: "300px",
          maxWidth: "90vw",
          background: "var(--omni-panel)",
          borderRadius: "var(--omni-radius)",
          border: "1px solid var(--omni-hairline)",
          color: "var(--omni-fog)",
          pointerEvents: "auto",
        }}
      >
        {/* 关闭按钮 */}
        <button
          type="button"
          data-testid="login-qr-close"
          onClick={handleClose}
          aria-label="关闭"
          style={{
            position: "absolute",
            top: "10px",
            right: "10px",
            display: "inline-flex",
            alignItems: "center",
            justifyContent: "center",
            width: "26px",
            height: "26px",
            borderRadius: "50%",
            border: "1px solid transparent",
            background: "transparent",
            color: "var(--omni-dim)",
            cursor: "pointer",
            transition: "color 200ms ease-out",
            padding: 0,
          }}
        >
          <Icon name="x" size={14} label="关闭" />
        </button>

        {/* 标题 */}
        <span
          style={{
            fontFamily: "ui-monospace, 'SF Mono', Menlo, Consolas, monospace",
            fontSize: "11px",
            letterSpacing: "0.14em",
            color: "var(--omni-dim)",
            textTransform: "uppercase",
          }}
        >
          扫码登录
        </span>

        {/* 二维码区域 */}
        <div
          data-testid="login-qr-image-wrap"
          style={{
            width: "200px",
            height: "200px",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            background: "var(--omni-abyss)",
            borderRadius: "8px",
            border: "1px solid var(--omni-hairline)",
            // expired / confirmed 时降亮度
            opacity: loginStatus === "expired" || loginStatus === "confirmed" ? 0.4 : 1,
            transition: "opacity 240ms ease-out",
          }}
        >
          {loginQr?.qr_url ? (
            <img
              data-testid="login-qr-image"
              src={loginQr.qr_url}
              alt="登录二维码"
              style={{ width: "180px", height: "180px", objectFit: "contain" }}
            />
          ) : (
            <Icon name="music" size={40} color="var(--omni-dim)" label="二维码加载中" />
          )}
        </div>

        {/* 状态文案 */}
        <span
          data-testid="login-qr-status"
          style={{
            fontSize: "13px",
            color: STATUS_COLOR[loginStatus],
            textAlign: "center",
            transition: "color 240ms ease-out",
          }}
        >
          {STATUS_TEXT[loginStatus]}
        </span>

        {/* 来源标签 */}
        {loginQr?.source ? (
          <span
            data-testid="login-qr-source"
            style={{
              fontSize: "10px",
              color: "var(--omni-dim)",
              fontFamily: "ui-monospace, 'SF Mono', Menlo, Consolas, monospace",
              letterSpacing: "0.08em",
            }}
          >
            {loginQr.source}
          </span>
        ) : null}

        {/* expired 时显示重新获取按钮 */}
        {loginStatus === "expired" ? (
          <button
            type="button"
            data-testid="login-qr-refresh"
            onClick={handleRefresh}
            aria-label="重新获取二维码"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: "6px",
              padding: "6px 16px",
              borderRadius: "var(--omni-radius)",
              border: "1px solid var(--omni-accent)",
              background: "transparent",
              color: "var(--omni-accent)",
              cursor: "pointer",
              fontSize: "12px",
              transition: "background-color 200ms ease-out",
            }}
          >
            <Icon name="repeat" size={12} label="重新获取" />
            重新获取
          </button>
        ) : null}
      </div>
    </div>
  );
}
