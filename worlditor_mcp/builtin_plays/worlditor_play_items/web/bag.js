// worlditor_play_items 背包视图。
// 视图组件协议（G3/D7）：new Function("Vue", "UiBlock", code) 动态加载——
// 本文件即该函数体：返回 Vue 组件选项对象。
// 数据通道：MCP tools/call（与 mcpc.js 同协议，动作统一走 MCP）。

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
        const cellStyle = {
          border: "1px solid #ddd",
          borderRadius: 6,
          padding: 8,
          minHeight: 64,
          background: "#ffffff",
          fontSize: 13,
          display: "flex",
          flexDirection: "column",
          gap: 4,
        };
        const cells = [];
        for (let i = 0; i < capacity.value; i++) {
          const slot = slots.value[i];
          if (!slot) {
            cells.push(
              h(
                "div",
                { style: { ...cellStyle, background: "#f7f7f7", borderStyle: "dashed" } },
                h("span", { style: { color: "#bbb" } }, "空")
              )
            );
            continue;
          }
          cells.push(
            h("div", { style: cellStyle }, [
              h(
                "div",
                { style: { fontWeight: 600 } },
                slot.name + " ×" + slot.count
              ),
              h(
                "button",
                {
                  onClick: () => useItem(slot.item_id),
                  style: { fontSize: 12, padding: "2px 8px" },
                },
                "使用"
              ),
            ])
          );
        }
        return h(
          "div",
          { style: { fontFamily: "system-ui, sans-serif", maxWidth: 560 } },
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
                h(
                  "span",
                  { style: { fontWeight: 600 } },
                  "背包（" + used.value + "/" + capacity.value + "）"
                ),
                h(
                  "button",
                  { onClick: () => refresh(), disabled: busy.value },
                  "刷新"
                ),
              ]
            ),
            h(
              "div",
              {
                style: {
                  display: "grid",
                  gridTemplateColumns: "repeat(4, 1fr)",
                  gap: 6,
                },
              },
              cells
            ),
            error.value
              ? h(
                  "div",
                  { style: { marginTop: 8, color: "#b00020", fontSize: 13 } },
                  "⚠ " + error.value
                )
              : null,
          ]
        );
      };
    },
  };
});
