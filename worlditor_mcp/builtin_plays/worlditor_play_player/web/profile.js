// worlditor_play_player 角色视图——玩家聚合界面。
// 视图组件协议（G3/D7）：new Function("Vue", "UiBlock", code) 动态加载。
// 数据通道：MCP tools/call（world_profile）——返回 {text, ui}：
//   ui = 角色卡（character）+ 其他包 ui_hook 注入的部件面板（如 items 背包面板）。
// 软依赖：背包面板由 items 包 hook 注入——items 未装时 ui 仅角色卡。

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

  return {
    name: "PlayerView",
    props: { view: { type: Object, required: true } },
    setup() {
      const ui = ref(null);
      const error = ref("");

      async function refresh() {
        try {
          const profile = await callTool("world_profile", {});
          ui.value = profile.ui || null;
          error.value = "";
        } catch (e) {
          error.value = e.message;
        }
      }

      onMounted(refresh);

      return () => {
        if (!ui.value) {
          return h(
            "div",
            { style: { fontFamily: "system-ui, sans-serif", color: "var(--text-dim)" } },
            error.value ? "⚠ " + error.value : "加载中……"
          );
        }
        // 聚合渲染：角色卡 + 注入的部件面板（背包等），UiBlockRenderer 递归
        return h(
          "div",
          { style: { fontFamily: "system-ui, sans-serif", maxWidth: 560 } },
          [
            h(UiBlock, { block: ui.value, onAction: () => refresh() }),
            h(
              "button",
              { onClick: () => refresh(), style: { marginTop: 12 } },
              "刷新"
            ),
          ]
        );
      };
    },
  };
});
