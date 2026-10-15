import { ref, computed, mergeProps, useSSRContext, reactive, watch, unref, createRenderer, nextTick, h } from "vue";
import { ssrRenderAttrs, ssrRenderList, ssrRenderClass, ssrRenderAttr, ssrInterpolate, ssrIncludeBooleanAttr, ssrRenderComponent, ssrLooseContain, ssrLooseEqual } from "vue/server-renderer";
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
const LOCAL$1 = "local";
const _sfc_main$3 = {
  __name: "ComponentPicker",
  __ssrInlineRender: true,
  props: {
    modelValue: { type: Array, default: () => [] },
    // 组件键列表
    kinds: { type: Array, default: () => [] }
    // 组件声明清单（{key, source, name, label, …}）
  },
  emits: ["update:modelValue"],
  setup(__props, { emit: __emit }) {
    const props = __props;
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
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<div${ssrRenderAttrs(mergeProps({ class: "component-picker" }, _attrs))} data-v-993a48d0><span class="label" data-v-993a48d0>组件</span><!--[-->`);
      ssrRenderList(__props.modelValue, (key, i) => {
        _push(`<span class="${ssrRenderClass([{ unknown: !specOf(key) }, "chip"])}"${ssrRenderAttr(
          "title",
          specOf(key) ? `已声明：${specOf(key).label || key}` : "虚构组件：没有声明，不贡献能力（允许存在）"
        )} data-v-993a48d0>${ssrInterpolate(labelOf(key))} `);
        if (specOf(key)) {
          _push(`<span class="src" data-v-993a48d0>来源 ${ssrInterpolate(specOf(key).source)}</span>`);
        } else {
          _push(`<!---->`);
        }
        _push(`<button class="x"${ssrRenderAttr("title", specOf(key) ? "移除组件（它的数据也一起删）" : "虚构组件：没有声明，不贡献任何能力")} data-v-993a48d0> × </button></span>`);
      });
      _push(`<!--]--><select class="mini"${ssrRenderAttr("value", "")} data-v-993a48d0><option value="" data-v-993a48d0>＋ 已声明组件…</option><!--[-->`);
      ssrRenderList(available.value, (k) => {
        _push(`<option${ssrRenderAttr("value", k.key)} data-v-993a48d0>${ssrInterpolate(k.label)}（${ssrInterpolate(k.key)} · 来源 ${ssrInterpolate(k.source)}） </option>`);
      });
      _push(`<!--]--></select><input${ssrRenderAttr("value", freeText.value)} class="mini"${ssrRenderAttr("placeholder", freePlaceholder.value)} data-v-993a48d0>`);
      if (freeError.value) {
        _push(`<span class="bad" data-v-993a48d0>${ssrInterpolate(freeError.value)}</span>`);
      } else {
        _push(`<!---->`);
      }
      _push(`</div>`);
    };
  }
};
const _sfc_setup$3 = _sfc_main$3.setup;
_sfc_main$3.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("src/components/editor/ComponentPicker.vue");
  return _sfc_setup$3 ? _sfc_setup$3(props, ctx) : void 0;
};
const ComponentPicker = /* @__PURE__ */ _export_sfc(_sfc_main$3, [["__scopeId", "data-v-993a48d0"]]);
const _sfc_main$2 = {
  __name: "FieldControl",
  __ssrInlineRender: true,
  props: {
    field: { type: Object, required: true },
    // {name,label,type,default?,source,play_id}
    modelValue: { type: [String, Number, Boolean], default: "" }
    // json 类型传 JSON 文本
  },
  emits: ["update:modelValue", "commit"],
  setup(__props, { emit: __emit }) {
    return (_ctx, _push, _parent, _attrs) => {
      let _temp0;
      if (__props.field.type === "str") {
        _push(`<input${ssrRenderAttrs(mergeProps({ value: __props.modelValue }, _attrs))} data-v-c45acfc3>`);
      } else if (__props.field.type === "int" || __props.field.type === "float") {
        _push(`<input${ssrRenderAttrs(mergeProps({
          value: __props.modelValue,
          type: "number",
          step: __props.field.type === "float" ? "any" : 1
        }, _attrs))} data-v-c45acfc3>`);
      } else if (__props.field.type === "bool") {
        _push(`<input${ssrRenderAttrs(mergeProps({
          type: "checkbox",
          checked: Boolean(__props.modelValue)
        }, _attrs))} data-v-c45acfc3>`);
      } else {
        _push(`<textarea${ssrRenderAttrs(_temp0 = mergeProps({
          value: __props.modelValue,
          rows: "2",
          placeholder: "JSON"
        }, _attrs), "textarea")} data-v-c45acfc3>${ssrInterpolate("value" in _temp0 ? _temp0.value : "")}</textarea>`);
      }
    };
  }
};
const _sfc_setup$2 = _sfc_main$2.setup;
_sfc_main$2.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("src/components/editor/FieldControl.vue");
  return _sfc_setup$2 ? _sfc_setup$2(props, ctx) : void 0;
};
const FieldControl = /* @__PURE__ */ _export_sfc(_sfc_main$2, [["__scopeId", "data-v-c45acfc3"]]);
reactive({
  open: false,
  title: "",
  text: "",
  detail: "",
  danger: false,
  confirmText: "确定",
  cancelText: "取消",
  _resolve: null
});
const LOCAL = "local";
const CORE = "core";
const _sfc_main$1 = {
  __name: "FieldForm",
  __ssrInlineRender: true,
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
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<div${ssrRenderAttrs(mergeProps({ class: "field-form" }, _attrs))} data-v-79111ac5>`);
      if (jsonError.value) {
        _push(`<p class="error-text" data-v-79111ac5>${ssrInterpolate(jsonError.value)}</p>`);
      } else {
        _push(`<!---->`);
      }
      _push(`<div class="comps" data-v-79111ac5><!--[-->`);
      ssrRenderList(componentList.value, (c) => {
        _push(`<details class="comp"${ssrIncludeBooleanAttr(c.name === justAdded.value || null) ? " open" : ""} data-v-79111ac5><summary data-v-79111ac5><code class="cname" data-v-79111ac5>${ssrInterpolate(c.name)}</code><span class="${ssrRenderClass([c.badgeClass, "chip"])}"${ssrRenderAttr("title", c.badgeTitle)} data-v-79111ac5>${ssrInterpolate(c.badge)}</span>`);
        if (c.fields.length) {
          _push(`<span class="dim" data-v-79111ac5>${ssrInterpolate(c.fields.length)} 个声明字段</span>`);
        } else {
          _push(`<!---->`);
        }
        if (c.extraCount) {
          _push(`<span class="bad" title="这个组件里没有声明过的键：不贡献任何能力，但会原样保存" data-v-79111ac5> 其余键 ${ssrInterpolate(c.extraCount)}</span>`);
        } else {
          _push(`<!---->`);
        }
        _push(`</summary><div class="comp-body" data-v-79111ac5>`);
        if (c.fields.length) {
          _push(`<div class="declared" data-v-79111ac5><!--[-->`);
          ssrRenderList(c.fields, (f) => {
            _push(`<div class="field" data-v-79111ac5><label${ssrRenderAttr("title", `${f.name}（${f.type}）—— 声明自组件 ${c.name}`)} data-v-79111ac5>${ssrInterpolate(f.label || f.name)}</label>`);
            _push(ssrRenderComponent(FieldControl, {
              field: f,
              "model-value": controlValue(c.name, f),
              "onUpdate:modelValue": (v) => setControl(c.name, f, v),
              onCommit: commit
            }, null, _parent));
            _push(`</div>`);
          });
          _push(`<!--]--></div>`);
        } else {
          _push(`<p class="tiny" data-v-79111ac5>这个组件没有声明任何字段（数据可以直接写在下面的 JSON 里）。</p>`);
        }
        _push(`<label class="tiny" data-v-79111ac5>其余键（未声明字段）—— 原始 JSON，整块替换本组件的数据</label><textarea rows="2" placeholder="{}" data-v-79111ac5>${ssrInterpolate(extraText[c.name])}</textarea><button class="mini-btn danger" data-v-79111ac5>删除组件</button></div></details>`);
      });
      _push(`<!--]-->`);
      if (!componentList.value.length) {
        _push(`<p class="dim" data-v-79111ac5> 这个实体还没有任何组件（没有必填组件，空字典也是合法状态）。 </p>`);
      } else {
        _push(`<!---->`);
      }
      _push(`</div><details class="new-comp" data-v-79111ac5><summary data-v-79111ac5>＋ 新增组件</summary><div class="new-row" data-v-79111ac5><input${ssrRenderAttr("value", newName.value)} class="mini" placeholder="组件键（如 stat → local:stat）" data-v-79111ac5><button class="btn" data-v-79111ac5>添加</button></div><p class="tiny" data-v-79111ac5> 组件键 = <code data-v-79111ac5>来源:名字</code>：<code data-v-79111ac5>core:</code> 内核保留、玩法包用自己的 id、 编辑器手写用 <code data-v-79111ac5>local:</code>。只允许字母/数字/下划线/点/连字符，且必须含一个冒号 （不含冒号时自动补 <code data-v-79111ac5>local:</code>）。 </p><label class="tiny" data-v-79111ac5>数据 JSON</label><textarea rows="2" placeholder="{&quot;gold&quot;: 120}" data-v-79111ac5>${ssrInterpolate(newJson.value)}</textarea>`);
      if (newError.value) {
        _push(`<p class="error-text" data-v-79111ac5>${ssrInterpolate(newError.value)}</p>`);
      } else {
        _push(`<!---->`);
      }
      _push(`</details></div>`);
    };
  }
};
const _sfc_setup$1 = _sfc_main$1.setup;
_sfc_main$1.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("src/components/editor/FieldForm.vue");
  return _sfc_setup$1 ? _sfc_setup$1(props, ctx) : void 0;
};
const FieldForm = /* @__PURE__ */ _export_sfc(_sfc_main$1, [["__scopeId", "data-v-79111ac5"]]);
const _sfc_main = {
  __name: "EntityManager",
  __ssrInlineRender: true,
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
    function withKeys(components, keys) {
      const out = {};
      for (const key of keys) {
        out[key] = Object.prototype.hasOwnProperty.call(components || {}, key) ? components[key] : {};
      }
      return out;
    }
    function setDraftKeys(keys) {
      draft.components = withKeys(draft.components, keys);
    }
    function setEditKeys(keys) {
      edit.components = withKeys(edit.components, keys);
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
    __expose({
      setError: (msg) => error.value = msg,
      focus: (id) => {
        selectedId.value = id;
        const e = props.entities.find((x) => x.id === id);
        if (e) select(e);
      }
    });
    return (_ctx, _push, _parent, _attrs) => {
      _push(`<div${ssrRenderAttrs(mergeProps({ class: "entity-manager" }, _attrs))} data-v-fa37c2a8><div class="toolbar" data-v-fa37c2a8><input${ssrRenderAttr("value", q.value)} class="mini search" placeholder="搜索名称 / 组件 / id…" data-v-fa37c2a8><select class="mini" data-v-fa37c2a8><option value="" data-v-fa37c2a8${ssrIncludeBooleanAttr(Array.isArray(componentFilter.value) ? ssrLooseContain(componentFilter.value, "") : ssrLooseEqual(componentFilter.value, "")) ? " selected" : ""}>全部组件</option><!--[-->`);
      ssrRenderList(componentOptions.value, (k) => {
        _push(`<option${ssrRenderAttr("value", k)} data-v-fa37c2a8${ssrIncludeBooleanAttr(Array.isArray(componentFilter.value) ? ssrLooseContain(componentFilter.value, k) : ssrLooseEqual(componentFilter.value, k)) ? " selected" : ""}>${ssrInterpolate(k)}</option>`);
      });
      _push(`<!--]--></select><select class="mini" data-v-fa37c2a8><option value="pos" data-v-fa37c2a8${ssrIncludeBooleanAttr(Array.isArray(sort.value) ? ssrLooseContain(sort.value, "pos") : ssrLooseEqual(sort.value, "pos")) ? " selected" : ""}>按位置</option><option value="name" data-v-fa37c2a8${ssrIncludeBooleanAttr(Array.isArray(sort.value) ? ssrLooseContain(sort.value, "name") : ssrLooseEqual(sort.value, "name")) ? " selected" : ""}>按名称</option><option value="comp" data-v-fa37c2a8${ssrIncludeBooleanAttr(Array.isArray(sort.value) ? ssrLooseContain(sort.value, "comp") : ssrLooseEqual(sort.value, "comp")) ? " selected" : ""}>按组件</option></select>`);
      if (__props.tileFilter) {
        _push(`<label class="mini-label pinned" data-v-fa37c2a8><input type="checkbox"${ssrIncludeBooleanAttr(Array.isArray(tileOnly.value) ? ssrLooseContain(tileOnly.value, null) : tileOnly.value) ? " checked" : ""} data-v-fa37c2a8> 只看地块 (${ssrInterpolate(__props.tileFilter.row)}, ${ssrInterpolate(__props.tileFilter.col)}) </label>`);
      } else {
        _push(`<!---->`);
      }
      _push(`<span class="grow" data-v-fa37c2a8></span><span class="dim" data-v-fa37c2a8>${ssrInterpolate(filtered.value.length)} 个实体</span><button class="btn" data-v-fa37c2a8>${ssrInterpolate(showCreate.value ? "收起放置" : "＋ 放置实体")}</button></div>`);
      if (showCreate.value) {
        _push(`<div class="create" data-v-fa37c2a8><div class="row" data-v-fa37c2a8><select class="mini" data-v-fa37c2a8><option value="" data-v-fa37c2a8${ssrIncludeBooleanAttr(Array.isArray(draft.template_id) ? ssrLooseContain(draft.template_id, "") : ssrLooseEqual(draft.template_id, "")) ? " selected" : ""}>（不用模板）</option><!--[-->`);
        ssrRenderList(__props.entityTemplates, (t) => {
          _push(`<option${ssrRenderAttr("value", t.id)} data-v-fa37c2a8${ssrIncludeBooleanAttr(Array.isArray(draft.template_id) ? ssrLooseContain(draft.template_id, t.id) : ssrLooseEqual(draft.template_id, t.id)) ? " selected" : ""}>${ssrInterpolate(t.name)}${ssrInterpolate(t.source === "play" ? `（${t.play_id}）` : "")}</option>`);
        });
        _push(`<!--]--></select><input${ssrRenderAttr("value", draft.ability)} class="mini" list="component-options" placeholder="能力组件（可自由输入，裸名由后端解析）" data-v-fa37c2a8><datalist id="component-options" data-v-fa37c2a8><!--[-->`);
        ssrRenderList(__props.kinds, (k) => {
          _push(`<option${ssrRenderAttr("value", k.key)} data-v-fa37c2a8>${ssrInterpolate(k.label)}</option>`);
        });
        _push(`<!--]--></datalist><input${ssrRenderAttr("value", draft.name)} class="mini" placeholder="名称（默认取组件文案）" data-v-fa37c2a8>`);
        if (__props.allowAbsent) {
          _push(`<!--[--><label class="mini-label" title="不勾 = 造一个不在世界上的实体（先造出来，之后再放）" data-v-fa37c2a8><input${ssrIncludeBooleanAttr(Array.isArray(draft.place) ? ssrLooseContain(draft.place, null) : draft.place) ? " checked" : ""} type="checkbox" data-v-fa37c2a8> 放进世界 </label>`);
          if (draft.place) {
            _push(`<!--[--><span class="dim" data-v-fa37c2a8>@</span><input${ssrRenderAttr("value", draft.row)} type="number" class="num" placeholder="行" data-v-fa37c2a8><input${ssrRenderAttr("value", draft.col)} type="number" class="num" placeholder="列" data-v-fa37c2a8><!--]-->`);
          } else {
            _push(`<span class="dim" data-v-fa37c2a8>不在世界上</span>`);
          }
          _push(`<!--]-->`);
        } else {
          _push(`<!--[--><span class="dim" data-v-fa37c2a8>@</span><input${ssrRenderAttr("value", draft.row)} type="number" class="num" placeholder="行" data-v-fa37c2a8><input${ssrRenderAttr("value", draft.col)} type="number" class="num" placeholder="列" data-v-fa37c2a8><!--]-->`);
        }
        _push(`<button class="btn" data-v-fa37c2a8>${ssrInterpolate(draft.place ? "放置" : "创建")}</button></div>`);
        _push(ssrRenderComponent(ComponentPicker, {
          "model-value": draftKeys.value,
          kinds: __props.kinds,
          "onUpdate:modelValue": setDraftKeys
        }, null, _parent));
        _push(ssrRenderComponent(FieldForm, {
          kinds: __props.kinds,
          components: draft.components,
          onUpdate: (v) => draft.components = v.components
        }, null, _parent));
        _push(`</div>`);
      } else {
        _push(`<!---->`);
      }
      if (error.value) {
        _push(`<p class="error-text" data-v-fa37c2a8>${ssrInterpolate(error.value)}</p>`);
      } else {
        _push(`<!---->`);
      }
      _push(`<div class="split" data-v-fa37c2a8><div class="list-wrap" data-v-fa37c2a8><table class="table tight" data-v-fa37c2a8><thead data-v-fa37c2a8><tr data-v-fa37c2a8><th data-v-fa37c2a8>名称</th><th data-v-fa37c2a8>组件</th><th data-v-fa37c2a8>位置</th><th data-v-fa37c2a8>能力</th><th class="ops-col" data-v-fa37c2a8>操作</th></tr></thead><tbody data-v-fa37c2a8><!--[-->`);
      ssrRenderList(pageItems.value, (e) => {
        var _a, _b, _c, _d, _e, _f;
        _push(`<tr class="${ssrRenderClass({ on: selectedId.value === e.id })}" data-v-fa37c2a8><td data-v-fa37c2a8><span class="name" data-v-fa37c2a8>${ssrInterpolate(unref(entityName)(e))}</span>`);
        if (unref(entityDesc)(e)) {
          _push(`<div class="dim ell" data-v-fa37c2a8>${ssrInterpolate(unref(entityDesc)(e))}</div>`);
        } else {
          _push(`<!---->`);
        }
        _push(`</td><td class="comp-cell" data-v-fa37c2a8>`);
        if (!unref(abilityComponents)(e).length) {
          _push(`<span class="dim" data-v-fa37c2a8>—</span>`);
        } else {
          _push(`<!---->`);
        }
        _push(`<!--[-->`);
        ssrRenderList(unref(abilityComponents)(e), (k) => {
          _push(`<span class="${ssrRenderClass([{ bad: isUnknown(e, k) }, "chip"])}"${ssrRenderAttr(
            "title",
            isUnknown(e, k) ? "虚构组件：没有声明，不贡献能力" : `组件 ${k}（能力 = 组件的存在）`
          )} data-v-fa37c2a8>${ssrInterpolate(k)}</span>`);
        });
        _push(`<!--]--></td><td class="dim" data-v-fa37c2a8>${ssrInterpolate(unref(positionLabel)(e))}</td><td class="caps-cell" data-v-fa37c2a8><!--[-->`);
        ssrRenderList((((_a = e.capabilities) == null ? void 0 : _a.interactions) || []).slice(0, 2), (a) => {
          _push(`<span class="chip" data-v-fa37c2a8>${ssrInterpolate(a)}</span>`);
        });
        _push(`<!--]-->`);
        if ((((_b = e.capabilities) == null ? void 0 : _b.interactions) || []).length > 2) {
          _push(`<span class="dim" data-v-fa37c2a8> +${ssrInterpolate(e.capabilities.interactions.length - 2)}</span>`);
        } else {
          _push(`<!---->`);
        }
        if ((_d = (_c = e.capabilities) == null ? void 0 : _c.unknown_components) == null ? void 0 : _d.length) {
          _push(`<span class="chip bad" title="虚构组件：没有声明，不贡献能力" data-v-fa37c2a8> ⚠${ssrInterpolate(e.capabilities.unknown_components.length)}</span>`);
        } else {
          _push(`<!---->`);
        }
        if ((_f = (_e = e.capabilities) == null ? void 0 : _e.inactive_components) == null ? void 0 : _f.length) {
          _push(`<span class="chip bad" title="有声明，但它所属的玩法包在本世界未启用" data-v-fa37c2a8> ⏸${ssrInterpolate(e.capabilities.inactive_components.length)}</span>`);
        } else {
          _push(`<!---->`);
        }
        _push(`</td><td class="ops-col" data-v-fa37c2a8><button class="mini-btn"${ssrIncludeBooleanAttr(!unref(hasPosition)(e)) ? " disabled" : ""}${ssrRenderAttr(
          "title",
          unref(hasPosition)(e) ? "在地图上选中它所在的地块" : "它不在世界上（没有 core:position），没有地块可定位"
        )} data-v-fa37c2a8> 定位 </button><button class="mini-btn danger" data-v-fa37c2a8>删除</button></td></tr>`);
      });
      _push(`<!--]-->`);
      if (!filtered.value.length) {
        _push(`<tr data-v-fa37c2a8><td colspan="5" class="dim" data-v-fa37c2a8>${ssrInterpolate(__props.tileFilter && tileOnly.value ? "这个地块上没有实体。" : "没有匹配的实体。")}</td></tr>`);
      } else {
        _push(`<!---->`);
      }
      _push(`</tbody></table>`);
      if (pages.value > 1) {
        _push(`<div class="pager" data-v-fa37c2a8><button class="mini-btn"${ssrIncludeBooleanAttr(page.value <= 1) ? " disabled" : ""} data-v-fa37c2a8>‹ 上一页</button><span class="dim" data-v-fa37c2a8>第 ${ssrInterpolate(page.value)} / ${ssrInterpolate(pages.value)} 页</span><button class="mini-btn"${ssrIncludeBooleanAttr(page.value >= pages.value) ? " disabled" : ""} data-v-fa37c2a8>下一页 ›</button><select class="mini" data-v-fa37c2a8><option${ssrRenderAttr("value", 50)} data-v-fa37c2a8${ssrIncludeBooleanAttr(Array.isArray(pageSize.value) ? ssrLooseContain(pageSize.value, 50) : ssrLooseEqual(pageSize.value, 50)) ? " selected" : ""}>50 / 页</option><option${ssrRenderAttr("value", 100)} data-v-fa37c2a8${ssrIncludeBooleanAttr(Array.isArray(pageSize.value) ? ssrLooseContain(pageSize.value, 100) : ssrLooseEqual(pageSize.value, 100)) ? " selected" : ""}>100 / 页</option><option${ssrRenderAttr("value", 200)} data-v-fa37c2a8${ssrIncludeBooleanAttr(Array.isArray(pageSize.value) ? ssrLooseContain(pageSize.value, 200) : ssrLooseEqual(pageSize.value, 200)) ? " selected" : ""}>200 / 页</option></select></div>`);
      } else {
        _push(`<!---->`);
      }
      _push(`</div><aside class="detail" data-v-fa37c2a8>`);
      if (current.value) {
        _push(`<!--[--><div class="detail-head" data-v-fa37c2a8><b data-v-fa37c2a8>实体详情</b><code class="dim" data-v-fa37c2a8>${ssrInterpolate(current.value.id.slice(0, 8))}</code></div><label class="field" data-v-fa37c2a8> 名称 <input${ssrRenderAttr("value", edit.name)}${ssrRenderAttr("placeholder", `未设名字 → 显示 ${current.value.id.slice(0, 8)}（core:info.name）`)} data-v-fa37c2a8></label><label class="field" data-v-fa37c2a8> 描述 <textarea rows="2" placeholder="core:info.desc（可留空）" data-v-fa37c2a8>${ssrInterpolate(edit.desc)}</textarea></label>`);
        _push(ssrRenderComponent(ComponentPicker, {
          "model-value": editKeys.value,
          kinds: __props.kinds,
          "onUpdate:modelValue": setEditKeys
        }, null, _parent));
        _push(ssrRenderComponent(FieldForm, {
          kinds: __props.kinds,
          components: edit.components,
          onUpdate: (v) => edit.components = v.components
        }, null, _parent));
        if (current.value.capabilities) {
          _push(`<div class="caps" data-v-fa37c2a8><b data-v-fa37c2a8>合并后的能力</b><div data-v-fa37c2a8>生效组件：${ssrInterpolate(current.value.capabilities.active_components.join("、") || "（无）")}</div>`);
          if (current.value.capabilities.inactive_components.length) {
            _push(`<div class="bad" data-v-fa37c2a8> 本世界未启用：${ssrInterpolate(current.value.capabilities.inactive_components.join("、"))} （有声明，但该玩法包在本世界没启用） </div>`);
          } else {
            _push(`<!---->`);
          }
          if (current.value.capabilities.unknown_components.length) {
            _push(`<div class="bad" data-v-fa37c2a8> 没有声明：${ssrInterpolate(current.value.capabilities.unknown_components.join("、"))} （虚构组件，不贡献能力） </div>`);
          } else {
            _push(`<!---->`);
          }
          _push(`<div data-v-fa37c2a8>动作：${ssrInterpolate(current.value.capabilities.interactions.join("、") || "（无）")}</div>`);
          if (fieldGroups.value.length) {
            _push(`<div data-v-fa37c2a8> 字段： <!--[-->`);
            ssrRenderList(fieldGroups.value, (g) => {
              _push(`<div class="fields-row" data-v-fa37c2a8><code data-v-fa37c2a8>${ssrInterpolate(g.key)}</code>: ${ssrInterpolate(g.names)}</div>`);
            });
            _push(`<!--]--></div>`);
          } else {
            _push(`<div data-v-fa37c2a8>字段：（无）</div>`);
          }
          _push(`</div>`);
        } else {
          _push(`<!---->`);
        }
        _push(`<div class="detail-ops" data-v-fa37c2a8><button class="btn" data-v-fa37c2a8>保存</button><button class="mini-btn" data-v-fa37c2a8>存为模板</button><button class="mini-btn"${ssrIncludeBooleanAttr(!unref(hasPosition)(current.value)) ? " disabled" : ""} data-v-fa37c2a8> 定位 </button><button class="mini-btn danger" data-v-fa37c2a8>删除</button></div><!--]-->`);
      } else {
        _push(`<p class="dim" data-v-fa37c2a8>从左边选一个实体查看/编辑详情；也可以用上方的「放置实体」新建。</p>`);
      }
      _push(`</aside></div></div>`);
    };
  }
};
const _sfc_setup = _sfc_main.setup;
_sfc_main.setup = (props, ctx) => {
  const ssrContext = useSSRContext();
  (ssrContext.modules || (ssrContext.modules = /* @__PURE__ */ new Set())).add("src/components/editor/EntityManager.vue");
  return _sfc_setup ? _sfc_setup(props, ctx) : void 0;
};
const EntityManager = /* @__PURE__ */ _export_sfc(_sfc_main, [["__scopeId", "data-v-fa37c2a8"]]);
const warnings = [];
const realWarn = console.warn;
console.warn = (...args) => {
  warnings.push(args.join(" "));
  realWarn(...args);
};
const nodeOps = {
  createElement: (tag) => ({ tag, children: [], props: {}, parent: null }),
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
  }
};
const { createApp: createMiniApp } = createRenderer(nodeOps);
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
  node.props.onInput({ target: { value } });
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
  setValue(sortSelect, "comp");
  await nextTick();
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
  check("其余键不含声明字段（gold 不进 JSON 框）", JSON.parse(extraArea("local:merchant").props.value).mood === "happy" && !("gold" in JSON.parse(extraArea("local:merchant").props.value)));
  check("未声明组件整块 JSON", JSON.stringify(JSON.parse(extraArea("zzz:ghost").props.value)) === '{"hp":3}');
  check("core: 块也有 JSON 兜底", JSON.parse(extraArea("core:info").props.value).name === "老张");
  check("声明字段渲染控件", nodes(blockOf("local:merchant"), (n) => n.tag === "input" && n.props.value === 7).length === 1);
  setValue(extraArea("local:merchant"), "{");
  extraArea("local:merchant").props.onChange();
  await nextTick();
  check("JSON 写坏时不发（fail closed）", emits.length === 0);
  check("JSON 写坏时错误露在折叠区外", text(root).includes("JSON 解析失败"));
  const errorNode = nodes(root, (n) => n.props && String(n.props.class).includes("error-text"))[0];
  check("错误在第一个块之前", Boolean(errorNode) && root.children.indexOf(errorNode) < root.children.indexOf(blockOf("core:info").parent || blockOf("core:info")));
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
