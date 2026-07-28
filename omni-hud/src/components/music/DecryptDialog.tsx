/**
 * DecryptDialog 加密音频解密弹窗（M19，D19.1 合规）。
 *
 * 解密加密音频文件（.qmc/.qmcflac/.mflac/.mgg）为标准格式。
 *
 * **D19.1 合规约束**：
 * - 仅用于已合法购买内容的格式转换，不提供破解付费内容能力
 * - 用户必须勾选「确认已合法购买」安全门才能执行解密
 * - 解密模块只处理用户已合法拥有的加密文件
 *
 * 三种状态：
 * - idle    ：待输入（默认）
 * - success ：解密成功，显示输出路径 + 合规声明
 * - error   ：解密失败，显示错误信息 + 重试按钮
 *
 * 暗房风格半透明遮罩 + 居中卡片；图标经 Icon.tsx（§五）；无 emoji。
 * 订阅 libraryStore.lastDecryptResult / error / isLoading。
 */
import { useCallback, useState, useSyncExternalStore } from "react";

import type { LibraryStore } from "../../store/libraryStore";
import { Icon } from "../ui/Icon";

export interface DecryptDialogProps {
  store: LibraryStore;
  /** 关闭回调（卸载弹窗）。 */
  onClose: () => void;
}

export function DecryptDialog({ store, onClose }: DecryptDialogProps): JSX.Element {
  const state = useSyncExternalStore(store.subscribe, store.getState);
  const [path, setPath] = useState("");
  const [outputPath, setOutputPath] = useState("");
  const [confirmed, setConfirmed] = useState(false);

  const isLoading = state.isLoading;
  const error = state.error;
  const result = state.lastDecryptResult;

  const handleDecrypt = useCallback((): void => {
    if (!path.trim() || !confirmed) return;
    void store.decryptFile(path.trim(), outputPath.trim() || undefined, true);
  }, [store, path, outputPath, confirmed]);

  const handleClose = useCallback((): void => {
    store.clearError();
    onClose();
  }, [store, onClose]);

  const canDecrypt = path.trim() !== "" && confirmed && !isLoading;

  return (
    <div
      data-testid="decrypt-dialog"
      data-state={result ? "success" : error ? "error" : "idle"}
      role="dialog"
      aria-modal="true"
      aria-label="加密音频解密"
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
        animation: "login-qr-fade-in 200ms ease-out",
      }}
    >
      <div
        data-testid="decrypt-dialog-card"
        onClick={(e) => e.stopPropagation()}
        style={{
          position: "relative",
          display: "flex",
          flexDirection: "column",
          gap: "14px",
          padding: "24px 28px 20px",
          width: "420px",
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
          data-testid="decrypt-close"
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
        <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
          <Icon name="music" size={16} color="var(--omni-accent)" />
          <span
            style={{
              fontFamily: "ui-monospace, 'SF Mono', Menlo, Consolas, monospace",
              fontSize: "11px",
              letterSpacing: "0.14em",
              color: "var(--omni-dim)",
              textTransform: "uppercase",
            }}
          >
            加密音频解密
          </span>
        </div>

        {/* 合规警告条 */}
        <div
          data-testid="decrypt-compliance-notice"
          style={{
            display: "flex",
            gap: "8px",
            padding: "8px 10px",
            background: "rgba(176, 74, 58, 0.08)",
            border: "1px solid rgba(176, 74, 58, 0.2)",
            borderRadius: "4px",
            fontSize: "10px",
            color: "#b04a3a",
            lineHeight: 1.5,
          }}
        >
          <Icon name="music2" size={10} color="#b04a3a" />
          <span>
            D19.1 合规约束：仅用于已合法购买内容的格式转换，不提供破解付费内容能力。
            请确保你已合法购买该音频内容。
          </span>
        </div>

        {/* 成功状态：显示结果 */}
        {result ? (
          <div
            data-testid="decrypt-success"
            style={{
              display: "flex",
              flexDirection: "column",
              gap: "8px",
              padding: "12px",
              background: "rgba(111, 181, 138, 0.08)",
              border: "1px solid rgba(111, 181, 138, 0.2)",
              borderRadius: "4px",
            }}
          >
            <span style={{ fontSize: "12px", color: "#6fb58a" }}>解密成功</span>
            <div style={{ fontSize: "10px", color: "var(--omni-dim)", lineHeight: 1.6 }}>
              <div>源文件：{result.source_path}</div>
              <div>输出文件：{result.output_path}</div>
            </div>
            <span style={{ fontSize: "9px", color: "var(--omni-dim)", marginTop: "4px" }}>
              {result.notice}
            </span>
          </div>
        ) : (
          <>
            {/* 文件路径输入 */}
            <label
              style={{
                display: "flex",
                flexDirection: "column",
                gap: "4px",
                fontSize: "10px",
                color: "var(--omni-dim)",
              }}
            >
              <span>加密源文件路径</span>
              <input
                data-testid="decrypt-path-input"
                type="text"
                value={path}
                onChange={(e) => setPath(e.target.value)}
                placeholder="/path/to/song.qmc0"
                aria-label="加密源文件路径"
                style={{
                  padding: "6px 8px",
                  fontSize: "12px",
                  background: "var(--omni-abyss)",
                  color: "var(--omni-fog)",
                  border: "1px solid var(--omni-hairline)",
                  borderRadius: "4px",
                  outline: "none",
                  fontFamily: "ui-monospace, 'SF Mono', Menlo, Consolas, monospace",
                }}
              />
            </label>

            {/* 输出路径输入（可选） */}
            <label
              style={{
                display: "flex",
                flexDirection: "column",
                gap: "4px",
                fontSize: "10px",
                color: "var(--omni-dim)",
              }}
            >
              <span>输出路径（可选，缺省同目录）</span>
              <input
                data-testid="decrypt-output-input"
                type="text"
                value={outputPath}
                onChange={(e) => setOutputPath(e.target.value)}
                placeholder="/path/to/output.mp3"
                aria-label="输出路径"
                style={{
                  padding: "6px 8px",
                  fontSize: "12px",
                  background: "var(--omni-abyss)",
                  color: "var(--omni-fog)",
                  border: "1px solid var(--omni-hairline)",
                  borderRadius: "4px",
                  outline: "none",
                  fontFamily: "ui-monospace, 'SF Mono', Menlo, Consolas, monospace",
                }}
              />
            </label>

            {/* 确认安全门 */}
            <label
              data-testid="decrypt-confirm-label"
              style={{
                display: "flex",
                alignItems: "flex-start",
                gap: "8px",
                padding: "8px 10px",
                background: "var(--omni-abyss)",
                borderRadius: "4px",
                border: confirmed ? "1px solid var(--omni-accent)" : "1px solid var(--omni-hairline)",
                cursor: "pointer",
                transition: "border-color 200ms ease-out",
              }}
            >
              <input
                data-testid="decrypt-confirm-checkbox"
                type="checkbox"
                checked={confirmed}
                onChange={(e) => setConfirmed(e.target.checked)}
                style={{ marginTop: "2px", cursor: "pointer" }}
              />
              <span style={{ fontSize: "11px", color: "var(--omni-fog)", lineHeight: 1.5 }}>
                我确认已合法购买该音频内容，解密仅作本地备份格式转换用途
              </span>
            </label>

            {/* 错误提示 */}
            {error ? (
              <div
                data-testid="decrypt-error"
                style={{
                  fontSize: "11px",
                  color: "#b04a3a",
                  padding: "6px 10px",
                  background: "rgba(176, 74, 58, 0.08)",
                  borderRadius: "4px",
                }}
              >
                {error}
              </div>
            ) : null}

            {/* 解密按钮 */}
            <button
              type="button"
              data-testid="decrypt-submit-btn"
              onClick={handleDecrypt}
              disabled={!canDecrypt}
              aria-label="执行解密"
              style={{
                display: "inline-flex",
                alignItems: "center",
                justifyContent: "center",
                gap: "6px",
                padding: "8px 16px",
                borderRadius: "var(--omni-radius)",
                border: "1px solid var(--omni-accent)",
                background: canDecrypt ? "var(--omni-accent)" : "transparent",
                color: canDecrypt ? "var(--omni-abyss)" : "var(--omni-dim)",
                cursor: canDecrypt ? "pointer" : "not-allowed",
                fontSize: "12px",
                opacity: isLoading ? 0.6 : 1,
                transition: "background-color 200ms ease-out, color 200ms ease-out",
              }}
            >
              <Icon name="music2" size={12} label="解密" />
              {isLoading ? "解密中..." : "解密"}
            </button>
          </>
        )}
      </div>
    </div>
  );
}
