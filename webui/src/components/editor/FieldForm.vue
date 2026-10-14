<template>
  <!-- 组件化字段表单（实体模型 v2 / D32–D34）：实体数据只有一种单位——
       组件字典 components（组件名 = `source:name` 信封）。v2 之前这里是
       attrs / state 两个扁平容器 + 两个大 JSON 框，现在改成：
         1) 顶部按声明字段 schema 渲染控件（声明字段仍来自 kind / 预设 / 实例标签）；
         2) 下面每个组件一块（可折叠）：命中的声明字段用控件，其余键走原始 JSON 兜底；
         3) 可以新增组件（名字不含冒号自动补 local:）、也可以删掉整个组件。 -->
  <div class="field-form">
    <div v-if="fields.length" class="declared">
      <div v-for="f in fields" :key="f.name" class="field">
        <label :title="fieldTitle(f)">
          {{ f.label || f.name }}
          <span class="where" :class="{ loose: !isDocked(f) }">
            {{ isDocked(f) ? `@${homeOf(f)}` : `→ ${homeOf(f)}` }}
          </span>
        </label>
        <FieldControl
          :field="f"
          :model-value="controlValue(f)"
          @update:model-value="(v) => setControl(f, v)"
          @commit="commit"
        />
      </div>
    </div>
    <p v-else class="dim">这个类型没有声明任何字段（可直接在下面的组件里写）。</p>

    <!-- 错误必须露在折叠区外面：v0.5.2 之前它藏在折叠区里，JSON 写坏时
         "改一个字段"会把另一袋数据静默清空，用户既看不到报错也看不到数据没了 -->
    <p v-if="jsonError" class="error-text">{{ jsonError }}</p>

    <div class="comps">
      <details
        v-for="c in componentList"
        :key="c.name"
        class="comp"
        :open="c.name === justAdded || null"
      >
        <summary>
          <code class="cname">{{ c.name }}</code>
          <span class="chip" :class="c.badgeClass" :title="c.badgeTitle">{{ c.badge }}</span>
          <span v-if="c.homed.length" class="dim">{{ c.homed.length }} 个声明字段</span>
          <span v-if="c.extra.length" class="bad" title="没有声明过的键：不贡献任何能力，但会原样保存">
            未声明 {{ c.extra.length }}
          </span>
          <span v-if="c.dups.length" class="warn" :title="`这些键的落点在别的组件里：${c.dups.join('、')}`">
            重名 {{ c.dups.length }}
          </span>
        </summary>
        <div class="comp-body">
          <div v-if="c.homed.length" class="declared">
            <div v-for="f in c.homed" :key="f.name" class="field">
              <label>{{ f.label || f.name }}</label>
              <FieldControl
                :field="f"
                :model-value="controlValue(f)"
                @update:model-value="(v) => setControl(f, v)"
                @commit="commit"
              />
            </div>
          </div>
          <label class="tiny">
            其余键（未声明字段 / 重名键）—— 原始 JSON，整块替换本组件
          </label>
          <textarea
            v-model="compText[c.name]"
            rows="2"
            placeholder="{}"
            @change="commit"
          ></textarea>
          <button class="mini-btn danger" @click="dropComponent(c.name)">删除组件</button>
        </div>
      </details>
      <p v-if="!componentList.length" class="dim">
        这个实体还没有任何组件（v2 里没有必填组件，空字典也是合法状态）。
      </p>
    </div>

    <details class="new-comp">
      <summary>＋ 新增组件</summary>
      <div class="new-row">
        <input
          v-model="newName"
          class="mini"
          placeholder="组件名（如 stat → local:stat）"
          @keydown.enter.prevent="addComponent"
        />
        <button class="btn" @click="addComponent">添加</button>
      </div>
      <p class="tiny">
        组件名 = <code>来源:名字</code>：<code>core:</code> 内核保留、玩法包用自己的 id、
        编辑器手写用 <code>local:</code>。只允许字母/数字/下划线/点/连字符，且必须含一个冒号
        （不含冒号时自动补 <code>local:</code>）。
      </p>
      <label class="tiny">数据 JSON</label>
      <textarea v-model="newJson" rows="2" placeholder='{"gold": 120}'></textarea>
      <p v-if="newError" class="error-text">{{ newError }}</p>
    </details>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue";
import FieldControl from "./FieldControl.vue";
import { askConfirm } from "../../confirm";

const props = defineProps({
  kinds: { type: Array, default: () => [] },
  kind: { type: String, default: "" },
  tags: { type: Array, default: () => [] },
  components: { type: Object, default: () => ({}) }, // 组件名 → 数据对象
});
const emit = defineEmits(["update"]);

// 组件名信封：source 与 name 各允许字母/数字/下划线/点/连字符（与内核
// split_component_key 的 _COMPONENT_PART_RE 同一口径），且必须有一个冒号。
const COMPONENT_RE = /^[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+$/;
const LOCAL = "local";

const values = reactive({}); // 声明字段（非 json）：字段名 → 值
const complex = reactive({}); // 声明字段（json）：字段名 → JSON 文本
const compText = reactive({}); // 组件名 → 该组件「其余键」的 JSON 文本
const jsonError = ref("");
const newName = ref("");
const newJson = ref("{}");
const newError = ref("");
const justAdded = ref(""); // 刚新增的组件默认展开（其余折叠）

/** 有效字段 = 类型（含预设标签）→ 实例标签，逐个合并（同名后者覆盖）。 */
const fields = computed(() => {
  const names = [...new Set([props.kind, ...presetOf(), ...props.tags])];
  const merged = new Map();
  for (const name of names) {
    const spec = props.kinds.find((k) => k.tag === name);
    if (!spec) continue;
    for (const f of spec.fields || []) {
      // source = 声明它的标签；play_id = 声明者所属玩法包（空 = 本地/内核注册）
      merged.set(f.name, { ...f, source: name, play_id: spec.play_id || "" });
    }
  }
  return [...merged.values()];
});

function presetOf() {
  const spec = props.kinds.find((k) => k.tag === props.kind);
  return spec?.preset_tags || [];
}

const declaredNames = computed(() => fields.value.map((f) => f.name));
const compNames = computed(() => Object.keys(props.components || {}));
const knownPlayIds = computed(
  () => new Set(props.kinds.map((k) => k.play_id).filter(Boolean))
);

/** 组件显示顺序：core → 玩法包 → local → 其他；同类按名字排（稳定，不随编辑跳动）。 */
function rankOf(name) {
  const source = String(name).split(":")[0];
  if (source === "core") return 0;
  if (knownPlayIds.value.has(source)) return 1;
  if (source === LOCAL) return 2;
  return 3;
}
const ordered = computed(() =>
  [...compNames.value].sort((a, b) => rankOf(a) - rankOf(b) || a.localeCompare(b))
);

function has(compName, key) {
  const data = props.components ? props.components[compName] : null;
  return Boolean(data) && Object.prototype.hasOwnProperty.call(data, key);
}

function declaredField(name) {
  return fields.value.find((f) => f.name === name) || null;
}

/**
 * 声明字段的落点：
 * 1. 已经在某个组件里 → 就写回那个组件（同名出现在多个组件时取显示序第一个，块头会标「重名」）；
 * 2. 还不存在于任何组件 → 按**声明它的标签**落地：`<来源包|local>:<标签>`
 *    （例如本地注册的标签 merchant 声明的 gold → local:merchant）。
 */
function homeOf(f) {
  const found = ordered.value.find((n) => has(n, f.name));
  return found || fallbackName(f);
}

function fallbackName(f) {
  // 声明它的标签名可能带空格之类的不合法字符（内核注册标签只要求非空）——
  // 组不出合法信封就落到 local:fields，别让整次保存被后端拒绝
  const candidate = `${f.play_id || LOCAL}:${f.source}`;
  return COMPONENT_RE.test(candidate) ? candidate : `${LOCAL}:fields`;
}

function isDocked(f) {
  return compNames.value.some((n) => has(n, f.name));
}

function fieldTitle(f) {
  const home = homeOf(f);
  const spec = `${f.name}（${f.type}${f.source ? " · 声明自 " + f.source : ""}${
    f.play_id ? " · 玩法包 " + f.play_id : ""
  }）`;
  if (!isDocked(f)) {
    return `${spec}\n还没落进任何组件：改动会写进 ${home}（按声明它的标签落地）`;
  }
  const homes = compNames.value.filter((n) => has(n, f.name));
  return `${spec}\n当前在组件：${homes.join("、")}`;
}

const componentList = computed(() =>
  ordered.value.map((name) => {
    const data = props.components[name] || {};
    const homed = [];
    const dups = [];
    let extra = 0;
    for (const key of Object.keys(data)) {
      const f = declaredField(key);
      if (!f) extra += 1;
      else if (homeOf(f) === name) homed.push(f);
      else dups.push(key);
    }
    return { name, homed, dups, extra, ...badgeOf(name) };
  })
);

/** 来源标记：core → 内核保留；已知玩法包 → 该来源包；没有声明 → 未声明组件。 */
function badgeOf(name) {
  const source = String(name).split(":")[0];
  if (source === "core") {
    return {
      badge: "内核保留",
      badgeClass: "core",
      badgeTitle: "core: 是内核保留命名空间（玩法包不得写入）",
    };
  }
  if (knownPlayIds.value.has(source)) {
    return {
      badge: `玩法包 ${source}`,
      badgeClass: "play",
      badgeTitle: `来源包：${source}`,
    };
  }
  const spec = props.kinds.find((k) => k.tag === name);
  if (spec) {
    return {
      badge: "已声明",
      badgeClass: "decl",
      badgeTitle: `已声明：${spec.label || spec.tag}`,
    };
  }
  return {
    badge: "未声明组件",
    badgeClass: "und",
    badgeTitle: "没有对应声明：不贡献任何能力（虚构组件，允许存在）",
  };
}

function defaultFor(type) {
  if (type === "int" || type === "float") return 0;
  if (type === "bool") return false;
  return "";
}

function fieldDefault(f) {
  return f.default !== undefined ? f.default : defaultFor(f.type);
}

/** json 字段：值是 JSON **文本**（照旧：空文本 = null）。 */
function controlValue(f) {
  return f.type === "json" ? complex[f.name] ?? "" : values[f.name];
}

function setControl(f, value) {
  jsonError.value = "";
  if (f.type === "json") complex[f.name] = value;
  else values[f.name] = value;
}

/** 该组件里不进控件、走原始 JSON 的键（未声明键 + 落点在别处的重名键）。 */
function extraOf(compName) {
  const out = {};
  for (const [key, value] of Object.entries(props.components[compName] || {})) {
    const f = declaredField(key);
    if (f && homeOf(f) === compName) continue;
    out[key] = value;
  }
  return out;
}

function syncFromProps() {
  const names = declaredNames.value;
  for (const key of Object.keys(values)) {
    if (!names.includes(key)) delete values[key];
  }
  for (const key of Object.keys(complex)) {
    if (!names.includes(key)) delete complex[key];
  }
  for (const f of fields.value) {
    const home = homeOf(f);
    const data = props.components ? props.components[home] : undefined;
    const present = Boolean(data) && Object.prototype.hasOwnProperty.call(data, f.name);
    if (f.type === "json") {
      complex[f.name] = present ? JSON.stringify(data[f.name]) : JSON.stringify(f.default ?? {});
      delete values[f.name];
    } else if (present) {
      values[f.name] = data[f.name];
    } else {
      values[f.name] = fieldDefault(f);
    }
  }
  for (const key of Object.keys(compText)) {
    if (!compNames.value.includes(key)) delete compText[key];
  }
  for (const name of compNames.value) {
    compText[name] = JSON.stringify(extraOf(name), null, 2);
  }
  jsonError.value = "";
}

/** 文本 → JSON 对象；失败返回错误文案（调用方决定露在哪）。 */
function parseObjectText(text, where) {
  const raw = String(text ?? "").trim();
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

/** 文本 → 任意 JSON 值（json 声明字段用；空文本 = null）。 */
function parseJsonValue(text, where) {
  const raw = String(text ?? "").trim();
  if (!raw || raw === "null") return { ok: true, value: null };
  try {
    return { ok: true, value: JSON.parse(raw) };
  } catch (e) {
    return { ok: false, error: `${where}不是合法 JSON：${e.message}` };
  }
}

/**
 * 组装新的组件字典。任何一处 JSON 写坏 → 返回 null 并写好 jsonError：
 * **不发**（宁可这次修改不生效，也不能把整袋数据清空，D23 口径）。
 */
function buildComponents(skip = "") {
  const out = {};
  for (const name of compNames.value) {
    if (name === skip) continue;
    const raw = compText[name];
    if (raw === undefined) {
      // 兜底：这块的文本还没初始化（正常路径下 syncFromProps 已经填好了）——
      // 原样带回，绝不能因为缺文本就把组件写成 {}
      out[name] = { ...(props.components[name] || {}) };
      continue;
    }
    const parsed = parseObjectText(raw, `组件「${name}」`);
    if (!parsed.ok) {
      jsonError.value = parsed.error;
      return null;
    }
    out[name] = { ...parsed.value };
  }
  for (const f of fields.value) {
    let home = homeOf(f);
    let dockedHere = has(home, f.name);
    if (home === skip) {
      // 落点组件正在被删 → 字段跟着走（回「未落地」），**不许**改嫁到别的组件里
      home = fallbackName(f);
      dockedHere = false;
    }
    // 还没落地的字段：值没离开默认值就不凭空造组件（v2 里没有必填组件）
    if (!dockedHere && isAtDefault(f)) continue;
    let value;
    if (f.type === "json") {
      const parsed = parseJsonValue(complex[f.name], `字段「${f.label || f.name}」`);
      if (!parsed.ok) {
        jsonError.value = parsed.error;
        return null;
      }
      value = parsed.value;
    } else {
      value = values[f.name];
    }
    out[home] = { ...(out[home] || {}), [f.name]: value };
  }
  return out;
}

function isAtDefault(f) {
  if (f.type === "json") {
    const parsed = parseJsonValue(complex[f.name], "字段");
    if (!parsed.ok) return false; // 写坏了：交给 buildComponents 报错
    return JSON.stringify(parsed.value) === JSON.stringify(f.default ?? {});
  }
  return values[f.name] === fieldDefault(f);
}

function commit() {
  const next = buildComponents();
  if (next === null) return; // 解析失败：错误已露在折叠区外面，不落盘
  jsonError.value = "";
  emit("update", { components: next });
}

/** 组件名归一：不含冒号 → 补 local: 前缀；再按信封字符集校验。 */
function normalizeName(raw) {
  const text = String(raw || "").trim();
  if (!text) return { ok: false, error: "组件名不能为空" };
  const full = text.includes(":") ? text : `${LOCAL}:${text}`;
  if (!COMPONENT_RE.test(full)) {
    return {
      ok: false,
      error: `组件名不合法：${full}（只允许字母/数字/下划线/点/连字符，且必须是「来源:名字」）`,
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
  if (next === null) return; // 已有组件里 JSON 写坏了：先修好再加
  next[named.name] = body.value;
  justAdded.value = named.name;
  newName.value = "";
  newJson.value = "{}";
  jsonError.value = "";
  emit("update", { components: next });
}

async function dropComponent(name) {
  const homedCount = Object.keys(props.components[name] || {}).filter((key) => {
    const f = declaredField(key);
    return Boolean(f) && homeOf(f) === name;
  }).length;
  const ok = await askConfirm({
    title: "删除组件",
    danger: true,
    text: `从实体上删除组件「${name}」？`,
    detail: homedCount
      ? `组件里的数据会一起移除，其中 ${homedCount} 个声明字段退回「未落地」；保存后才真正生效。`
      : "组件里的数据会一起移除；保存后才真正生效。",
    confirmText: "删除",
  });
  if (!ok) return;
  if (buildComponents(name) === null) return; // 别处 JSON 写坏了：先修好再删
  // 落在被删组件里的声明字段 → 回默认值（组件都没了，不该静默搬到别的组件去）
  for (const f of fields.value) {
    if (homeOf(f) !== name) continue;
    if (f.type === "json") complex[f.name] = JSON.stringify(f.default ?? {});
    else values[f.name] = fieldDefault(f);
  }
  const next = buildComponents(name);
  if (next === null) return;
  delete next[name];
  if (justAdded.value === name) justAdded.value = "";
  jsonError.value = "";
  emit("update", { components: next });
}

watch(() => [props.kind, props.tags, props.components], syncFromProps, {
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
.where {
  font-size: 10px;
  color: var(--text-dim);
  font-family: ui-monospace, monospace;
}
.where.loose {
  color: var(--accent);
}
.comps {
  margin-top: 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.comp,
.new-comp {
  border: 1px solid var(--bg-3);
  border-radius: 8px;
  padding: 4px 6px;
  font-size: 12px;
  color: var(--text-dim);
}
.comp summary,
.new-comp summary {
  cursor: pointer;
  padding: 2px 0;
}
/* summary 保持原生 list-item（三角标才在），块头用行内元素排 */
.comp summary > *,
.new-comp summary > * {
  margin-right: 5px;
  vertical-align: middle;
}
.cname {
  color: var(--text);
}
.comp-body {
  padding-top: 6px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.comp textarea,
.new-comp textarea {
  width: 100%;
  padding: 6px 8px;
  border-radius: 6px;
  border: 1px solid var(--bg-3);
  background: var(--bg);
  color: var(--text);
  font-family: ui-monospace, monospace;
  font-size: 12px;
}
.new-row {
  display: flex;
  gap: 6px;
  align-items: center;
  margin-top: 4px;
}
.chip {
  font-size: 10px;
  border: 1px solid var(--bg-3);
  border-radius: 999px;
  padding: 0 6px;
  color: var(--text-dim);
}
.chip.core {
  color: var(--accent);
  border-color: var(--accent);
}
.chip.play {
  color: var(--text);
}
.chip.decl {
  color: var(--text);
  border-style: dashed;
}
.chip.und {
  color: var(--danger);
  border-color: var(--danger);
}
.mini,
.new-comp input {
  padding: 4px 6px;
  border-radius: 6px;
  border: 1px solid var(--bg-3);
  background: var(--bg);
  color: var(--text);
  font-size: 12px;
}
.mini-btn {
  align-self: flex-start;
  border: none;
  background: transparent;
  color: var(--text-dim);
  font-size: 12px;
  cursor: pointer;
  padding: 2px 4px;
  border-radius: 6px;
}
.mini-btn:hover {
  color: var(--accent);
  background: var(--bg-3);
}
.mini-btn.danger:hover {
  color: var(--danger);
}
.tiny {
  display: block;
  font-size: 11px;
  margin-top: 4px;
}
.bad {
  color: var(--danger);
}
.warn {
  color: var(--accent);
}
.dim {
  color: var(--text-dim);
  font-size: 12px;
}
</style>
