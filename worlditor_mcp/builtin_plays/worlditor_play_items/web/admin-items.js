// worlditor_play_items 管理页组件：物品定义管理。
// 管理页组件协议（v0.1.12）：new Function("Vue", "UiBlock", code) 动态加载——
// 本文件即该函数体：返回 Vue 组件选项对象（render 函数，运行时无模板编译器）。
// 数据通道：/admin/play-pages/<play_id>/<page_key>/<action> 代理端点（tier=admin）。

(function (Vue, UiBlock) {
  "use strict";
  const { ref, reactive, onMounted, h } = Vue;

  const TOKEN_KEY = "worlditor_token";
  const BASE = "/admin/play-pages/worlditor_play_items/items";

  async function call(action, params) {
    const resp = await fetch(BASE + "/" + action, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer " + (localStorage.getItem(TOKEN_KEY) || ""),
      },
      body: JSON.stringify(params || {}),
    });
    let data = {};
    try {
      data = await resp.json();
    } catch (e) {
      /* ignore */
    }
    if (!resp.ok) throw new Error(data.error || "HTTP " + resp.status);
    return data.data || {};
  }

  const emptyForm = () => ({
    id: "",
    name: "",
    desc: "",
    icon: "",
    stackable: true,
    use_action: "",
    attrs: "",
  });

  return {
    name: "AdminItemsView",
    setup() {
      const items = ref([]);
      const form = reactive(emptyForm());
      const editId = ref("");
      const error = ref("");
      const busy = ref(false);
      const note = ref("");

      async function refresh() {
        busy.value = true;
        error.value = "";
        try {
          const data = await call("list", {});
          items.value = Array.isArray(data.items) ? data.items : [];
        } catch (e) {
          error.value = e.message;
        } finally {
          busy.value = false;
        }
      }

      function resetForm() {
        Object.assign(form, emptyForm());
        editId.value = "";
      }

      function edit(item) {
        editId.value = item.id;
        Object.assign(form, {
          id: item.id,
          name: item.name,
          desc: item.desc || "",
          icon: item.icon || "",
          stackable: item.stackable !== false,
          use_action: item.use_action || "",
          attrs: JSON.stringify(item.attrs || {}, null, 2),
        });
      }

      async function save() {
        error.value = "";
        note.value = "";
        let attrs = {};
        try {
          attrs = form.attrs.trim() ? JSON.parse(form.attrs) : {};
        } catch (e) {
          error.value = "attrs 不是合法 JSON：" + e.message;
          return;
        }
        const payload = {
          id: form.id,
          name: form.name,
          desc: form.desc,
          icon: form.icon,
          stackable: form.stackable,
          use_action: form.use_action || null,
          attrs: attrs,
        };
        try {
          if (editId.value) {
            await call("update", payload);
            note.value = "已更新「" + form.name + "」";
          } else {
            await call("create", payload);
            note.value = "已创建「" + form.name + "」";
          }
          resetForm();
          await refresh();
        } catch (e) {
          error.value = e.message;
        }
      }

      async function remove(item) {
        if (!confirm("删除物品定义「" + item.name + "」？持有数据不受影响。")) return;
        error.value = "";
        try {
          await call("delete", { id: item.id });
          await refresh();
        } catch (e) {
          error.value = e.message;
        }
      }

      onMounted(refresh);

      return () => {
        const rowStyle = (item) => ({
          display: "grid",
          gridTemplateColumns: "96px 1fr 60px 90px 90px",
          gap: 8,
          padding: "8px 10px",
          borderBottom: "1px solid var(--bg-3)",
          alignItems: "center",
          fontSize: 13,
          cursor: "pointer",
        });
        const headStyle = Object.assign({}, rowStyle(), {
          color: "var(--text-dim)",
          borderBottom: "1px solid var(--bg-3)",
          cursor: "default",
        });
        const inputStyle = {
          padding: "7px 9px",
          borderRadius: 8,
          border: "1px solid var(--bg-3)",
          background: "var(--bg)",
          color: "var(--text)",
          fontSize: 13,
          width: "100%",
        };
        const btnStyle = {
          padding: "8px 14px",
          borderRadius: 8,
          border: "none",
          background: "var(--accent-dim)",
          color: "#fff",
          cursor: "pointer",
          fontSize: 13,
        };
        const ghostBtn = Object.assign({}, btnStyle, {
          background: "transparent",
          border: "1px solid var(--bg-3)",
          color: "var(--text-dim)",
        });
        const dangerBtn = Object.assign({}, ghostBtn, {
          color: "var(--danger)",
          borderColor: "var(--danger)",
        });

        return h("div", { style: { fontFamily: "system-ui, sans-serif" } }, [
          h(
            "div",
            {
              style: {
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: 10,
              },
            },
            [
              h("span", { style: { fontWeight: 600 } }, "物品定义（" + items.value.length + "）"),
              h(
                "button",
                { onClick: () => refresh(), disabled: busy.value, style: ghostBtn },
                "刷新"
              ),
            ]
          ),
          error.value
            ? h(
                "p",
                { style: { color: "var(--danger)", fontSize: 13 } },
                "⚠ " + error.value
              )
            : null,
          note.value
            ? h("p", { style: { color: "var(--accent)", fontSize: 13 } }, note.value)
            : null,

          // 列表
          h("div", { style: { marginBottom: 12 } }, [
            h(
              "div",
              { style: headStyle },
              [
                h("span", {}, "id"),
                h("span", {}, "名称"),
                h("span", {}, "堆叠"),
                h("span", {}, "use_action"),
                h("span", {}, "操作"),
              ]
            ),
            items.value.map((it) =>
              h(
                "div",
                { key: it.id, style: rowStyle(it), onClick: () => edit(it) },
                [
                  h("code", { style: { fontSize: 12 } }, it.id),
                  h("span", {}, it.name + (it.desc ? " — " + it.desc : "")),
                  h("span", { style: { color: "var(--text-dim)" } }, it.stackable ? "是" : "否"),
                  h("span", { style: { color: "var(--text-dim)" } }, it.use_action || "—"),
                  h(
                    "button",
                    {
                      onClick: (e) => {
                        e.stopPropagation();
                        remove(it);
                      },
                      style: dangerBtn,
                    },
                    "删除"
                  ),
                ]
              )
            ),
            !items.value.length
              ? h(
                  "p",
                  { style: { color: "var(--text-dim)", fontSize: 13 } },
                  "暂无物品定义"
                )
              : null,
          ]),

          // 表单
          h(
            "div",
            {
              style: {
                border: "1px solid var(--bg-3)",
                borderRadius: 10,
                padding: 12,
                display: "flex",
                flexDirection: "column",
                gap: 8,
              },
            },
            [
              h("strong", {}, editId.value ? "编辑：" + editId.value : "新建物品定义"),
              h(
                "div",
                { style: { display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 } },
                [
                  h("input", {
                    placeholder: "物品 id（如 knife）",
                    value: form.id,
                    disabled: !!editId.value,
                    onInput: (e) => (form.id = e.target.value),
                    style: inputStyle,
                  }),
                  h("input", {
                    placeholder: "名称",
                    value: form.name,
                    onInput: (e) => (form.name = e.target.value),
                    style: inputStyle,
                  }),
                  h("input", {
                    placeholder: "icon（可选）",
                    value: form.icon,
                    onInput: (e) => (form.icon = e.target.value),
                    style: inputStyle,
                  }),
                  h("input", {
                    placeholder: "use_action（如 eat，可选）",
                    value: form.use_action,
                    onInput: (e) => (form.use_action = e.target.value),
                    style: inputStyle,
                  }),
                ]
              ),
              h("textarea", {
                placeholder: "描述",
                rows: 2,
                value: form.desc,
                onInput: (e) => (form.desc = e.target.value),
                style: Object.assign({}, inputStyle, { resize: "vertical" }),
              }),
              h("textarea", {
                placeholder: 'attrs JSON（如 {"price": 5}，可选）',
                rows: 3,
                value: form.attrs,
                onInput: (e) => (form.attrs = e.target.value),
                style: Object.assign({}, inputStyle, {
                  resize: "vertical",
                  fontFamily: "monospace",
                  fontSize: 12,
                }),
              }),
              h(
                "label",
                { style: { display: "flex", gap: 6, alignItems: "center", fontSize: 13 } },
                [
                  h("input", {
                    type: "checkbox",
                    checked: form.stackable,
                    onChange: (e) => (form.stackable = e.target.checked),
                  }),
                  h("span", {}, "可堆叠"),
                ]
              ),
              h(
                "div",
                { style: { display: "flex", gap: 8 } },
                [
                  h("button", { onClick: () => save(), style: btnStyle }, "保存"),
                  editId.value
                    ? h("button", { onClick: () => resetForm(), style: ghostBtn }, "取消编辑")
                    : null,
                ]
              ),
            ]
          ),
        ]);
      };
    },
  };
});
