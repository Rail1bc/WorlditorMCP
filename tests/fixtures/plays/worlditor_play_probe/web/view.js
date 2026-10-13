// 探针夹具包的视图组件（占位实现，v0.7.0）。
//
// 它存在的意义是让「世界激活过滤」与「SSE 自动刷新视图 tab」这类测试有两个
// 视图可对照（demo 包的 view.js 是完整参考实现；本文件只需能被加载出来）。
// 故**不含** MCP 会话与 clientInfo.version——版本串一致性守卫只认参考实现那份。

(function (Vue, UiBlock) {
  "use strict";
  const { ref, onMounted, h } = Vue;

  return {
    name: "ProbeView",
    props: { view: { type: Object, required: true } },
    setup() {
      const ready = ref(false);
      onMounted(() => {
        ready.value = true;
      });
      return () =>
        h("div", {}, [
          h("div", { class: "wt-head" }, [
            h("span", { class: "wt-title" }, "探针视图"),
          ]),
          h("div", { class: "wt-dim" }, ready.value ? "已加载" : "加载中……"),
        ]);
    },
  };
});
