// 保存前差异预览（v0.5 / D23）。
//
// 为什么需要它：G24 的教训——管理端连接编辑器曾把跨图目标、路径权重、路径文案
// **静默**改坏（打开→保存就丢），lint 也抓不到（损坏后的目标地块存在）。
// 凡是"整对象替换"的写操作，都必须让管理员**先看见旧值→新值**再落盘。
//
// 与 confirm.js 同一套路：全局单例 + Promise API，宿主组件挂在 App.vue。
import { reactive } from "vue";

export const diffState = reactive({
  open: false,
  title: "",
  detail: "",
  changes: [], // [{ label, before, after }]
  confirmText: "确认保存",
  _resolve: null,
});

/** 把"变更清单"渲染成可读文本值。 */
export function showValue(value) {
  if (value === undefined) return "（无）";
  if (value === null) return "null";
  if (typeof value === "string") return value === "" ? "（空）" : value;
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/**
 * 计算扁平字段差异：只列**变了的**键。
 * @param {object} before 旧对象
 * @param {object} after  新对象
 * @param {object} labels 键 → 中文标签（可选）
 */
export function diffFields(before, after, labels = {}) {
  const keys = new Set([...Object.keys(before || {}), ...Object.keys(after || {})]);
  const out = [];
  for (const key of keys) {
    const b = before ? before[key] : undefined;
    const a = after ? after[key] : undefined;
    if (JSON.stringify(b) === JSON.stringify(a)) continue;
    out.push({ label: labels[key] || key, before: b, after: a });
  }
  return out;
}

/**
 * 弹出差异预览；resolve 为 true（确认保存）或 false（取消）。
 * `changes` 为空数组时直接返回 true（没有变化就不打扰用户）。
 */
export function askDiff({ title, detail = "", changes, confirmText = "确认保存" }) {
  if (!changes || !changes.length) return Promise.resolve(true);
  if (diffState._resolve) diffState._resolve(false);
  diffState.open = true;
  diffState.title = title || "保存前确认";
  diffState.detail = detail;
  diffState.changes = changes;
  diffState.confirmText = confirmText;
  return new Promise((resolve) => {
    diffState._resolve = resolve;
  });
}

export function settleDiff(ok) {
  const resolve = diffState._resolve;
  diffState._resolve = null;
  diffState.open = false;
  if (resolve) resolve(Boolean(ok));
}
