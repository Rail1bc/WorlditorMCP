// worlditor_play_movement 视野视图（3×3 网格）。
// 视图组件协议（G3/D7）：new Function("Vue", "UiBlock", code) 动态加载——
// 本文件即该函数体：返回 Vue 组件选项对象。
// 数据通道：MCP tools/call（与 mcpc.js 同协议），动作统一走 MCP（B10）。

(function (Vue, UiBlock) {
  "use strict";
  const { ref, onMounted, h } = Vue;

  const TOKEN_KEY = "worlditor_token";
  const ABS = ["up", "right", "down", "left"];
  const DIR_OFFSETS = { up: [-1, 0], down: [1, 0], left: [0, -1], right: [0, 1] };
  const REL = ["forward", "right", "back", "left"];
  const KIND_EMOJI = {
    player: "🧍",
    agent: "🤖",
    merchant: "🧑‍🌾",
    sign: "📋",
    door: "🚪",
    wolf: "🐺",
  };
  const FACING_ARROW = { up: "▲", right: "▶", down: "▼", left: "◀" };

  // 轻量 MCP 调用（与 webui/src/mcpc.js 同协议；组件无法 import，内嵌实现）
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

  function relTo(facing, dir) {
    const f = ABS.indexOf(facing);
    const d = ABS.indexOf(dir);
    const delta = ((d - f) % 4 + 4) % 4;
    return REL[delta];
  }

  function dirOf(dr, dc) {
    for (const d of ABS) {
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
      const facing = ref("up");
      const paths = ref([]);
      const error = ref("");
      const busy = ref(false);

      async function refresh() {
        try {
          const look = await callTool("world_look", {});
          grid.value = Array.isArray(look.grid) ? look.grid : [];
          facing.value = look.facing || "up";
          paths.value = Array.isArray(look.paths) ? look.paths : [];
          error.value = "";
        } catch (e) {
          error.value = e.message;
        }
      }

      async function go(rel) {
        if (busy.value) return;
        busy.value = true;
        error.value = "";
        try {
          await callTool("world_move", { direction: rel });
          await refresh();
        } catch (e) {
          error.value = e.message;
        } finally {
          busy.value = false;
        }
      }

      async function turn(rel) {
        try {
          await callTool("world_turn", { direction: rel });
          await refresh();
        } catch (e) {
          error.value = e.message;
        }
      }

      onMounted(refresh);

      return () => {
        const cellStyle = {
          border: "1px solid #ddd",
          borderRadius: 6,
          padding: 6,
          minHeight: 56,
          background: "#f4f4f4",
          fontSize: 12,
          overflow: "hidden",
        };
        const cells = [];
        for (let dr = -1; dr <= 1; dr++) {
          for (let dc = -1; dc <= 1; dc++) {
            const cell = grid.value.find((g) => g.dr === dr && g.dc === dc);
            const dir = dirOf(dr, dc);
            const walkable = Boolean(dir && paths.value.includes(dir));
            const isCenter = dr === 0 && dc === 0;
            const children = [];
            if (cell && cell.loc) {
              children.push(
                h("div", { style: { fontWeight: 600 } }, cell.loc.name)
              );
            }
            if (cell) {
              for (const e of cell.entities) {
                const label = e.is_me
                  ? "你 " + (FACING_ARROW[facing.value] || "")
                  : (KIND_EMOJI[e.kind] || "❔") + " " + e.name;
                children.push(
                  h(
                    "div",
                    {
                      style: {
                        whiteSpace: "nowrap",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        fontWeight: e.is_me ? 700 : 400,
                      },
                    },
                    label
                  )
                );
              }
            }
            if (!isCenter && walkable) {
              children.push(h("div", { style: { color: "#2f6f2f" } }, "可走 →"));
            }
            const style = {
              ...cellStyle,
              background: isCenter
                ? "#fff7d6"
                : cell && cell.loc
                  ? "#ffffff"
                  : "#f4f4f4",
              cursor: walkable ? "pointer" : "default",
            };
            cells.push(
              h(
                "div",
                {
                  style,
                  onClick: walkable
                    ? () => go(relTo(facing.value, dir))
                    : null,
                },
                children
              )
            );
          }
        }

        const rowStyle = {
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
          gap: 4,
          marginBottom: 4,
        };

        return h(
          "div",
          { style: { fontFamily: "system-ui, sans-serif", maxWidth: 420 } },
          [
            h(
              "div",
              {
                style: {
                  display: "flex",
                  alignItems: "center",
                  gap: 8,
                  marginBottom: 8,
                },
              },
              [
                h("button", { onClick: () => turn("left") }, "← 左转"),
                h(
                  "span",
                  { style: { flex: 1, textAlign: "center", fontWeight: 600 } },
                  "你面向 " + (FACING_ARROW[facing.value] || "") + " " + facing.value
                ),
                h("button", { onClick: () => turn("right") }, "右转 →"),
              ]
            ),
            h("div", { style: rowStyle }, cells.slice(0, 3)),
            h("div", { style: rowStyle }, cells.slice(3, 6)),
            h("div", { style: rowStyle }, cells.slice(6, 9)),
            paths.value.length
              ? h(
                  "div",
                  { style: { marginTop: 8, fontSize: 12, color: "#555" } },
                  "可走：" +
                    paths.value
                      .map((d) => {
                        const rel = relTo(facing.value, d);
                        return (
                          d +
                          "（" +
                          rel +
                          "）"
                        );
                      })
                      .join("、")
                )
              : null,
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
