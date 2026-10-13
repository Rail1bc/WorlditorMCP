// 管理页组件参考实现（测试夹具 worlditor_play_demo 的「货单管理」页，v0.7.0）。
//
// 管理页组件协议同视图组件（new Function("Vue", "UiBlock", code)），差别在
// 数据通道：不直连 MCP，而是 fetch 管理端代理端点
// POST /admin/play-pages/{play_id}/{page_key}/{action}（同源 + Bearer）。
// 管理页组件不走玩家端样式守卫（admin-*.js 用管理端表格密度自行管理）。

(function (Vue, UiBlock) {
  "use strict";
  const { ref, onMounted, h } = Vue;

  const BASE = "/admin/play-pages/worlditor_play_demo/shop";

  async function call(action, payload) {
    const resp = await fetch(BASE + "/" + action, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer " + (localStorage.getItem("worlditor_admin_key") || ""),
      },
      body: JSON.stringify(payload || {}),
    });
    const data = await resp.json().catch(() => null);
    if (!resp.ok) {
      throw new Error((data && data.detail) || "HTTP " + resp.status);
    }
    return data && data.data !== undefined ? data.data : data;
  }

  return {
    name: "AdminShop",
    props: { page: { type: Object, required: true } },
    setup() {
      const rows = ref([]);
      const error = ref("");

      async function refresh() {
        try {
          const out = await call("list", {});
          const prices = out.prices || {};
          rows.value = Object.keys(prices).map((id) => ({
            id: id,
            label: prices[id].label,
            price: prices[id].price,
          }));
          error.value = "";
        } catch (e) {
          error.value = e.message;
        }
      }

      async function setPrice(row) {
        const raw = window.prompt("新价格", String(row.price));
        if (raw === null) return;
        try {
          await call("set_price", { item_id: row.id, price: Number(raw) });
          await refresh();
        } catch (e) {
          error.value = e.message;
        }
      }

      onMounted(refresh);

      return () =>
        h("div", {}, [
          error.value ? h("div", { class: "err" }, error.value) : null,
          h("table", {}, [
            h("thead", {}, [
              h("tr", {}, [h("th", {}, "货品"), h("th", {}, "价格"), h("th", {})]),
            ]),
            h(
              "tbody",
              {},
              rows.value.map((row) =>
                h("tr", {}, [
                  h("td", {}, row.label || row.id),
                  h("td", {}, String(row.price)),
                  h(
                    "td",
                    {},
                    [h("button", { onClick: () => setPrice(row) }, "改价")]
                  ),
                ])
              )
            ),
          ]),
          h("button", { onClick: refresh }, "刷新"),
        ]);
    },
  };
});
