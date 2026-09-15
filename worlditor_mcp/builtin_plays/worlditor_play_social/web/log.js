// worlditor_play_social 世界日志视图。
// 视图组件协议（G3/D7）：new Function("Vue", "UiBlock", code) 动态加载。
// 数据通道：MCP tools/call（world_log 工具）。

(function (Vue, UiBlock) {
  "use strict";
  const { ref, onMounted, h } = Vue;

  const TOKEN_KEY = "worlditor_token";

  // MCP streamable HTTP 会话（视图组件无法 import SDK，内嵌轻量实现）
  let _sessionId = "";

  async function ensureSession() {
    if (_sessionId) return;
    const resp = await fetch("/world/mcp", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-06-18",
        Authorization: "Bearer " + (localStorage.getItem(TOKEN_KEY) || ""),
      },
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: 0,
        method: "initialize",
        params: {
          protocolVersion: "2025-06-18",
          capabilities: {},
          clientInfo: { name: "worlditor-webui", version: "0.1.0" },
        },
      }),
    });
    if (!resp.ok) throw new Error("MCP 初始化失败：HTTP " + resp.status);
    _sessionId = resp.headers.get("Mcp-Session-Id") || "";
    if (!_sessionId) throw new Error("MCP 初始化失败：未取得会话");
  }

  async function callTool(name, args) {
    await ensureSession();
    const resp = await fetch("/world/mcp", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json, text/event-stream",
        "MCP-Protocol-Version": "2025-06-18",
        Authorization: "Bearer " + (localStorage.getItem(TOKEN_KEY) || ""),
        "Mcp-Session-Id": _sessionId,
      },
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: 1,
        method: "tools/call",
        params: { name: name, arguments: args || {} },
      }),
    });
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    const text = await resp.text();
    let data = null;
    if (text.trimStart().startsWith("event:")) {
      const m = text.match(/data: (.*)/s);
      data = m ? JSON.parse(m[1]) : null;
    } else {
      data = text ? JSON.parse(text) : null;
    }
    if (data && data.error) throw new Error(data.error.message || "MCP 调用失败");
    const content = data && data.result && data.result.content && data.result.content[0];
    if (!content || !content.text) return {};
    try {
      return JSON.parse(content.text);
    } catch (e) {
      return { text: content.text };
    }
  }

  // 常见事件的中文标签（未命中的事件名原样显示）
  const KIND_LABEL = {
    on_world_edited: "🌍 世界编辑",
    on_entity_changed: "🧬 实体变更",
    on_entity_spawned: "✨ 实体出现",
    on_entity_removed: "💨 实体离开",
    on_item_gained: "🎁 获得物品",
    on_item_used: "🍎 使用物品",
  };

  function clip(v) {
    const s = String(v);
    return s.length > 18 ? s.slice(0, 18) + "…" : s;
  }

  // 事件摘要：挑关键字段；变更类事件的明细在数组里（dicts/ops），取首条。
  // 完整 JSON 折叠进"详情"，避免整坨糊在列表里。
  function brief(data, depth) {
    if (!data || typeof data !== "object") {
      return data === undefined || data === null ? "" : clip(data);
    }
    const keys = [
      "text",
      "message",
      "label",
      "name",
      "title",
      "op",
      "action",
      "item_id",
      "entity_id",
      "map_id",
    ];
    const parts = [];
    for (const k of keys) {
      const v = data[k];
      if (v === undefined || v === null || v === "") continue;
      parts.push(k + "=" + clip(v));
      if (parts.length >= 3) break;
    }
    if (parts.length) return parts.join(" · ");
    if ((depth || 0) < 2) {
      for (const k of ["dicts", "ops", "changes", "items", "entries"]) {
        const arr = data[k];
        if (Array.isArray(arr) && arr.length && typeof arr[0] === "object") {
          const inner = brief(arr[0], (depth || 0) + 1);
          if (inner) return k + "[" + arr.length + "] " + inner;
        }
      }
    }
    return "";
  }

  function fmtEntry(entry) {
    const data = entry.data || {};
    const ts = new Date((entry.ts || 0) * 1000).toLocaleTimeString();
    if (entry.kind === "say" || entry.kind === "broadcast") {
      const label = entry.kind === "say" ? "💬" : "📢";
      return h(
        "div",
        { class: "wt-li" },
        ts + " " + label + " " + (data.name || "?") + "：" + (data.text || "")
      );
    }
    const summary = brief(data);
    const raw = JSON.stringify(data);
    return h("div", { class: "wt-li" }, [
      h("div", {}, ts + " " + (KIND_LABEL[entry.kind] || entry.kind) + (summary ? " · " + summary : "")),
      raw && raw !== "{}"
        ? h("details", { class: "wt-detail" }, [
            h("summary", {}, "详情"),
            h("pre", { class: "wt-json" }, raw),
          ])
        : null,
    ]);
  }

  return {
    name: "LogView",
    props: { view: { type: Object, required: true } },
    setup() {
      const entries = ref([]);
      const error = ref("");

      async function refresh() {
        try {
          const result = await callTool("world_log", { limit: 50 });
          entries.value = Array.isArray(result.entries) ? result.entries : [];
          error.value = "";
        } catch (e) {
          error.value = e.message;
        }
      }

      onMounted(refresh);

      return () => {
        const rows = entries.value.map((e) => fmtEntry(e));
        return h("div", {}, [
          h("div", { class: "wt-head" }, [
            h("span", { class: "wt-title" }, "世界日志"),
            h("button", { class: "wt-btn", onClick: () => refresh() }, "刷新"),
          ]),
          entries.value.length
            ? h("div", { class: "wt-list" }, rows)
            : h(
                "div",
                { class: "wt-dim" },
                error.value ? "⚠ " + error.value : "还没有日志。"
              ),
        ]);
      };
    },
  };
});
