// 统一确认弹层（v0.4.0：替代原生 confirm）。
//
// 为什么不用原生弹窗：管理端可能被嵌进 iframe / 沙箱环境，原生 confirm 会被
// 浏览器直接屏蔽（返回 undefined，删除操作静默失效）；而且原生弹窗样式与
// 管理台完全脱节。这里做成全局单例 Promise API，页面里 `if (!(await askConfirm(...))) return;`
// 就是原生 confirm 的等价写法。
import { reactive } from "vue";

export const confirmState = reactive({
  open: false,
  title: "",
  text: "",
  detail: "",
  danger: false,
  confirmText: "确定",
  cancelText: "取消",
  _resolve: null,
});

/**
 * 弹出确认层，resolve 为 true（确认）或 false（取消）。
 * 后一次调用会让上一次未决的确认直接作废（避免弹层堆叠）。
 */
export function askConfirm(opts = {}) {
  if (confirmState._resolve) confirmState._resolve(false);
  confirmState.open = true;
  confirmState.title = opts.title || "确认操作";
  confirmState.text = opts.text || "";
  confirmState.detail = opts.detail || "";
  confirmState.danger = Boolean(opts.danger);
  confirmState.confirmText = opts.confirmText || (opts.danger ? "删除" : "确定");
  confirmState.cancelText = opts.cancelText || "取消";
  return new Promise((resolve) => {
    confirmState._resolve = resolve;
  });
}

export function settleConfirm(ok) {
  const resolve = confirmState._resolve;
  confirmState._resolve = null;
  confirmState.open = false;
  if (resolve) resolve(Boolean(ok));
}
