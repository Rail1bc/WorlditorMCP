// worlditor_play_player 角色视图。
// 视图组件协议（G3/D7）：new Function("Vue", "UiBlock", code) 动态加载。
// 数据通道：/scene 只读快照（entity.attrs），无需动作通道。

(function (Vue, UiBlock) {
  "use strict";
  const { ref, onMounted, h } = Vue;

  const TOKEN_KEY = "worlditor_token";
  const KIND_EMOJI = { player: "🧍", agent: "🤖" };

  async function fetchScene() {
    const resp = await fetch("/scene", {
      headers: {
        Authorization: "Bearer " + (localStorage.getItem(TOKEN_KEY) || ""),
      },
    });
    if (!resp.ok) throw new Error("HTTP " + resp.status);
    return resp.json();
  }

  return {
    name: "PlayerView",
    props: { view: { type: Object, required: true } },
    setup() {
      const entity = ref(null);
      const error = ref("");

      async function refresh() {
        try {
          const data = await fetchScene();
          entity.value = data.entity || null;
          error.value = "";
        } catch (e) {
          error.value = e.message;
        }
      }

      onMounted(refresh);

      return () => {
        const e = entity.value;
        if (!e) {
          return h(
            "div",
            { style: { fontFamily: "system-ui, sans-serif", color: "#888" } },
            error.value ? "⚠ " + error.value : "加载中……"
          );
        }
        const rows = Object.entries(e.attrs || {}).map(([k, v]) =>
          h(
            "div",
            {
              style: {
                display: "flex",
                justifyContent: "space-between",
                padding: "4px 0",
                borderBottom: "1px solid #eee",
              },
            },
            [h("span", {}, k), h("span", { style: { fontWeight: 600 } }, String(v))]
          )
        );
        return h(
          "div",
          { style: { fontFamily: "system-ui, sans-serif", maxWidth: 360 } },
          [
            h(
              "div",
              { style: { fontSize: 18, fontWeight: 700, marginBottom: 4 } },
              (KIND_EMOJI[e.kind] || "🧍") + " " + e.name
            ),
            h("div", { style: { color: "#666", marginBottom: 8 } }, "「" + e.desc + "」"),
            h("div", { style: { fontWeight: 600, margin: "8px 0 4px" } }, "属性"),
            rows,
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
