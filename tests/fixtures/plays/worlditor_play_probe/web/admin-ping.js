// 管理页组件参考实现之二（测试夹具 worlditor_play_probe 的「探针面板」，v0.7.0）。
//
// 存在的意义：让夹具包拥有**两个**管理页，从而能验收「管理页之间切换时宿主必须
// 重新加载组件」——否则会出现"B 的标题 + A 的界面"。
// 组件协议同视图组件；数据通道是管理端代理端点（见 web/admin-shop.js 的说明）。
// 这个标记字符串是验收脚本用来判断"当前渲染的到底是哪个页面的组件"的锚点。

(function (Vue, UiBlock) {
  "use strict";
  const { ref, onMounted, h } = Vue;

  const BASE = "/admin/play-pages/worlditor_play_probe/ping";

  async function call(action, payload) {
    const resp = await fetch(BASE + "/" + action, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer " + (localStorage.getItem("worlditor_token") || ""),
      },
      body: JSON.stringify(payload || {}),
    });
    const data = await resp.json().catch(() => null);
    if (!resp.ok) {
      throw new Error((data && data.error) || "HTTP " + resp.status);
    }
    return data && data.data !== undefined ? data.data : data;
  }

  return {
    name: "AdminPing",
    props: { page: { type: Object, required: true } },
    setup() {
      const info = ref("");
      const error = ref("");

      async function refresh() {
        try {
          const out = await call("info", {});
          info.value = out.text || "";
          error.value = "";
        } catch (e) {
          error.value = e.message;
        }
      }

      onMounted(refresh);

      return () =>
        h("div", {}, [
          h("p", { class: "PROBE-PAGE-MARKER" }, "PROBE-PAGE-MARKER"),
          error.value ? h("div", { class: "err" }, error.value) : null,
          h("p", {}, info.value || "……"),
          h("button", { onClick: refresh }, "刷新"),
        ]);
    },
  };
});
