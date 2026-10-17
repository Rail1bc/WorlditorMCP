// 视图组件参考实现 · 玩家包（worlditor_play_player，v0.8.0）。
//
// 视图组件协议（G3 / D7）：内核以 new Function("Vue", "UiBlock", code) 动态加载
// 本文件，加载器注入返回值（IIFE），返回值 = 一个 Vue 组件定义对象。
// 数据通道：MCP tools/call（视图组件无法 import SDK，故内嵌轻量会话实现）。
//
// 本文件演示**"没有化身"是合法状态**（D45/D46）该怎么写：
//   - 一律先调 player_whoami / player_avatars（它们声明了 requires_entity=False，
//     没有化身时也调得到——这是自举路径的关键）；
//   - roster 为空 → 显示"创建角色"按钮，而不是报错或空白；
//   - 切角色后**重新拉一次**（api.act_as 影响的是后续请求的行动实体）。
//
// 样式约定（v0.1.17）：只用 wt-* 类 / CSS 变量，按钮必须带 wt-btn——
// 硬编码浅色会在暗色主题下白底白字。版本串（v0.5.2）必须与 Python 包版本一致。

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
          clientInfo: { name: "worlditor-webui", version: "0.9.0" },
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
      const who = ref("");
      const roster = ref("");
      const error = ref("");
      const busy = ref(false);

      async function refresh() {
        busy.value = true;
        try {
          const me = await callTool("player_whoami", {});
          who.value = me.text || "";
          const list = await callTool("player_avatars", {});
          roster.value = list.text || "";
          error.value = "";
        } catch (e) {
          error.value = e.message;
        } finally {
          busy.value = false;
        }
      }

      async function create() {
        busy.value = true;
        try {
          const out = await callTool("player_create", {});
          who.value = out.text || who.value;
          await refresh();
        } catch (e) {
          error.value = e.message;
        } finally {
          busy.value = false;
        }
      }

      onMounted(refresh);

      return () => {
        const body = [];
        if (error.value) {
          body.push(h("div", { class: "wt-err" }, "⚠ " + error.value));
        }
        body.push(
          h("div", { class: "wt-dim" }, busy.value ? "加载中……" : who.value)
        );
        if (roster.value) {
          body.push(h("pre", { class: "wt-list" }, roster.value));
        }
        body.push(
          h(
            "div",
            {},
            [
              h(
                "button",
                { class: "wt-btn", onClick: create, disabled: busy.value },
                "创建角色"
              ),
              h(
                "button",
                { class: "wt-btn", onClick: refresh, disabled: busy.value },
                "刷新"
              ),
            ]
          )
        );
        return h("div", {}, [
          h("div", { class: "wt-head" }, [
            h("span", { class: "wt-title" }, "角色"),
          ]),
          ...body,
        ]);
      };
    },
  };
});
