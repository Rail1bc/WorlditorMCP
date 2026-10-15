// 视图组件参考实现（测试夹具 worlditor_play_demo 的视图，v0.7.0）。
//
// 视图组件协议（G3 / D7）：内核以 new Function("Vue", "UiBlock", code) 动态加载
// 本文件，加载器注入返回值（IIFE），返回值 = 一个 Vue 组件定义对象。
// 数据通道：MCP tools/call（视图组件无法 import SDK，故内嵌轻量会话实现）。
//
// 本文件是仓库里**唯一提交在案的视图组件**，因此它同时是两条守卫的对象：
//   1. 样式约定（v0.1.17）：只用 wt-* 类 / CSS 变量，按钮必须带 wt-btn——
//      硬编码浅色会在暗色主题下白底白字；
//   2. 版本串一致性（v0.5.2）：上报的 clientInfo.version = Python 包版本。
// 玩法包自带视图组件时，照此文件写法即可。

(function (Vue, UiBlock) {
  "use strict";
  const { ref, onMounted, h } = Vue;

  const TOKEN_KEY = "worlditor_token";

  // MCP streamable HTTP 会话（每个组件自持；会话 id 由 initialize 响应头给出）
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
          clientInfo: { name: "worlditor-webui", version: "0.7.2" },
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
    name: "DemoView",
    props: { view: { type: Object, required: true } },
    setup() {
      const text = ref("");
      const block = ref(null);
      const error = ref("");

      async function refresh() {
        try {
          const out = await callTool("world_whoami", {});
          text.value = out.text || "";
          block.value = out.ui || null;
          error.value = "";
        } catch (e) {
          error.value = e.message;
        }
      }

      onMounted(refresh);

      return () => {
        const body = [];
        if (error.value) {
          body.push(h("div", { class: "wt-err" }, "⚠ " + error.value));
        } else if (!text.value) {
          body.push(h("div", { class: "wt-dim" }, "加载中……"));
        } else {
          body.push(h("div", { class: "wt-dim" }, text.value));
        }
        // 服务端已展开 ui_hook 的块交给通用渲染器（含部件面板）
        if (block.value) {
          body.push(h(UiBlock, { block: block.value, onAction: refresh }));
        }
        body.push(
          h("button", { class: "wt-btn", onClick: refresh }, "刷新")
        );
        return h("div", {}, [
          h("div", { class: "wt-head" }, [
            h("span", { class: "wt-title" }, "参考视图"),
          ]),
          ...body,
        ]);
      };
    },
  };
});
