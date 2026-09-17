<template>
  <!-- 字段表单（D9/D23）：声明过的字段按 schema 渲染控件，未声明字段走原始 JSON 兜底 -->
  <div class="field-form">
    <div v-if="fields.length" class="declared">
      <div v-for="f in fields" :key="f.name" class="field">
        <label :title="`${f.name}（${f.type}${f.source ? ' · 来自 ' + f.source : ''}）`">
          {{ f.label || f.name }}
        </label>
        <input v-if="f.type === 'str'" v-model="values[f.name]" @change="push" />
        <input
          v-else-if="f.type === 'int' || f.type === 'float'"
          v-model.number="values[f.name]"
          type="number"
          :step="f.type === 'float' ? 'any' : 1"
          @change="push"
        />
        <input
          v-else-if="f.type === 'bool'"
          v-model="values[f.name]"
          type="checkbox"
          @change="push"
        />
        <textarea
          v-else
          v-model="complex[f.name]"
          rows="2"
          placeholder="JSON"
          @change="pushComplex(f)"
        ></textarea>
      </div>
    </div>
    <p v-else class="dim">这个类型没有声明任何字段（可直接在下面的原始 JSON 里写）。</p>

    <details class="raw" :open="Boolean(extraKeys.length)">
      <summary>
        原始数据
        <span v-if="extraKeys.length" class="bad">未声明字段 {{ extraKeys.length }} 个</span>
      </summary>
      <label class="tiny">attrs（玩法数据容器）</label>
      <textarea v-model="attrsJson" rows="3" @change="pushRaw('attrs')"></textarea>
      <label class="tiny">
        state（动态状态：<code>block_move</code> 可动态改挡路、<code>invisible</code> 隐身）
      </label>
      <textarea v-model="stateJson" rows="3" @change="pushRaw('state')"></textarea>
      <p v-if="jsonError" class="error-text">{{ jsonError }}</p>
    </details>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue";

const props = defineProps({
  kinds: { type: Array, default: () => [] },
  kind: { type: String, default: "" },
  tags: { type: Array, default: () => [] },
  attrs: { type: Object, default: () => ({}) },
  state: { type: Object, default: () => ({}) },
});
const emit = defineEmits(["update"]);

const values = reactive({});
const complex = reactive({});
const attrsJson = ref("{}");
const stateJson = ref("{}");
const jsonError = ref("");

/** 有效字段 = 类型（含预设标签）→ 实例标签，逐个合并（同名后者覆盖）。 */
const fields = computed(() => {
  const names = [...new Set([props.kind, ...presetOf(), ...props.tags])];
  const merged = new Map();
  for (const name of names) {
    const spec = props.kinds.find((k) => k.tag === name);
    if (!spec) continue;
    for (const f of spec.fields || []) {
      merged.set(f.name, { ...f, source: name });
    }
  }
  return [...merged.values()];
});

function presetOf() {
  const spec = props.kinds.find((k) => k.tag === props.kind);
  return spec?.preset_tags || [];
}

const declaredNames = computed(() => fields.value.map((f) => f.name));
const extraKeys = computed(() =>
  Object.keys(props.attrs || {}).filter((k) => !declaredNames.value.includes(k))
);

function syncFromProps() {
  const names = declaredNames.value;
  for (const key of Object.keys(values)) {
    if (!names.includes(key)) delete values[key];
  }
  for (const f of fields.value) {
    const has = Object.prototype.hasOwnProperty.call(props.attrs || {}, f.name);
    if (f.type === "json") {
      complex[f.name] = has ? JSON.stringify(props.attrs[f.name]) : JSON.stringify(f.default ?? {});
      values[f.name] = undefined;
    } else if (has) {
      values[f.name] = props.attrs[f.name];
    } else {
      values[f.name] = f.default !== undefined ? f.default : defaultFor(f.type);
    }
  }
  const extra = {};
  for (const key of extraKeys.value) extra[key] = props.attrs[key];
  attrsJson.value = JSON.stringify(extra, null, 2);
  stateJson.value = JSON.stringify(props.state || {}, null, 2);
  jsonError.value = "";
}

function defaultFor(type) {
  if (type === "int" || type === "float") return 0;
  if (type === "bool") return false;
  return "";
}

function buildAttrs() {
  const extra = parseJson(attrsJson.value);
  if (extra === null) return null;
  const out = { ...extra };
  for (const f of fields.value) {
    if (f.type === "json") {
      const parsed = parseJson(complex[f.name] || "null");
      if (parsed === null && (complex[f.name] || "").trim() && (complex[f.name] || "").trim() !== "null") {
        jsonError.value = `字段「${f.label || f.name}」不是合法 JSON`;
        return null;
      }
      out[f.name] = parsed;
    } else if (values[f.name] !== undefined) {
      out[f.name] = values[f.name];
    }
  }
  return out;
}

function parseJson(text) {
  const raw = (text || "").trim();
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw);
    if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
      jsonError.value = "必须是一个 JSON 对象";
      return null;
    }
    return parsed;
  } catch (e) {
    jsonError.value = `JSON 解析失败：${e.message}`;
    return null;
  }
}

function push() {
  const attrs = buildAttrs();
  if (attrs === null) return;
  jsonError.value = "";
  emit("update", { attrs, state: parseJson(stateJson.value) || {} });
}

function pushComplex(f) {
  jsonError.value = "";
  push();
  void f;
}

function pushRaw(which) {
  if (which === "state") {
    const state = parseJson(stateJson.value);
    if (state === null) return;
    jsonError.value = "";
    emit("update", { attrs: buildAttrs() || {}, state });
    return;
  }
  push();
}

watch(() => [props.kind, props.tags, props.attrs, props.state], syncFromProps, {
  immediate: true,
});
</script>

<style scoped>
.field-form {
  margin: 4px 0;
}
.declared {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 12px;
  color: var(--text-dim);
}
.field input[type="text"],
.field input:not([type]),
.field input[type="number"],
.field textarea {
  padding: 4px 6px;
  border-radius: 6px;
  border: 1px solid var(--bg-3);
  background: var(--bg);
  color: var(--text);
  font-size: 13px;
  min-width: 120px;
}
.field input[type="checkbox"] {
  align-self: flex-start;
}
.raw {
  margin-top: 6px;
  font-size: 12px;
  color: var(--text-dim);
}
.raw textarea {
  width: 100%;
  padding: 6px 8px;
  border-radius: 6px;
  border: 1px solid var(--bg-3);
  background: var(--bg);
  color: var(--text);
  font-family: ui-monospace, monospace;
  font-size: 12px;
  margin-bottom: 4px;
}
.tiny {
  display: block;
  font-size: 11px;
  margin-top: 4px;
}
.bad {
  color: var(--danger);
}
.dim {
  color: var(--text-dim);
  font-size: 13px;
}
</style>
