// 分时段文案（TextSchedule）在前端的处理——**全链路只有一种格式**（v0.5.2）
//
// 服务端只认结构化对象：`{periods: [{start, end, items: [{text, weight}]}]}`
// （`worlditor_mcp/world/model.py` 的 `parse_text_schedule`；纯字符串直接报错）。
// 所以编辑框里**永远是这份 JSON**，不给"纯文本"第二条路：
// 同一份数据两种写法，必然导致"读进来是文本、存回去结构变了"这类静默丢失
// （G24 / G28 的根因），也让差异预览无法如实比对。
//
// 前端只做"是不是 JSON 对象"这一层检查，字段级校验归服务端（唯一权威）——
// 错误消息原样透出给用户。

/** 标准结构示例（占位符与错误提示都用它）。 */
export const SCHEDULE_HINT =
  '{ "periods": [ { "start": "00:00", "end": "24:00", "items": [ { "text": "文本", "weight": 1 } ] } ] }';

/** 服务端值 → 编辑框文本：一律输出结构化 JSON（历史纯文本也归一成标准结构）。 */
export function scheduleToJson(value) {
  if (value === null || value === undefined || value === "") return "";
  if (typeof value === "string") {
    // 历史形态（纯文本 = 全天单条）：只在**显示**时归一，写入路径不接受纯文本
    return JSON.stringify(
      {
        periods: [
          { start: "00:00", end: "24:00", items: [{ text: value, weight: 1 }] },
        ],
      },
      null,
      2
    );
  }
  return JSON.stringify(value, null, 2);
}

/**
 * 编辑框文本 → 提交值。
 *
 * 空 = 清除（null）；否则必须是 JSON **对象**。返回 `{ok, value}` 或
 * `{ok: false, error}`（调用方把 error 显示出来并**不要提交**）。
 */
export function parseScheduleText(text) {
  const raw = (text || "").trim();
  if (!raw) return { ok: true, value: null };
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (e) {
    return { ok: false, error: `不是合法 JSON：${e.message}` };
  }
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    return { ok: false, error: `文案必须是结构化对象，例：${SCHEDULE_HINT}` };
  }
  return { ok: true, value: parsed };
}
