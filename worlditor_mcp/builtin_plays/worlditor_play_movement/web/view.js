// worlditor_play_movement 视野视图（3×3 网格）。
// 视图组件协议（G3/D7）：new Function("Vue", "UiBlock", code) 动态加载——
// 本文件即该函数体：返回 Vue 组件选项对象。
// 数据通道：MCP tools/call（动作统一走 MCP，B10）。

(function (Vue, UiBlock) {
  "use strict";
  const { ref, onMounted, h } = Vue;

  const TOKEN_KEY = "worlditor_token";
  // 地块连接槽的绝对方向（内核数据模型，DESIGN §数据模型）——本包无朝向概念
  const DIR_OFFSETS = { up: [-1, 0], right: [0, 1], down: [1, 0], left: [0, -1] };
  const DIR_LABEL = { up: "上", right: "右", down: "下", left: "左" };
  const DIR_ARROW = { up: "↑", right: "→", down: "↓", left: "←" };
  const KIND_EMOJI = {
    player: "🧍",
    agent: "🤖",
    merchant: "🧑‍🌾",
    sign: "📋",
    door: "🚪",
    wolf: "🐺",
  };

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

  // 轻量 MCP 调用（组件无法 import，内嵌实现；协议见 PLAY_DEV §8）
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

  function dirOf(dr, dc) {
    for (const d of Object.keys(DIR_OFFSETS)) {
      const [oDr, oDc] = DIR_OFFSETS[d];
      if (oDr === dr && oDc === dc) return d;
    }
    return null; // 中心格
  }

  return {
    name: "MovementView",
    props: { view: { type: Object, required: true } },
    setup() {
      const grid = ref([]);
      const here = ref(null);
      const paths = ref([]);
      const error = ref("");
      const busy = ref(false);

      async function refresh() {
        try {
          const look = await callTool("world_look", {});
          grid.value = Array.isArray(look.grid) ? look.grid : [];
          here.value = look.location || null;
          paths.value = Array.isArray(look.paths) ? look.paths : [];
          error.value = "";
        } catch (e) {
          error.value = e.message;
        }
      }

      // 点相邻格直接走（绝对方向，无"先转身"步骤）
      async function go(dir) {
        if (busy.value || !dir) return;
        busy.value = true;
        error.value = "";
        try {
          await callTool("world_move", { direction: dir });
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
        for (let dr = -1; dr <= 1; dr++) {
          for (let dc = -1; dc <= 1; dc++) {
            const cell = grid.value.find((g) => g.dr === dr && g.dc === dc);
            const dir = dirOf(dr, dc);
            const walkable = Boolean(dir && paths.value.includes(dir));
            const isCenter = dr === 0 && dc === 0;
            const children = [];
            if (cell && cell.loc) {
              children.push(h("div", { class: "wt-strong" }, cell.loc.name));
            }
            if (cell) {
              for (const e of cell.entities) {
                const label = e.is_me
                  ? "你"
                  : (KIND_EMOJI[e.kind] || "❔") + " " + e.name;
                children.push(
                  h("div", { class: e.is_me ? "wt-strong wt-clip" : "wt-clip" }, label)
                );
              }
            }
            if (!isCenter && walkable) {
              children.push(
                h("div", { class: "wt-dim" }, (DIR_ARROW[dir] || "") + " 可走")
              );
            }
            const cls = ["wt-cell"];
            if (isCenter) cls.push("here");
            if (walkable) cls.push("walkable");
            cells.push(
              h(
                "div",
                {
                  class: cls.join(" "),
                  onClick: walkable ? () => go(dir) : null,
                },
                children
              )
            );
          }
        }

        return h("div", {}, [
          h("div", { class: "wt-head" }, [
            h(
              "span",
              { class: "wt-title" },
              here.value ? here.value.name : "…"
            ),
            h(
              "button",
              { class: "wt-btn", onClick: () => refresh(), disabled: busy.value },
              "刷新"
            ),
          ]),
          h("div", { class: "wt-grid wt-cols-3" }, cells),
          paths.value.length
            ? h(
                "div",
                { class: "wt-note" },
                "可走：" +
                  paths.value.map((d) => DIR_LABEL[d] || d).join("、")
              )
            : h("div", { class: "wt-note" }, "这里没有可走的出口。"),
          error.value ? h("div", { class: "wt-err" }, "⚠ " + error.value) : null,
        ]);
      };
    },
  };
});
