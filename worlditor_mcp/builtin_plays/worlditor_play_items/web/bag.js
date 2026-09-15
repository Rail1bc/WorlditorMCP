// worlditor_play_items 背包视图。
// 视图组件协议（G3/D7）：new Function("Vue", "UiBlock", code) 动态加载——
// 本文件即该函数体：返回 Vue 组件选项对象。
// 数据通道：MCP tools/call（动作统一走 MCP，B10）。

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
    name: "BagView",
    props: { view: { type: Object, required: true } },
    setup() {
      const slots = ref([]); // {item_id, name, count}
      const capacity = ref(20);
      const used = ref(0);
      const error = ref("");
      const busy = ref(false);

      async function refresh() {
        try {
          const bag = await callTool("world_bag", {});
          slots.value = Array.isArray(bag.slots) ? bag.slots : [];
          capacity.value = bag.capacity || 20;
          used.value = bag.used || 0;
          error.value = "";
        } catch (e) {
          error.value = e.message;
        }
      }

      async function useItem(itemId) {
        if (busy.value) return;
        busy.value = true;
        error.value = "";
        try {
          await callTool("world_use", { item_id: itemId });
          await refresh();
        } catch (e) {
          error.value = e.message;
        } finally {
          busy.value = false;
        }
      }

      onMounted(refresh);

      return () => {
        const cells = [];
        for (let i = 0; i < capacity.value; i++) {
          const slot = slots.value[i];
          if (!slot) {
            cells.push(h("div", { class: "wt-cell empty" }, "空"));
            continue;
          }
          cells.push(
            h("div", { class: "wt-cell" }, [
              h("div", { class: "wt-strong" }, slot.name + " ×" + slot.count),
              h(
                "button",
                { class: "wt-btn", onClick: () => useItem(slot.item_id) },
                "使用"
              ),
            ])
          );
        }
        return h("div", {}, [
          h("div", { class: "wt-head" }, [
            h(
              "span",
              { class: "wt-title" },
              "背包（" + used.value + "/" + capacity.value + "）"
            ),
            h(
              "button",
              { class: "wt-btn", onClick: () => refresh(), disabled: busy.value },
              "刷新"
            ),
          ]),
          h("div", { class: "wt-grid wt-cols-4" }, cells),
          error.value ? h("div", { class: "wt-err" }, "⚠ " + error.value) : null,
        ]);
      };
    },
  };
});
