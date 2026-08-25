// worlditor_play_social 世界日志视图。
// 视图组件协议（G3/D7）：new Function("Vue", "UiBlock", code) 动态加载。
// 数据通道：MCP tools/call（world_log 工具）。

(function (Vue, UiBlock) {
  "use strict";
  const { ref, onMounted, h } = Vue;

  const TOKEN_KEY = "worlditor_token";

  async function callTool(name, args) {
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

  function fmtEntry(entry) {
    const data = entry.data || {};
    const ts = new Date((entry.ts || 0) * 1000).toLocaleTimeString();
    if (entry.kind === "say" || entry.kind === "broadcast") {
      const label = entry.kind === "say" ? "💬" : "📢";
      return ts + " " + label + " " + (data.name || "?") + "：" + (data.text || "");
    }
    return ts + " [" + entry.kind + "] " + JSON.stringify(data);
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
        const rows = entries.value.map((e) =>
          h(
            "div",
            {
              style: {
                padding: "6px 0",
                borderBottom: "1px solid #eee",
                fontSize: 13,
              },
            },
            fmtEntry(e)
          )
        );
        return h(
          "div",
          { style: { fontFamily: "system-ui, sans-serif", maxWidth: 480 } },
          [
            h(
              "div",
              {
                style: {
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  marginBottom: 8,
                },
              },
              [
                h("span", { style: { fontWeight: 600 } }, "世界日志"),
                h("button", { onClick: () => refresh() }, "刷新"),
              ]
            ),
            entries.value.length
              ? rows
              : h(
                  "div",
                  { style: { color: "#888" } },
                  error.value ? "⚠ " + error.value : "还没有日志。"
                ),
          ]
        );
      };
    },
  };
});
