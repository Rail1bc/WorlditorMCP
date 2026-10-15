import { ref, computed, openBlock, createElementBlock, createElementVNode, Fragment, renderList, normalizeClass, createTextVNode, toDisplayString, createCommentVNode, withDirectives, withKeys, withModifiers, vModelText, reactive, watch, createVNode, vModelSelect, vModelCheckbox, unref, createRenderer, nextTick, h } from "vue";
const CORE_INFO = "core:info";
const CORE_POSITION = "core:position";
function entityPosition(e) {
  const p = e && e.components && e.components[CORE_POSITION];
  if (!p) return null;
  const { map_id, row, col } = p;
  if (typeof map_id !== "string" || !map_id) return null;
  if (typeof row !== "number" || typeof col !== "number") return null;
  return { map_id, row, col };
}
function hasPosition(e) {
  return entityPosition(e) !== null;
}
function positionLabel(e) {
  const p = entityPosition(e);
  if (!p) return "不在世界";
  return `${p.map_id} ${p.row},${p.col}`;
}
const NO_ROW = 1 << 30;
const NO_COL = 1 << 30;
const NO_MAP = "￿";
function positionSortKey(e) {
  const p = entityPosition(e);
  if (!p) return [NO_MAP, NO_ROW, NO_COL];
  return [p.map_id, p.row, p.col];
}
function withoutPosition(components) {
  const out = { ...components || {} };
  delete out[CORE_POSITION];
  return out;
}
function rawEntityName(e) {
  const info = e && e.components && e.components[CORE_INFO];
  return info && typeof info.name === "string" ? info.name : "";
}
function entityName(e) {
  const name = rawEntityName(e);
  if (name) return name;
  return e && e.id ? String(e.id).slice(0, 8) : "";
}
function rawEntityDesc(e) {
  const info = e && e.components && e.components[CORE_INFO];
  return info && typeof info.desc === "string" ? info.desc : "";
}
function entityDesc(e) {
  return rawEntityDesc(e);
}
function hasComponent(e, key) {
  return Boolean(e && e.components && Object.prototype.hasOwnProperty.call(e.components, key));
}
function componentKeys(e) {
  return Object.keys(e && e.components || {});
}
const CORE_PREFIX = "core:";
function isCoreComponent(key) {
  return String(key).startsWith(CORE_PREFIX);
}
function abilityComponents(e) {
  return componentKeys(e).filter((key) => !isCoreComponent(key));
}
const _export_sfc = (sfc, props) => {
  const target = sfc.__vccOpts || sfc;
  for (const [key, val] of props) {
    target[key] = val;
  }
  return target;
};
const _hoisted_1$3 = { class: "component-picker" };
const _hoisted_2$3 = ["title"];
const _hoisted_3$3 = {
  key: 0,
  class: "src"
};
const _hoisted_4$3 = ["title", "onClick"];
const _hoisted_5$2 = ["value"];
const _hoisted_6$2 = ["placeholder", "onKeydown"];
const _hoisted_7$2 = {
  key: 0,
  class: "bad"
};
const LOCAL$1 = "local";
const _sfc_main$3 = {
  __name: "ComponentPicker",
  props: {
    modelValue: { type: Array, default: () => [] },
    // 组件键列表
    kinds: { type: Array, default: () => [] }
    // 组件声明清单（{key, source, name, label, …}）
  },
  emits: ["update:modelValue"],
  setup(__props, { emit: __emit }) {
    const props = __props;
    const emit = __emit;
    const COMPONENT_RE = /^[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+$/;
    const freeText = ref("");
    const freeError = ref("");
    const freePlaceholder = computed(() => `手输组件键（如 stat → ${LOCAL$1}:stat，回车添加）`);
    function specOf(key) {
      return props.kinds.find((k) => k.key === key) || null;
    }
    function labelOf(key) {
      const spec = specOf(key);
      if (!spec) return key;
      return spec.label && spec.label !== key ? `${spec.label}（${key}）` : key;
    }
    const available = computed(() => props.kinds.filter((k) => !props.modelValue.includes(k.key)));
    function add(key) {
      if (!key || props.modelValue.includes(key)) return;
      freeError.value = "";
      emit("update:modelValue", [...props.modelValue, key]);
    }
    function addFree() {
      freeError.value = "";
      const text2 = freeText.value.trim();
      if (!text2) return;
      const full = text2.includes(":") ? text2 : `${LOCAL$1}:${text2}`;
      if (!COMPONENT_RE.test(full)) {
        freeError.value = `组件键不合法：${full}（只允许字母/数字/下划线/点/连字符，且必须是「来源:名字」）`;
        return;
      }
      freeText.value = "";
      add(full);
    }
    function remove(index) {
      const next = [...props.modelValue];
      next.splice(index, 1);
      emit("update:modelValue", next);
    }
    return (_ctx, _cache) => {
      return openBlock(), createElementBlock("div", _hoisted_1$3, [
        _cache[3] || (_cache[3] = createElementVNode("span", { class: "label" }, "组件", -1)),
        (openBlock(true), createElementBlock(Fragment, null, renderList(__props.modelValue, (key, i) => {
          return openBlock(), createElementBlock("span", {
            key: `v-${key}`,
            class: normalizeClass(["chip", { unknown: !specOf(key) }]),
            title: specOf(key) ? `已声明：${specOf(key).label || key}` : "虚构组件：没有声明，不贡献能力（允许存在）"
          }, [
            createTextVNode(toDisplayString(labelOf(key)) + " ", 1),
            specOf(key) ? (openBlock(), createElementBlock("span", _hoisted_3$3, "来源 " + toDisplayString(specOf(key).source), 1)) : createCommentVNode("", true),
            createElementVNode("button", {
              class: "x",
              title: specOf(key) ? "移除组件（它的数据也一起删）" : "虚构组件：没有声明，不贡献任何能力",
              onClick: ($event) => remove(i)
            }, " × ", 8, _hoisted_4$3)
          ], 10, _hoisted_2$3);
        }), 128)),
        createElementVNode("select", {
          class: "mini",
          value: "",
          onChange: _cache[0] || (_cache[0] = ($event) => add($event.target.value))
        }, [
          _cache[2] || (_cache[2] = createElementVNode("option", { value: "" }, "＋ 已声明组件…", -1)),
          (openBlock(true), createElementBlock(Fragment, null, renderList(available.value, (k) => {
            return openBlock(), createElementBlock("option", {
              key: k.key,
              value: k.key
            }, toDisplayString(k.label) + "（" + toDisplayString(k.key) + " · 来源 " + toDisplayString(k.source) + "） ", 9, _hoisted_5$2);
          }), 128))
        ], 32),
        withDirectives(createElementVNode("input", {
          "onUpdate:modelValue": _cache[1] || (_cache[1] = ($event) => freeText.value = $event),
          class: "mini",
          placeholder: freePlaceholder.value,
          onKeydown: withKeys(withModifiers(addFree, ["prevent"]), ["enter"])
        }, null, 40, _hoisted_6$2), [
          [vModelText, freeText.value]
        ]),
        freeError.value ? (openBlock(), createElementBlock("span", _hoisted_7$2, toDisplayString(freeError.value), 1)) : createCommentVNode("", true)
      ]);
    };
  }
};
const ComponentPicker = /* @__PURE__ */ _export_sfc(_sfc_main$3, [["__scopeId", "data-v-993a48d0"]]);
const _hoisted_1$2 = ["value"];
const _hoisted_2$2 = ["value", "step"];
const _hoisted_3$2 = ["checked"];
const _hoisted_4$2 = ["value"];
const _sfc_main$2 = {
  __name: "FieldControl",
  props: {
    field: { type: Object, required: true },
    // {name,label,type,default?,source,play_id}
    modelValue: { type: [String, Number, Boolean], default: "" }
    // json 类型传 JSON 文本
  },
  emits: ["update:modelValue", "commit"],
  setup(__props, { emit: __emit }) {
    const emit = __emit;
    return (_ctx, _cache) => {
      return __props.field.type === "str" ? (openBlock(), createElementBlock("input", {
        key: 0,
        value: __props.modelValue,
        onInput: _cache[0] || (_cache[0] = ($event) => emit("update:modelValue", $event.target.value)),
        onChange: _cache[1] || (_cache[1] = ($event) => emit("commit"))
      }, null, 40, _hoisted_1$2)) : __props.field.type === "int" || __props.field.type === "float" ? (openBlock(), createElementBlock("input", {
        key: 1,
        value: __props.modelValue,
        type: "number",
        step: __props.field.type === "float" ? "any" : 1,
        onInput: _cache[2] || (_cache[2] = ($event) => emit("update:modelValue", $event.target.value === "" ? "" : Number($event.target.value))),
        onChange: _cache[3] || (_cache[3] = ($event) => emit("commit"))
      }, null, 40, _hoisted_2$2)) : __props.field.type === "bool" ? (openBlock(), createElementBlock("input", {
        key: 2,
        type: "checkbox",
        checked: Boolean(__props.modelValue),
        onChange: _cache[4] || (_cache[4] = ($event) => {
          emit("update:modelValue", $event.target.checked);
          emit("commit");
        })
      }, null, 40, _hoisted_3$2)) : (openBlock(), createElementBlock("textarea", {
        key: 3,
        value: __props.modelValue,
        rows: "2",
        placeholder: "JSON",
        onInput: _cache[5] || (_cache[5] = ($event) => emit("update:modelValue", $event.target.value)),
        onChange: _cache[6] || (_cache[6] = ($event) => emit("commit"))
      }, null, 40, _hoisted_4$2));
    };
  }
};
const FieldControl = /* @__PURE__ */ _export_sfc(_sfc_main$2, [["__scopeId", "data-v-c45acfc3"]]);
const confirmState = reactive({
  open: false,
  title: "",
  text: "",
  detail: "",
  danger: false,
  confirmText: "确定",
  cancelText: "取消",
  _resolve: null
});
function askConfirm(opts = {}) {
  if (confirmState._resolve) confirmState._resolve(false);
  confirmState.open = true;
  confirmState.title = opts.title || "确认操作";
  confirmState.text = opts.text || "";
  confirmState.detail = opts.detail || "";
  confirmState.danger = Boolean(opts.danger);
  confirmState.confirmText = opts.confirmText || (opts.danger ? "删除" : "确定");
  confirmState.cancelText = opts.cancelText || "取消";
  return new Promise((resolve) => {
    confirmState._resolve = resolve;
  });
}
const _hoisted_1$1 = { class: "field-form" };
const _hoisted_2$1 = {
  key: 0,
  class: "error-text"
};
const _hoisted_3$1 = { class: "comps" };
const _hoisted_4$1 = ["open"];
const _hoisted_5$1 = { class: "cname" };
const _hoisted_6$1 = ["title"];
const _hoisted_7$1 = {
  key: 0,
  class: "dim"
};
const _hoisted_8$1 = {
  key: 1,
  class: "bad",
  title: "这个组件里没有声明过的键：不贡献任何能力，但会原样保存"
};
const _hoisted_9$1 = { class: "comp-body" };
const _hoisted_10$1 = {
  key: 0,
  class: "declared"
};
const _hoisted_11$1 = ["title"];
const _hoisted_12$1 = {
  key: 1,
  class: "tiny"
};
const _hoisted_13$1 = ["onUpdate:modelValue"];
const _hoisted_14$1 = ["onClick"];
const _hoisted_15$1 = {
  key: 0,
  class: "dim"
};
const _hoisted_16$1 = { class: "new-comp" };
const _hoisted_17$1 = { class: "new-row" };
const _hoisted_18$1 = ["onKeydown"];
const _hoisted_19$1 = {
  key: 0,
  class: "error-text"
};
const LOCAL = "local";
const CORE = "core";
const _sfc_main$1 = {
  __name: "FieldForm",
  props: {
    kinds: { type: Array, default: () => [] },
    // 组件声明清单（{key, source, label, fields, …}）
    components: { type: Object, default: () => ({}) }
    // 组件键 → 数据对象
  },
  emits: ["update"],
  setup(__props, { emit: __emit }) {
    const props = __props;
    const emit = __emit;
    const COMPONENT_RE = /^[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+$/;
    const values = reactive({});
    const complex = reactive({});
    const extraText = reactive({});
    const jsonError = ref("");
    const newName = ref("");
    const newJson = ref("{}");
    const newError = ref("");
    const justAdded = ref("");
    const compNames = computed(() => Object.keys(props.components || {}));
    const knownSources = computed(
      () => new Set(
        props.kinds.map((k) => k.source).filter((s) => s && s !== CORE && s !== LOCAL)
      )
    );
    function rankOf(name) {
      const source = String(name).split(":")[0];
      if (source === CORE) return 0;
      if (knownSources.value.has(source)) return 1;
      if (source === LOCAL) return 2;
      return 3;
    }
    const ordered = computed(
      () => [...compNames.value].sort((a, b) => rankOf(a) - rankOf(b) || a.localeCompare(b))
    );
    function declaredFieldsOf(name) {
      const spec = props.kinds.find((k) => k.key === name);
      return spec && spec.fields || [];
    }
    function defaultFor(type) {
      if (type === "int" || type === "float") return 0;
      if (type === "bool") return false;
      return "";
    }
    function fieldDefault(f) {
      return f.default !== void 0 ? f.default : defaultFor(f.type);
    }
    function controlValue(name, f) {
      if (f.type === "json") return (complex[name] && complex[name][f.name]) ?? "";
      return values[name] ? values[name][f.name] : void 0;
    }
    function setControl(name, f, value) {
      jsonError.value = "";
      if (f.type === "json") {
        if (!complex[name]) complex[name] = {};
        complex[name][f.name] = value;
      } else {
        if (!values[name]) values[name] = {};
        values[name][f.name] = value;
      }
    }
    const componentList = computed(
      () => ordered.value.map((name) => {
        const data = props.components[name] || {};
        const declared = new Set(declaredFieldsOf(name).map((f) => f.name));
        const extraCount = Object.keys(data).filter((key) => !declared.has(key)).length;
        return { name, fields: declaredFieldsOf(name), extraCount, ...badgeOf(name) };
      })
    );
    function badgeOf(name) {
      const source = String(name).split(":")[0];
      if (source === CORE) {
        return {
          badge: "内核保留",
          badgeClass: "core",
          badgeTitle: "core: 是内核保留命名空间（玩法包不得写入）"
        };
      }
      if (knownSources.value.has(source)) {
        return {
          badge: `玩法包 ${source}`,
          badgeClass: "play",
          badgeTitle: `来源包：${source}`
        };
      }
      const spec = props.kinds.find((k) => k.key === name);
      if (spec) {
        return {
          badge: "已声明",
          badgeClass: "decl",
          badgeTitle: `已声明：${spec.label || spec.key}`
        };
      }
      return {
        badge: "虚构组件",
        badgeClass: "und",
        badgeTitle: "未声明组件（虚构组件）：没有对应声明，不贡献任何能力，但允许存在"
      };
    }
    function parseObjectText(text2, where) {
      const raw = String(text2 ?? "").trim();
      if (!raw) return { ok: true, value: {} };
      let parsed;
      try {
        parsed = JSON.parse(raw);
      } catch (e) {
        return { ok: false, error: `${where}的 JSON 解析失败：${e.message}` };
      }
      if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
        return { ok: false, error: `${where}必须是一个 JSON 对象` };
      }
      return { ok: true, value: parsed };
    }
    function parseJsonValue(text2, where) {
      const raw = String(text2 ?? "").trim();
      if (!raw || raw === "null") return { ok: true, value: null };
      try {
        return { ok: true, value: JSON.parse(raw) };
      } catch (e) {
        return { ok: false, error: `${where}不是合法 JSON：${e.message}` };
      }
    }
    function declaredValues(name) {
      const out = {};
      for (const f of declaredFieldsOf(name)) {
        if (f.type === "json") {
          const where = `字段「${f.label || f.name}」（组件 ${name}）`;
          const parsed = parseJsonValue(complex[name] && complex[name][f.name], where);
          if (!parsed.ok) {
            jsonError.value = parsed.error;
            return null;
          }
          out[f.name] = parsed.value;
        } else {
          out[f.name] = values[name] ? values[name][f.name] : void 0;
        }
      }
      return out;
    }
    function buildComponents(skip = "") {
      const out = {};
      for (const name of compNames.value) {
        if (name === skip) continue;
        const raw = extraText[name];
        let extra;
        if (raw === void 0) {
          extra = { ...props.components[name] || {} };
        } else {
          const parsed = parseObjectText(raw, `组件「${name}」`);
          if (!parsed.ok) {
            jsonError.value = parsed.error;
            return null;
          }
          extra = parsed.value;
        }
        const declared = declaredValues(name);
        if (declared === null) return null;
        out[name] = { ...extra, ...declared };
      }
      return out;
    }
    function commit() {
      const next = buildComponents();
      if (next === null) return;
      jsonError.value = "";
      emit("update", { components: next });
    }
    function normalizeName(raw) {
      const text2 = String(raw || "").trim();
      if (!text2) return { ok: false, error: "组件键不能为空" };
      const full = text2.includes(":") ? text2 : `${LOCAL}:${text2}`;
      if (!COMPONENT_RE.test(full)) {
        return {
          ok: false,
          error: `组件键不合法：${full}（只允许字母/数字/下划线/点/连字符，且必须是「来源:名字」）`
        };
      }
      return { ok: true, name: full };
    }
    function addComponent() {
      newError.value = "";
      const named = normalizeName(newName.value);
      if (!named.ok) {
        newError.value = named.error;
        return;
      }
      if (compNames.value.includes(named.name)) {
        newError.value = `组件已存在：${named.name}（要改数据请在下面那块里编辑）`;
        return;
      }
      const body = parseObjectText(newJson.value, `组件「${named.name}」`);
      if (!body.ok) {
        newError.value = body.error;
        return;
      }
      const next = buildComponents();
      if (next === null) return;
      next[named.name] = body.value;
      justAdded.value = named.name;
      newName.value = "";
      newJson.value = "{}";
      jsonError.value = "";
      emit("update", { components: next });
    }
    async function dropComponent(name) {
      const ok = await askConfirm({
        title: "删除组件",
        danger: true,
        text: `从实体上删除组件「${name}」？`,
        detail: "能力 = 组件的存在：删掉它，这个实体就失去该组件带来的能力，组件里的数据也一起移除；保存后才真正生效。",
        confirmText: "删除"
      });
      if (!ok) return;
      const next = buildComponents(name);
      if (next === null) return;
      delete next[name];
      if (justAdded.value === name) justAdded.value = "";
      jsonError.value = "";
      emit("update", { components: next });
    }
    function syncFromProps() {
      const names = compNames.value;
      for (const key of Object.keys(values)) {
        if (!names.includes(key)) delete values[key];
      }
      for (const key of Object.keys(complex)) {
        if (!names.includes(key)) delete complex[key];
      }
      for (const key of Object.keys(extraText)) {
        if (!names.includes(key)) delete extraText[key];
      }
      for (const name of names) {
        const data = props.components[name] || {};
        const fields = declaredFieldsOf(name);
        const declaredNames = new Set(fields.map((f) => f.name));
        const plain = {};
        const json = {};
        for (const f of fields) {
          const present = Object.prototype.hasOwnProperty.call(data, f.name);
          if (f.type === "json") {
            json[f.name] = present ? JSON.stringify(data[f.name]) : JSON.stringify(f.default ?? {});
          } else {
            plain[f.name] = present ? data[f.name] : fieldDefault(f);
          }
        }
        values[name] = plain;
        complex[name] = json;
        const extra = {};
        for (const [key, value] of Object.entries(data)) {
          if (!declaredNames.has(key)) extra[key] = value;
        }
        extraText[name] = JSON.stringify(extra, null, 2);
      }
      jsonError.value = "";
    }
    watch(() => props.components, syncFromProps, { immediate: true });
    return (_ctx, _cache) => {
      return openBlock(), createElementBlock("div", _hoisted_1$1, [
        jsonError.value ? (openBlock(), createElementBlock("p", _hoisted_2$1, toDisplayString(jsonError.value), 1)) : createCommentVNode("", true),
        createElementVNode("div", _hoisted_3$1, [
          (openBlock(true), createElementBlock(Fragment, null, renderList(componentList.value, (c) => {
            return openBlock(), createElementBlock("details", {
              key: c.name,
              class: "comp",
              open: c.name === justAdded.value || null
            }, [
              createElementVNode("summary", null, [
                createElementVNode("code", _hoisted_5$1, toDisplayString(c.name), 1),
                createElementVNode("span", {
                  class: normalizeClass(["chip", c.badgeClass]),
                  title: c.badgeTitle
                }, toDisplayString(c.badge), 11, _hoisted_6$1),
                c.fields.length ? (openBlock(), createElementBlock("span", _hoisted_7$1, toDisplayString(c.fields.length) + " 个声明字段", 1)) : createCommentVNode("", true),
                c.extraCount ? (openBlock(), createElementBlock("span", _hoisted_8$1, " 其余键 " + toDisplayString(c.extraCount), 1)) : createCommentVNode("", true)
              ]),
              createElementVNode("div", _hoisted_9$1, [
                c.fields.length ? (openBlock(), createElementBlock("div", _hoisted_10$1, [
                  (openBlock(true), createElementBlock(Fragment, null, renderList(c.fields, (f) => {
                    return openBlock(), createElementBlock("div", {
                      key: f.name,
                      class: "field"
                    }, [
                      createElementVNode("label", {
                        title: `${f.name}（${f.type}）—— 声明自组件 ${c.name}`
                      }, toDisplayString(f.label || f.name), 9, _hoisted_11$1),
                      createVNode(FieldControl, {
                        field: f,
                        "model-value": controlValue(c.name, f),
                        "onUpdate:modelValue": (v) => setControl(c.name, f, v),
                        onCommit: commit
                      }, null, 8, ["field", "model-value", "onUpdate:modelValue"])
                    ]);
                  }), 128))
                ])) : (openBlock(), createElementBlock("p", _hoisted_12$1, "这个组件没有声明任何字段（数据可以直接写在下面的 JSON 里）。")),
                _cache[2] || (_cache[2] = createElementVNode("label", { class: "tiny" }, "其余键（未声明字段）—— 原始 JSON，整块替换本组件的数据", -1)),
                withDirectives(createElementVNode("textarea", {
                  "onUpdate:modelValue": ($event) => extraText[c.name] = $event,
                  rows: "2",
                  placeholder: "{}",
                  onChange: commit
                }, null, 40, _hoisted_13$1), [
                  [vModelText, extraText[c.name]]
                ]),
                createElementVNode("button", {
                  class: "mini-btn danger",
                  onClick: ($event) => dropComponent(c.name)
                }, "删除组件", 8, _hoisted_14$1)
              ])
            ], 8, _hoisted_4$1);
          }), 128)),
          !componentList.value.length ? (openBlock(), createElementBlock("p", _hoisted_15$1, " 这个实体还没有任何组件（没有必填组件，空字典也是合法状态）。 ")) : createCommentVNode("", true)
        ]),
        createElementVNode("details", _hoisted_16$1, [
          _cache[3] || (_cache[3] = createElementVNode("summary", null, "＋ 新增组件", -1)),
          createElementVNode("div", _hoisted_17$1, [
            withDirectives(createElementVNode("input", {
              "onUpdate:modelValue": _cache[0] || (_cache[0] = ($event) => newName.value = $event),
              class: "mini",
              placeholder: "组件键（如 stat → local:stat）",
              onKeydown: withKeys(withModifiers(addComponent, ["prevent"]), ["enter"])
            }, null, 40, _hoisted_18$1), [
              [vModelText, newName.value]
            ]),
            createElementVNode("button", {
              class: "btn",
              onClick: addComponent
            }, "添加")
          ]),
          _cache[4] || (_cache[4] = createElementVNode("p", { class: "tiny" }, [
            createTextVNode(" 组件键 = "),
            createElementVNode("code", null, "来源:名字"),
            createTextVNode("："),
            createElementVNode("code", null, "core:"),
            createTextVNode(" 内核保留、玩法包用自己的 id、 编辑器手写用 "),
            createElementVNode("code", null, "local:"),
            createTextVNode("。只允许字母/数字/下划线/点/连字符，且必须含一个冒号 （不含冒号时自动补 "),
            createElementVNode("code", null, "local:"),
            createTextVNode("）。 ")
          ], -1)),
          _cache[5] || (_cache[5] = createElementVNode("label", { class: "tiny" }, "数据 JSON", -1)),
          withDirectives(createElementVNode("textarea", {
            "onUpdate:modelValue": _cache[1] || (_cache[1] = ($event) => newJson.value = $event),
            rows: "2",
            placeholder: '{"gold": 120}'
          }, null, 512), [
            [vModelText, newJson.value]
          ]),
          newError.value ? (openBlock(), createElementBlock("p", _hoisted_19$1, toDisplayString(newError.value), 1)) : createCommentVNode("", true)
        ])
      ]);
    };
  }
};
const FieldForm = /* @__PURE__ */ _export_sfc(_sfc_main$1, [["__scopeId", "data-v-79111ac5"]]);
const _hoisted_1 = { class: "entity-manager" };
const _hoisted_2 = { class: "toolbar" };
const _hoisted_3 = ["value"];
const _hoisted_4 = {
  key: 0,
  class: "mini-label pinned"
};
const _hoisted_5 = { class: "dim" };
const _hoisted_6 = {
  key: 0,
  class: "create"
};
const _hoisted_7 = { class: "row" };
const _hoisted_8 = ["value"];
const _hoisted_9 = { id: "component-options" };
const _hoisted_10 = ["value"];
const _hoisted_11 = {
  class: "mini-label",
  title: "不勾 = 造一个不在世界上的实体（先造出来，之后再放）"
};
const _hoisted_12 = {
  key: 1,
  class: "dim"
};
const _hoisted_13 = {
  key: 1,
  class: "error-text"
};
const _hoisted_14 = { class: "split" };
const _hoisted_15 = { class: "list-wrap" };
const _hoisted_16 = { class: "table tight" };
const _hoisted_17 = ["onClick"];
const _hoisted_18 = { class: "name" };
const _hoisted_19 = {
  key: 0,
  class: "dim ell"
};
const _hoisted_20 = { class: "comp-cell" };
const _hoisted_21 = {
  key: 0,
  class: "dim"
};
const _hoisted_22 = ["title"];
const _hoisted_23 = { class: "dim" };
const _hoisted_24 = { class: "caps-cell" };
const _hoisted_25 = {
  key: 0,
  class: "dim"
};
const _hoisted_26 = {
  key: 1,
  class: "chip bad",
  title: "虚构组件：没有声明，不贡献能力"
};
const _hoisted_27 = {
  key: 2,
  class: "chip bad",
  title: "有声明，但它所属的玩法包在本世界未启用"
};
const _hoisted_28 = { class: "ops-col" };
const _hoisted_29 = ["disabled", "title", "onClick"];
const _hoisted_30 = ["onClick"];
const _hoisted_31 = { key: 0 };
const _hoisted_32 = {
  colspan: "5",
  class: "dim"
};
const _hoisted_33 = {
  key: 0,
  class: "pager"
};
const _hoisted_34 = ["disabled"];
const _hoisted_35 = { class: "dim" };
const _hoisted_36 = ["disabled"];
const _hoisted_37 = { class: "detail" };
const _hoisted_38 = { class: "detail-head" };
const _hoisted_39 = { class: "dim" };
const _hoisted_40 = { class: "field" };
const _hoisted_41 = ["placeholder"];
const _hoisted_42 = { class: "field" };
const _hoisted_43 = {
  key: 0,
  class: "caps"
};
const _hoisted_44 = {
  key: 0,
  class: "bad"
};
const _hoisted_45 = {
  key: 1,
  class: "bad"
};
const _hoisted_46 = { key: 2 };
const _hoisted_47 = { key: 3 };
const _hoisted_48 = { class: "detail-ops" };
const _hoisted_49 = ["disabled"];
const _hoisted_50 = {
  key: 1,
  class: "dim"
};
const _sfc_main = {
  __name: "EntityManager",
  props: {
    entities: { type: Array, default: () => [] },
    kinds: { type: Array, default: () => [] },
    entityTemplates: { type: Array, default: () => [] },
    tileFilter: { type: Object, default: null },
    // {row, col} | null（从地图跳进来时带的）
    // 是否允许"造一个不在世界上的实体"（D36）——只有实体治理视角（全局实体页）为真
    allowAbsent: { type: Boolean, default: false }
  },
  emits: ["create", "update", "remove", "save-template", "locate"],
  setup(__props, { expose: __expose, emit: __emit }) {
    const props = __props;
    const emit = __emit;
    const error = ref("");
    const q = ref("");
    const componentFilter = ref("");
    const sort = ref("pos");
    const tileOnly = ref(true);
    const page = ref(1);
    const pageSize = ref(50);
    const showCreate = ref(false);
    const selectedId = ref("");
    const draft = reactive({
      template_id: "",
      ability: "",
      // 单个能力组件：自由输入，裸名由后端解析成组件键（省略 = 不带能力组件）
      name: "",
      components: {},
      // 组件键 → 数据（实体数据的唯一单位）
      row: 0,
      col: 0,
      place: true
      // D36：勾选 = 放进世界（发坐标）；不勾 = 造一个不在世界上的实体
    });
    const edit = reactive({ name: "", desc: "", components: {} });
    const draftKeys = computed(() => componentKeys({ components: draft.components }));
    const editKeys = computed(() => componentKeys({ components: edit.components }));
    function withKeys2(components, keys) {
      const out = {};
      for (const key of keys) {
        out[key] = Object.prototype.hasOwnProperty.call(components || {}, key) ? components[key] : {};
      }
      return out;
    }
    function setDraftKeys(keys) {
      draft.components = withKeys2(draft.components, keys);
    }
    function setEditKeys(keys) {
      edit.components = withKeys2(edit.components, keys);
    }
    const componentOptions = computed(() => {
      const rank = (key) => isCoreComponent(key) ? 1 : 0;
      return [...new Set(props.entities.flatMap((e) => componentKeys(e)))].sort(
        (a, b) => rank(a) - rank(b) || a.localeCompare(b)
      );
    });
    function componentSortKey(e) {
      return abilityComponents(e).sort().join("、");
    }
    const filtered = computed(() => {
      const needle = q.value.trim().toLowerCase();
      const list = props.entities.filter((e) => {
        if (tileOnly.value && props.tileFilter) {
          const p = entityPosition(e);
          if (!p || p.row !== props.tileFilter.row || p.col !== props.tileFilter.col) return false;
        }
        if (componentFilter.value && !hasComponent(e, componentFilter.value)) return false;
        if (!needle) return true;
        return entityName(e).toLowerCase().includes(needle) || e.id.toLowerCase().includes(needle) || // 组件键也是可搜的（"哪些实体带 core:perception" 这类排查）
        componentKeys(e).some((n) => n.toLowerCase().includes(needle));
      });
      const byPos = (a, b) => {
        const [ka, ra, ca] = positionSortKey(a);
        const [kb, rb, cb] = positionSortKey(b);
        return ka.localeCompare(kb) || ra - rb || ca - cb || entityName(a).localeCompare(entityName(b));
      };
      if (sort.value === "name")
        list.sort((a, b) => entityName(a).localeCompare(entityName(b)));
      else if (sort.value === "comp")
        list.sort((a, b) => componentSortKey(a).localeCompare(componentSortKey(b)) || byPos(a, b));
      else list.sort(byPos);
      return list;
    });
    const pages = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize.value)));
    const pageItems = computed(() => {
      const start = (page.value - 1) * pageSize.value;
      return filtered.value.slice(start, start + pageSize.value);
    });
    const current = computed(() => props.entities.find((e) => e.id === selectedId.value) || null);
    const fieldGroups = computed(() => {
      var _a;
      const fields = current.value && ((_a = current.value.capabilities) == null ? void 0 : _a.fields) || {};
      return Object.entries(fields).map(([key, list]) => ({
        key,
        names: (list || []).map((f) => f.label || f.name).join("、") || "（无）"
      }));
    });
    watch(filtered, () => {
      if (page.value > pages.value) page.value = pages.value;
    });
    watch(
      () => props.tileFilter,
      (v) => {
        if (v) {
          tileOnly.value = true;
          page.value = 1;
        }
      }
    );
    function isUnknown(e, key) {
      return (e && e.capabilities && e.capabilities.unknown_components || []).includes(key);
    }
    function cloneComponents(components) {
      return JSON.parse(JSON.stringify(components || {}));
    }
    function select(e) {
      selectedId.value = e.id;
      edit.name = rawEntityName(e);
      edit.desc = rawEntityDesc(e);
      edit.components = cloneComponents(e.components);
    }
    function applyTemplate() {
      const t = props.entityTemplates.find((x) => x.id === draft.template_id);
      if (!t) return;
      const d = t.data || {};
      draft.name = d.name || "";
      draft.components = cloneComponents(d.components);
    }
    function create() {
      error.value = "";
      const pos = draft.place ? { row: Number(draft.row), col: Number(draft.col) } : {};
      const components = draft.place ? cloneComponents(draft.components) : withoutPosition(draft.components);
      emit("create", {
        // 能力组件是**输入便利**：裸名由后端解析成组件键；不填 = 不带能力组件
        kind: draft.ability.trim() || void 0,
        name: draft.name.trim() || void 0,
        components,
        ...pos
      });
      draft.name = "";
      draft.ability = "";
    }
    function save() {
      if (!current.value) return;
      const patch = {
        // name/desc 走顶层键（后端折进 core:info）。name 为空就**不发**——
        // 空的 name 在语义上是"没设名字 → 展示回落 id 前 8 位"，而后端要求 name 非空。
        desc: edit.desc,
        components: cloneComponents(edit.components)
        // PATCH 里 components 是整体替换
      };
      if (edit.name.trim()) patch.name = edit.name.trim();
      emit("update", current.value, patch);
    }
    __expose({
      setError: (msg) => error.value = msg,
      focus: (id) => {
        selectedId.value = id;
        const e = props.entities.find((x) => x.id === id);
        if (e) select(e);
      }
    });
    return (_ctx, _cache) => {
      return openBlock(), createElementBlock("div", _hoisted_1, [
        createElementVNode("div", _hoisted_2, [
          withDirectives(createElementVNode("input", {
            "onUpdate:modelValue": _cache[0] || (_cache[0] = ($event) => q.value = $event),
            class: "mini search",
            placeholder: "搜索名称 / 组件 / id…"
          }, null, 512), [
            [vModelText, q.value]
          ]),
          withDirectives(createElementVNode("select", {
            "onUpdate:modelValue": _cache[1] || (_cache[1] = ($event) => componentFilter.value = $event),
            class: "mini"
          }, [
            _cache[23] || (_cache[23] = createElementVNode("option", { value: "" }, "全部组件", -1)),
            (openBlock(true), createElementBlock(Fragment, null, renderList(componentOptions.value, (k) => {
              return openBlock(), createElementBlock("option", {
                key: k,
                value: k
              }, toDisplayString(k), 9, _hoisted_3);
            }), 128))
          ], 512), [
            [vModelSelect, componentFilter.value]
          ]),
          withDirectives(createElementVNode("select", {
            "onUpdate:modelValue": _cache[2] || (_cache[2] = ($event) => sort.value = $event),
            class: "mini"
          }, [..._cache[24] || (_cache[24] = [
            createElementVNode("option", { value: "pos" }, "按位置", -1),
            createElementVNode("option", { value: "name" }, "按名称", -1),
            createElementVNode("option", { value: "comp" }, "按组件", -1)
          ])], 512), [
            [vModelSelect, sort.value]
          ]),
          __props.tileFilter ? (openBlock(), createElementBlock("label", _hoisted_4, [
            withDirectives(createElementVNode("input", {
              type: "checkbox",
              "onUpdate:modelValue": _cache[3] || (_cache[3] = ($event) => tileOnly.value = $event)
            }, null, 512), [
              [vModelCheckbox, tileOnly.value]
            ]),
            createTextVNode(" 只看地块 (" + toDisplayString(__props.tileFilter.row) + ", " + toDisplayString(__props.tileFilter.col) + ") ", 1)
          ])) : createCommentVNode("", true),
          _cache[25] || (_cache[25] = createElementVNode("span", { class: "grow" }, null, -1)),
          createElementVNode("span", _hoisted_5, toDisplayString(filtered.value.length) + " 个实体", 1),
          createElementVNode("button", {
            class: "btn",
            onClick: _cache[4] || (_cache[4] = ($event) => showCreate.value = !showCreate.value)
          }, toDisplayString(showCreate.value ? "收起放置" : "＋ 放置实体"), 1)
        ]),
        showCreate.value ? (openBlock(), createElementBlock("div", _hoisted_6, [
          createElementVNode("div", _hoisted_7, [
            withDirectives(createElementVNode("select", {
              "onUpdate:modelValue": _cache[5] || (_cache[5] = ($event) => draft.template_id = $event),
              class: "mini",
              onChange: applyTemplate
            }, [
              _cache[26] || (_cache[26] = createElementVNode("option", { value: "" }, "（不用模板）", -1)),
              (openBlock(true), createElementBlock(Fragment, null, renderList(__props.entityTemplates, (t) => {
                return openBlock(), createElementBlock("option", {
                  key: t.id,
                  value: t.id
                }, toDisplayString(t.name) + toDisplayString(t.source === "play" ? `（${t.play_id}）` : ""), 9, _hoisted_8);
              }), 128))
            ], 544), [
              [vModelSelect, draft.template_id]
            ]),
            withDirectives(createElementVNode("input", {
              "onUpdate:modelValue": _cache[6] || (_cache[6] = ($event) => draft.ability = $event),
              class: "mini",
              list: "component-options",
              placeholder: "能力组件（可自由输入，裸名由后端解析）"
            }, null, 512), [
              [vModelText, draft.ability]
            ]),
            createElementVNode("datalist", _hoisted_9, [
              (openBlock(true), createElementBlock(Fragment, null, renderList(__props.kinds, (k) => {
                return openBlock(), createElementBlock("option", {
                  key: k.key,
                  value: k.key
                }, toDisplayString(k.label), 9, _hoisted_10);
              }), 128))
            ]),
            withDirectives(createElementVNode("input", {
              "onUpdate:modelValue": _cache[7] || (_cache[7] = ($event) => draft.name = $event),
              class: "mini",
              placeholder: "名称（默认取组件文案）"
            }, null, 512), [
              [vModelText, draft.name]
            ]),
            __props.allowAbsent ? (openBlock(), createElementBlock(Fragment, { key: 0 }, [
              createElementVNode("label", _hoisted_11, [
                withDirectives(createElementVNode("input", {
                  "onUpdate:modelValue": _cache[8] || (_cache[8] = ($event) => draft.place = $event),
                  type: "checkbox"
                }, null, 512), [
                  [vModelCheckbox, draft.place]
                ]),
                _cache[27] || (_cache[27] = createTextVNode(" 放进世界 ", -1))
              ]),
              draft.place ? (openBlock(), createElementBlock(Fragment, { key: 0 }, [
                _cache[28] || (_cache[28] = createElementVNode("span", { class: "dim" }, "@", -1)),
                withDirectives(createElementVNode("input", {
                  "onUpdate:modelValue": _cache[9] || (_cache[9] = ($event) => draft.row = $event),
                  type: "number",
                  class: "num",
                  placeholder: "行"
                }, null, 512), [
                  [
                    vModelText,
                    draft.row,
                    void 0,
                    { number: true }
                  ]
                ]),
                withDirectives(createElementVNode("input", {
                  "onUpdate:modelValue": _cache[10] || (_cache[10] = ($event) => draft.col = $event),
                  type: "number",
                  class: "num",
                  placeholder: "列"
                }, null, 512), [
                  [
                    vModelText,
                    draft.col,
                    void 0,
                    { number: true }
                  ]
                ])
              ], 64)) : (openBlock(), createElementBlock("span", _hoisted_12, "不在世界上"))
            ], 64)) : (openBlock(), createElementBlock(Fragment, { key: 1 }, [
              _cache[29] || (_cache[29] = createElementVNode("span", { class: "dim" }, "@", -1)),
              withDirectives(createElementVNode("input", {
                "onUpdate:modelValue": _cache[11] || (_cache[11] = ($event) => draft.row = $event),
                type: "number",
                class: "num",
                placeholder: "行"
              }, null, 512), [
                [
                  vModelText,
                  draft.row,
                  void 0,
                  { number: true }
                ]
              ]),
              withDirectives(createElementVNode("input", {
                "onUpdate:modelValue": _cache[12] || (_cache[12] = ($event) => draft.col = $event),
                type: "number",
                class: "num",
                placeholder: "列"
              }, null, 512), [
                [
                  vModelText,
                  draft.col,
                  void 0,
                  { number: true }
                ]
              ])
            ], 64)),
            createElementVNode("button", {
              class: "btn",
              onClick: create
            }, toDisplayString(draft.place ? "放置" : "创建"), 1)
          ]),
          createVNode(ComponentPicker, {
            "model-value": draftKeys.value,
            kinds: __props.kinds,
            "onUpdate:modelValue": setDraftKeys
          }, null, 8, ["model-value", "kinds"]),
          createVNode(FieldForm, {
            kinds: __props.kinds,
            components: draft.components,
            onUpdate: _cache[13] || (_cache[13] = (v) => draft.components = v.components)
          }, null, 8, ["kinds", "components"])
        ])) : createCommentVNode("", true),
        error.value ? (openBlock(), createElementBlock("p", _hoisted_13, toDisplayString(error.value), 1)) : createCommentVNode("", true),
        createElementVNode("div", _hoisted_14, [
          createElementVNode("div", _hoisted_15, [
            createElementVNode("table", _hoisted_16, [
              _cache[30] || (_cache[30] = createElementVNode("thead", null, [
                createElementVNode("tr", null, [
                  createElementVNode("th", null, "名称"),
                  createElementVNode("th", null, "组件"),
                  createElementVNode("th", null, "位置"),
                  createElementVNode("th", null, "能力"),
                  createElementVNode("th", { class: "ops-col" }, "操作")
                ])
              ], -1)),
              createElementVNode("tbody", null, [
                (openBlock(true), createElementBlock(Fragment, null, renderList(pageItems.value, (e) => {
                  var _a, _b, _c, _d, _e, _f;
                  return openBlock(), createElementBlock("tr", {
                    key: e.id,
                    class: normalizeClass({ on: selectedId.value === e.id }),
                    onClick: ($event) => select(e)
                  }, [
                    createElementVNode("td", null, [
                      createElementVNode("span", _hoisted_18, toDisplayString(unref(entityName)(e)), 1),
                      unref(entityDesc)(e) ? (openBlock(), createElementBlock("div", _hoisted_19, toDisplayString(unref(entityDesc)(e)), 1)) : createCommentVNode("", true)
                    ]),
                    createElementVNode("td", _hoisted_20, [
                      !unref(abilityComponents)(e).length ? (openBlock(), createElementBlock("span", _hoisted_21, "—")) : createCommentVNode("", true),
                      (openBlock(true), createElementBlock(Fragment, null, renderList(unref(abilityComponents)(e), (k) => {
                        return openBlock(), createElementBlock("span", {
                          key: k,
                          class: normalizeClass(["chip", { bad: isUnknown(e, k) }]),
                          title: isUnknown(e, k) ? "虚构组件：没有声明，不贡献能力" : `组件 ${k}（能力 = 组件的存在）`
                        }, toDisplayString(k), 11, _hoisted_22);
                      }), 128))
                    ]),
                    createElementVNode("td", _hoisted_23, toDisplayString(unref(positionLabel)(e)), 1),
                    createElementVNode("td", _hoisted_24, [
                      (openBlock(true), createElementBlock(Fragment, null, renderList((((_a = e.capabilities) == null ? void 0 : _a.interactions) || []).slice(0, 2), (a) => {
                        return openBlock(), createElementBlock("span", {
                          key: a,
                          class: "chip"
                        }, toDisplayString(a), 1);
                      }), 128)),
                      (((_b = e.capabilities) == null ? void 0 : _b.interactions) || []).length > 2 ? (openBlock(), createElementBlock("span", _hoisted_25, " +" + toDisplayString(e.capabilities.interactions.length - 2), 1)) : createCommentVNode("", true),
                      ((_d = (_c = e.capabilities) == null ? void 0 : _c.unknown_components) == null ? void 0 : _d.length) ? (openBlock(), createElementBlock("span", _hoisted_26, " ⚠" + toDisplayString(e.capabilities.unknown_components.length), 1)) : createCommentVNode("", true),
                      ((_f = (_e = e.capabilities) == null ? void 0 : _e.inactive_components) == null ? void 0 : _f.length) ? (openBlock(), createElementBlock("span", _hoisted_27, " ⏸" + toDisplayString(e.capabilities.inactive_components.length), 1)) : createCommentVNode("", true)
                    ]),
                    createElementVNode("td", _hoisted_28, [
                      createElementVNode("button", {
                        class: "mini-btn",
                        disabled: !unref(hasPosition)(e),
                        title: unref(hasPosition)(e) ? "在地图上选中它所在的地块" : "它不在世界上（没有 core:position），没有地块可定位",
                        onClick: withModifiers(($event) => emit("locate", e), ["stop"])
                      }, " 定位 ", 8, _hoisted_29),
                      createElementVNode("button", {
                        class: "mini-btn danger",
                        onClick: withModifiers(($event) => emit("remove", e), ["stop"])
                      }, "删除", 8, _hoisted_30)
                    ])
                  ], 10, _hoisted_17);
                }), 128)),
                !filtered.value.length ? (openBlock(), createElementBlock("tr", _hoisted_31, [
                  createElementVNode("td", _hoisted_32, toDisplayString(__props.tileFilter && tileOnly.value ? "这个地块上没有实体。" : "没有匹配的实体。"), 1)
                ])) : createCommentVNode("", true)
              ])
            ]),
            pages.value > 1 ? (openBlock(), createElementBlock("div", _hoisted_33, [
              createElementVNode("button", {
                class: "mini-btn",
                disabled: page.value <= 1,
                onClick: _cache[14] || (_cache[14] = ($event) => page.value -= 1)
              }, "‹ 上一页", 8, _hoisted_34),
              createElementVNode("span", _hoisted_35, "第 " + toDisplayString(page.value) + " / " + toDisplayString(pages.value) + " 页", 1),
              createElementVNode("button", {
                class: "mini-btn",
                disabled: page.value >= pages.value,
                onClick: _cache[15] || (_cache[15] = ($event) => page.value += 1)
              }, "下一页 ›", 8, _hoisted_36),
              withDirectives(createElementVNode("select", {
                "onUpdate:modelValue": _cache[16] || (_cache[16] = ($event) => pageSize.value = $event),
                class: "mini"
              }, [..._cache[31] || (_cache[31] = [
                createElementVNode("option", { value: 50 }, "50 / 页", -1),
                createElementVNode("option", { value: 100 }, "100 / 页", -1),
                createElementVNode("option", { value: 200 }, "200 / 页", -1)
              ])], 512), [
                [
                  vModelSelect,
                  pageSize.value,
                  void 0,
                  { number: true }
                ]
              ])
            ])) : createCommentVNode("", true)
          ]),
          createElementVNode("aside", _hoisted_37, [
            current.value ? (openBlock(), createElementBlock(Fragment, { key: 0 }, [
              createElementVNode("div", _hoisted_38, [
                _cache[32] || (_cache[32] = createElementVNode("b", null, "实体详情", -1)),
                createElementVNode("code", _hoisted_39, toDisplayString(current.value.id.slice(0, 8)), 1)
              ]),
              createElementVNode("label", _hoisted_40, [
                _cache[33] || (_cache[33] = createTextVNode(" 名称 ", -1)),
                withDirectives(createElementVNode("input", {
                  "onUpdate:modelValue": _cache[17] || (_cache[17] = ($event) => edit.name = $event),
                  placeholder: `未设名字 → 显示 ${current.value.id.slice(0, 8)}（core:info.name）`
                }, null, 8, _hoisted_41), [
                  [vModelText, edit.name]
                ])
              ]),
              createElementVNode("label", _hoisted_42, [
                _cache[34] || (_cache[34] = createTextVNode(" 描述 ", -1)),
                withDirectives(createElementVNode("textarea", {
                  "onUpdate:modelValue": _cache[18] || (_cache[18] = ($event) => edit.desc = $event),
                  rows: "2",
                  placeholder: "core:info.desc（可留空）"
                }, null, 512), [
                  [vModelText, edit.desc]
                ])
              ]),
              createVNode(ComponentPicker, {
                "model-value": editKeys.value,
                kinds: __props.kinds,
                "onUpdate:modelValue": setEditKeys
              }, null, 8, ["model-value", "kinds"]),
              createVNode(FieldForm, {
                kinds: __props.kinds,
                components: edit.components,
                onUpdate: _cache[19] || (_cache[19] = (v) => edit.components = v.components)
              }, null, 8, ["kinds", "components"]),
              current.value.capabilities ? (openBlock(), createElementBlock("div", _hoisted_43, [
                _cache[36] || (_cache[36] = createElementVNode("b", null, "合并后的能力", -1)),
                createElementVNode("div", null, "生效组件：" + toDisplayString(current.value.capabilities.active_components.join("、") || "（无）"), 1),
                current.value.capabilities.inactive_components.length ? (openBlock(), createElementBlock("div", _hoisted_44, " 本世界未启用：" + toDisplayString(current.value.capabilities.inactive_components.join("、")) + " （有声明，但该玩法包在本世界没启用） ", 1)) : createCommentVNode("", true),
                current.value.capabilities.unknown_components.length ? (openBlock(), createElementBlock("div", _hoisted_45, " 没有声明：" + toDisplayString(current.value.capabilities.unknown_components.join("、")) + " （虚构组件，不贡献能力） ", 1)) : createCommentVNode("", true),
                createElementVNode("div", null, "动作：" + toDisplayString(current.value.capabilities.interactions.join("、") || "（无）"), 1),
                fieldGroups.value.length ? (openBlock(), createElementBlock("div", _hoisted_46, [
                  _cache[35] || (_cache[35] = createTextVNode(" 字段： ", -1)),
                  (openBlock(true), createElementBlock(Fragment, null, renderList(fieldGroups.value, (g) => {
                    return openBlock(), createElementBlock("div", {
                      key: g.key,
                      class: "fields-row"
                    }, [
                      createElementVNode("code", null, toDisplayString(g.key), 1),
                      createTextVNode(": " + toDisplayString(g.names), 1)
                    ]);
                  }), 128))
                ])) : (openBlock(), createElementBlock("div", _hoisted_47, "字段：（无）"))
              ])) : createCommentVNode("", true),
              createElementVNode("div", _hoisted_48, [
                createElementVNode("button", {
                  class: "btn",
                  onClick: save
                }, "保存"),
                createElementVNode("button", {
                  class: "mini-btn",
                  onClick: _cache[20] || (_cache[20] = ($event) => emit("save-template", current.value))
                }, "存为模板"),
                createElementVNode("button", {
                  class: "mini-btn",
                  disabled: !unref(hasPosition)(current.value),
                  onClick: _cache[21] || (_cache[21] = ($event) => emit("locate", current.value))
                }, " 定位 ", 8, _hoisted_49),
                createElementVNode("button", {
                  class: "mini-btn danger",
                  onClick: _cache[22] || (_cache[22] = ($event) => emit("remove", current.value))
                }, "删除")
              ])
            ], 64)) : (openBlock(), createElementBlock("p", _hoisted_50, "从左边选一个实体查看/编辑详情；也可以用上方的「放置实体」新建。"))
          ])
        ])
      ]);
    };
  }
};
const EntityManager = /* @__PURE__ */ _export_sfc(_sfc_main, [["__scopeId", "data-v-fa37c2a8"]]);
const warnings = [];
const realWarn = console.warn;
console.warn = (...args) => {
  warnings.push(args.join(" "));
  realWarn(...args);
};
function makeEl(tag) {
  const el = {
    tag,
    children: [],
    props: {},
    parent: null,
    _listeners: {},
    _value: void 0,
    selectedIndex: -1,
    multiple: false,
    addEventListener(type, fn) {
      (el._listeners[type] || (el._listeners[type] = [])).push(fn);
    },
    removeEventListener(type, fn) {
      const list = el._listeners[type] || [];
      const i = list.indexOf(fn);
      if (i !== -1) list.splice(i, 1);
    },
    get options() {
      return el.children.filter((c) => c.tag === "option");
    },
    get value() {
      return el._value === void 0 ? "" : el._value;
    },
    set value(v) {
      el._value = v;
    }
  };
  return el;
}
const nodeOps = {
  createElement: (tag) => makeEl(tag),
  createText: (value) => ({ text: value, children: [], props: {}, parent: null }),
  createComment: (value) => ({
    text: value,
    isComment: true,
    children: [],
    props: {},
    parent: null
  }),
  setText: (node, value) => {
    node.text = value;
  },
  setElementText: (el, value) => {
    el.children = [{ text: value, children: [], props: {}, parent: el }];
  },
  insert: (child, parent, anchor) => {
    child.parent = parent;
    if (!anchor) {
      parent.children.push(child);
      return;
    }
    const i = parent.children.indexOf(anchor);
    if (i === -1) parent.children.push(child);
    else parent.children.splice(i, 0, child);
  },
  remove: (child) => {
    const parent = child.parent;
    if (parent) {
      const i = parent.children.indexOf(child);
      if (i !== -1) parent.children.splice(i, 1);
    }
    child.parent = null;
  },
  parentNode: (node) => node.parent || null,
  nextSibling: (node) => {
    const parent = node.parent;
    if (!parent) return null;
    const i = parent.children.indexOf(node);
    return parent.children[i + 1] || null;
  },
  patchProp: (el, key, prev, next) => {
    el.props[key] = next;
    if (key === "value") el._value = next;
  }
};
const { createApp: createMiniApp } = createRenderer(nodeOps);
function fire(node, type) {
  for (const fn of node._listeners[type] || []) fn({ target: node });
}
function walk(node, fn) {
  if (!node) return;
  fn(node);
  for (const child of node.children || []) walk(child, fn);
}
function nodes(root, pred) {
  const out = [];
  walk(root, (n) => {
    if (pred(n)) out.push(n);
  });
  return out;
}
function text(node) {
  let out = "";
  walk(node, (n) => {
    if (typeof n.text === "string") out += n.text;
  });
  return out;
}
function rootNode() {
  return { tag: "#root", children: [], props: {}, parent: null };
}
function setValue(node, value) {
  var _a, _b;
  node.value = value;
  (_b = (_a = node.props).onInput) == null ? void 0 : _b.call(_a, { target: node });
  fire(node, "input");
}
async function pickSelect(node, value) {
  var _a, _b;
  node.value = value;
  fire(node, "change");
  (_b = (_a = node.props).onChange) == null ? void 0 : _b.call(_a, { target: node });
  await nextTick();
}
async function click(node) {
  node.props.onClick();
  await nextTick();
}
const kinds = [
  {
    key: "local:merchant",
    source: "local",
    name: "merchant",
    label: "商人",
    interactions: ["trade"],
    fields: [{ name: "gold", label: "金币", type: "int", default: 10 }],
    categories: []
  },
  {
    key: "worlditor_play_demo:apple",
    source: "worlditor_play_demo",
    name: "apple",
    label: "苹果",
    interactions: ["eat"],
    fields: [],
    categories: []
  }
];
function caps(components, extra = {}) {
  return {
    components: Object.keys(components),
    active_components: [],
    inactive_components: [],
    unknown_components: [],
    interactions: [],
    fields: {},
    ...extra
  };
}
const merchant = {
  id: "aaaaaaaa1111",
  components: {
    "core:info": { name: "老张" },
    "core:position": { map_id: "default", row: 1, col: 2 },
    "local:merchant": { gold: 7 }
  },
  last_active_ts: 1,
  revision: 3,
  changed_tick: 9,
  capabilities: caps(
    { "core:info": {}, "core:position": {}, "local:merchant": { gold: 7 } },
    {
      active_components: ["local:merchant"],
      interactions: ["trade"],
      fields: { "local:merchant": [{ name: "gold", label: "金币", type: "int" }] }
    }
  )
};
const fictional = {
  id: "bbbbbbbb2222",
  components: {
    "local:thing": { hp: 3 },
    "core:position": { map_id: "default", row: 0, col: 0 }
  },
  last_active_ts: 2,
  revision: 1,
  changed_tick: 4,
  capabilities: caps(
    { "local:thing": { hp: 3 }, "core:position": {} },
    { unknown_components: ["local:thing"] }
  )
};
const failures = [];
function check(name, ok) {
  if (!ok) failures.push(name);
}
async function checkEntityManager() {
  const root = rootNode();
  createMiniApp(EntityManager, {
    entities: [merchant, fictional],
    kinds,
    entityTemplates: [
      {
        id: "t1",
        name: "商人模板",
        source: "play",
        play_id: "worlditor_play_demo",
        scope: "entity",
        data: { name: "模板商人", desc: "", components: { "local:merchant": {} } }
      }
    ],
    allowAbsent: true
  }).mount(root);
  const options = nodes(root, (n) => n.tag === "option").map((n) => n.props.value);
  const wanted = ["", "local:merchant", "core:info", "core:position", "local:thing"];
  check(
    "筛选下拉 = 全部组件键（非 core: 在前）",
    JSON.stringify(options) === JSON.stringify(wanted)
  );
  check("排序项含按组件", nodes(root, (n) => n.tag === "option" && n.props.value === "comp").length === 1);
  const toggle = nodes(root, (n) => n.tag === "button" && text(n).includes("放置实体"))[0];
  check("找到「放置实体」按钮", Boolean(toggle));
  await click(toggle);
  const createText = text(root);
  check("放置区：模板选项", createText.includes("商人模板") && createText.includes("worlditor_play_demo"));
  check(
    "放置区：能力组件输入（裸名由后端解析）",
    nodes(
      root,
      (n) => String(n.props && n.props.placeholder).includes("能力组件（可自由输入，裸名由后端解析）")
    ).length === 1
  );
  const datalist = nodes(root, (n) => n.tag === "datalist")[0];
  check("放置区：datalist 用 kinds.key", Boolean(datalist) && datalist.children.some((c) => c.props.value === "local:merchant"));
  check("放置区：组件选择器", createText.includes("＋ 已声明组件…"));
  check("放置区：FieldForm 新增组件", createText.includes("＋ 新增组件"));
  const row = nodes(root, (n) => n.tag === "tr" && text(n).includes("老张"))[0];
  check("找到实体行", Boolean(row));
  await click(row);
  const detail = text(root);
  check("详情：生效组件", detail.includes("生效组件：local:merchant"));
  check("详情：动作", detail.includes("动作：trade"));
  check("详情：字段按组件分组", detail.includes("local:merchant: 金币"));
  check("详情：组件选择器", detail.includes("＋ 已声明组件…"));
  check("详情：旧「类型（基底）」已删", !detail.includes("类型（基底）"));
  const detailPane = nodes(root, (n) => n.props && n.props.class === "detail")[0];
  check(
    "详情：声明字段回填 7",
    nodes(detailPane, (n) => n.tag === "input" && n.props.value === 7).length >= 1
  );
  check("详情：没有 core: 组件 chip（组件列只显示能力组件）", !detail.includes("组件 core:info（能力 = 组件的存在）"));
  const sortSelect = nodes(root, (n) => n.tag === "select" && n.children.some((c) => c.props.value === "comp"))[0];
  check("找到排序下拉", Boolean(sortSelect));
  await pickSelect(sortSelect, "comp");
  const rows = nodes(root, (n) => n.tag === "tr" && text(n).includes("老张")).length;
  check("按组件排序后仍能渲染", rows === 1);
}
async function checkFieldForm() {
  const emits = [];
  const components = {
    "core:info": { name: "老张", desc: "掌柜" },
    "worlditor_play_demo:apple": {},
    "local:merchant": { gold: 7, mood: "happy" },
    "zzz:ghost": { hp: 3 }
  };
  const Root = {
    render: () => h(FieldForm, { kinds, components, onUpdate: (v) => emits.push(v) })
  };
  const root = rootNode();
  createMiniApp(Root).mount(root);
  const blocks = nodes(root, (n) => {
    const summary = (n.children || []).find((c) => c.tag === "summary");
    return n.tag === "details" && summary && !text(summary).includes("新增组件");
  });
  check("四个组件块", blocks.length === 4);
  const order = blocks.map((b) => {
    const summary = b.children.find((c) => c.tag === "summary");
    return text(summary).split(" ")[0];
  });
  check(
    "块顺序 core → 玩法包 → local → 其他",
    JSON.stringify(order) === JSON.stringify(["core:info", "worlditor_play_demo:apple", "local:merchant", "zzz:ghost"])
  );
  function blockOf(key) {
    return nodes(root, (n) => {
      const summary = (n.children || []).find((c) => c.tag === "summary");
      return n.tag === "details" && summary && text(summary).startsWith(key);
    })[0];
  }
  function extraArea(key) {
    return nodes(blockOf(key), (n) => n.tag === "textarea")[0];
  }
  const extraJson = (key) => JSON.parse(extraArea(key).value || extraArea(key).props.value || "{}");
  check(
    "其余键不含声明字段（gold 不进 JSON 框）",
    extraJson("local:merchant").mood === "happy" && !("gold" in extraJson("local:merchant"))
  );
  check("未声明组件整块 JSON", JSON.stringify(extraJson("zzz:ghost")) === '{"hp":3}');
  check("core: 块也有 JSON 兜底", extraJson("core:info").name === "老张");
  check(
    "声明字段渲染控件",
    nodes(blockOf("local:merchant"), (n) => n.tag === "input" && n.props.value === 7).length === 1
  );
  setValue(extraArea("local:merchant"), "{");
  extraArea("local:merchant").props.onChange();
  await nextTick();
  check("JSON 写坏时不发（fail closed）", emits.length === 0);
  check("JSON 写坏时错误露在折叠区外", text(root).includes("JSON 解析失败"));
  const errorNode = nodes(root, (n) => n.tag === "p" && String(n.props.class).includes("error-text"))[0];
  check("错误在第一个组件块之前", Boolean(errorNode) && Boolean(errorNode.parent) && root.children.indexOf(errorNode.parent) < root.children.indexOf(root.children.find((c) => text(c).includes("core:info"))));
  setValue(extraArea("local:merchant"), '{"mood": "sad"}');
  extraArea("local:merchant").props.onChange();
  await nextTick();
  check("修好后发一次", emits.length === 1);
  const sent = emits.length ? emits[0].components : {};
  check(
    "组装：其余键 + 声明字段当前值",
    JSON.stringify(sent["local:merchant"]) === JSON.stringify({ mood: "sad", gold: 7 })
  );
  check("组装：其它组件原样带回", JSON.stringify(sent["zzz:ghost"]) === '{"hp":3}' && sent["core:info"].name === "老张");
}
async function main() {
  await checkEntityManager();
  await checkFieldForm();
  const vueWarnings = warnings.filter((w) => w.includes("[Vue warn]"));
  if (vueWarnings.length) failures.push(`Vue warn: ${vueWarnings.join(" | ")}`);
  if (failures.length) {
    console.error("FAIL:\n - " + failures.join("\n - "));
    process.exit(1);
  }
  console.log("INTERACT CHECK OK");
}
main();
