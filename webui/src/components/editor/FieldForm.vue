<template>
  <!-- 按组件分组的字段表单（实体模型 v2 / D41：能力 = 组件的存在）。
       实体数据只有一种单位——组件字典 components（组件键 = `source:name` 信封）。
       每个组件一块（折叠块）：块内先是**该组件自己声明的字段**（走 FieldControl），
       再是这个组件里「其余键」的原始 JSON 兜底（整块替换本组件），最后可以删掉组件。
       不再有"字段该落进哪个组件"的猜测：字段属于声明它的那个组件，落点只有一个。 -->
  <div class="field-form">
    <!-- 错误必须露在折叠区外面：v0.5.2 之前它藏在折叠区里，JSON 写坏时
         "改一个字段"会把另一袋数据静默清空，用户既看不到报错也看不到数据没了 -->
    <p v-if="jsonError" class="error-text">{{ jsonError }}</p>

    <div class="comps">
      <section v-for="group in componentGroups" :key="group.source" class="source-group">
        <header class="source-head">
          <div>
            <strong>{{ group.title }}</strong>
            <code>{{ group.source }}:</code>
          </div>
          <span class="dim">{{ group.items.length }} 个组件</span>
        </header>
        <details
          v-for="c in group.items"
          :key="c.name"
          class="comp"
          :open="c.name === justAdded || null"
        >
          <summary>
            <code class="cname">{{ c.name }}</code>
            <span class="chip" :class="c.badgeClass" :title="c.badgeTitle">{{ c.badge }}</span>
            <span v-if="c.fields.length" class="dim">{{ c.fields.length }} 个声明字段</span>
            <span v-if="c.extraCount" class="bad">其余键 {{ c.extraCount }}</span>
            <span v-if="c.locked" class="lock" title="core 组件由内核协议管理">锁定</span>
          </summary>
          <div class="comp-body">
            <div v-if="c.fields.length" class="declared">
              <div v-for="f in c.fields" :key="f.name" class="field">
                <label :title="`${f.name}（${f.type}）—— 声明自组件 ${c.name}`">
                  {{ f.label || f.name }}
                </label>
                <FieldControl
                  :field="f"
                  :model-value="controlValue(c.name, f)"
                  @update:model-value="(v) => setControl(c.name, f, v)"
                  @commit="commit"
                />
              </div>
            </div>
            <p v-else class="tiny">没有声明字段；可在下方编辑组件 JSON。</p>
            <label class="tiny">未声明字段（其余键）—— JSON，整块替换本组件的数据</label>
            <textarea
              v-model="extraText[c.name]"
              rows="3"
              placeholder="{}"
              @change="commit"
            ></textarea>
            <button v-if="!c.locked" class="mini-btn danger" @click="dropComponent(c.name)">
              删除组件
            </button>
            <span v-else class="tiny">core 组件不可从此处删除。</span>
          </div>
        </details>
      </section>
      <p v-if="!componentList.length" class="empty-state">
        还没有组件。空组件字典是合法实体状态，可以从下方添加 local: 组件。
      </p>
    </div>

    <details class="new-comp">
      <summary>＋ 新增组件</summary>
      <div class="new-row">
        <input
          v-model="newName"
          class="mini"
          placeholder="组件键（如 stat → local:stat）"
          @keydown.enter.prevent="addComponent"
        />
        <button class="btn" @click="addComponent">添加</button>
      </div>
      <p class="tiny">
        组件键 = <code>来源:名字</code>：<code>core:</code> 内核保留、玩法包用自己的 id、
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
  kinds: { type: Array, default: () => [] }, // 组件声明清单（{key, source, label, fields, …}）
  components: { type: Object, default: () => ({}) }, // 组件键 → 数据对象
});
const emit = defineEmits(["update"]);

// 组件键信封：source 与 name 各允许字母/数字/下划线/点/连字符（与内核
// split_component_key 的 _COMPONENT_PART_RE 同一口径），且必须有一个冒号。
const COMPONENT_RE = /^[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+$/;
const LOCAL = "local";
const CORE = "core";

const values = reactive({}); // 组件键 → {声明字段名: 值}（非 json）
const complex = reactive({}); // 组件键 → {声明字段名: JSON 文本}（json 类型）
const extraText = reactive({}); // 组件键 → 该组件「未声明键」的 JSON 文本
const jsonError = ref("");
const newName = ref("");
const newJson = ref("{}");
const newError = ref("");
const justAdded = ref(""); // 刚新增的组件默认展开（其余折叠）

const compNames = computed(() => Object.keys(props.components || {}));

/** 有声明的玩法包 source（排序用；core / local 单列，不算"玩法包"）。 */
const knownSources = computed(
  () =>
    new Set(
      props.kinds.map((k) => k.source).filter((s) => s && s !== CORE && s !== LOCAL)
    )
);

/** 组件显示顺序：core → 已声明的玩法包 → local → 其他；同类按名字排（稳定，不随编辑跳动）。 */
function rankOf(name) {
  const source = String(name).split(":")[0];
  if (source === CORE) return 0;
  if (knownSources.value.has(source)) return 1;
  if (source === LOCAL) return 2;
  return 3;
}
const ordered = computed(() =>
  [...compNames.value].sort((a, b) => rankOf(a) - rankOf(b) || a.localeCompare(b))
);

/** 该组件声明的字段（**只认组件键**：字段属于声明它的组件，不存在跨组件覆盖顺序）。 */
function declaredFieldsOf(name) {
  const spec = props.kinds.find((k) => k.key === name);
  return (spec && spec.fields) || [];
}

function defaultFor(type) {
  if (type === "int" || type === "float") return 0;
  if (type === "bool") return false;
  return "";
}

function fieldDefault(f) {
  return f.default !== undefined ? f.default : defaultFor(f.type);
}

/** json 声明字段：值是 JSON **文本**（照旧：空文本 = null）。 */
function controlValue(name, f) {
  if (f.type === "json") return (complex[name] && complex[name][f.name]) ?? "";
  return values[name] ? values[name][f.name] : undefined;
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

const componentList = computed(() =>
  ordered.value.map((name) => {
    const data = props.components[name] || {};
    const declared = new Set(declaredFieldsOf(name).map((f) => f.name));
    const extraCount = Object.keys(data).filter((key) => !declared.has(key)).length;
    return {
      name,
      fields: declaredFieldsOf(name),
      extraCount,
      locked: name.startsWith(`${CORE}:`),
      ...badgeOf(name),
    };
  })
);

const componentGroups = computed(() => {
  const groups = new Map();
  for (const item of componentList.value) {
    const source = item.name.split(":")[0] || "local";
    if (!groups.has(source)) {
      groups.set(source, {
        source,
        title: source === CORE ? "内核协议" : source === LOCAL ? "本地内容" : `玩法包：${source}`,
        items: [],
      });
    }
    groups.get(source).items.push(item);
  }
  return [...groups.values()];
});

/** 来源标记：core → 内核保留；已声明玩法包 → 该来源包；已声明 local → 已声明；否则虚构组件。 */
function badgeOf(name) {
  const source = String(name).split(":")[0];
  if (source === CORE) {
    return {
      badge: "内核保留",
      badgeClass: "core",
      badgeTitle: "core: 是内核保留命名空间（玩法包不得写入）",
    };
  }
  if (knownSources.value.has(source)) {
    return {
      badge: `玩法包 ${source}`,
      badgeClass: "play",
      badgeTitle: `来源包：${source}`,
    };
  }
  const spec = props.kinds.find((k) => k.key === name);
  if (spec) {
    return {
      badge: "已声明",
      badgeClass: "decl",
      badgeTitle: `已声明：${spec.label || spec.key}`,
    };
  }
  return {
    badge: "虚构组件",
    badgeClass: "und",
    badgeTitle: "未声明组件（虚构组件）：没有对应声明，不贡献任何能力，但允许存在",
  };
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

/** 某组件声明字段的当前值；json 字段写坏 → 写 jsonError 并返回 null。 */
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
      out[f.name] = values[name] ? values[name][f.name] : undefined;
    }
  }
  return out;
}

/**
 * 组装新的组件字典：每个组件 = `{...它的其余键 JSON, ...它自己声明字段的当前值}`。
 * 任何一处 JSON 写坏 → 返回 null 并写好 jsonError：**不发**（宁可这次修改不生效，
 * 也不能把整袋数据清空，D23 口径）。
 */
function buildComponents(skip = "") {
  const out = {};
  for (const name of compNames.value) {
    if (name === skip) continue; // 正在被删的组件不参与校验（它的数据本来就要丢掉）
    const raw = extraText[name];
    let extra;
    if (raw === undefined) {
      // 兜底：这块的文本还没初始化（正常路径下 syncFromProps 已经填好了）——
      // 原样带回，绝不能因为缺文本就把组件写成 {}；声明字段随后覆盖自己的键
      extra = { ...(props.components[name] || {}) };
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
  if (next === null) return; // 解析失败：错误已露在折叠区外面，不落盘
  jsonError.value = "";
  emit("update", { components: next });
}

/** 组件键归一：不含冒号 → 补 local: 前缀；再按信封字符集校验。 */
function normalizeName(raw) {
  const text = String(raw || "").trim();
  if (!text) return { ok: false, error: "组件键不能为空" };
  const full = text.includes(":") ? text : `${LOCAL}:${text}`;
  if (!COMPONENT_RE.test(full)) {
    return {
      ok: false,
      error: `组件键不合法：${full}（只允许字母/数字/下划线/点/连字符，且必须是「来源:名字」）`,
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
  if (name.startsWith(`${CORE}:`)) {
    jsonError.value = "core 组件由内核协议管理，不能在实体编辑器中删除";
    return;
  }
  const ok = await askConfirm({
    title: "删除组件",
    danger: true,
    text: `从实体上删除组件「${name}」？`,
    detail:
      "能力 = 组件的存在：删掉它，这个实体就失去该组件带来的能力，组件里的数据也一起移除；保存后才真正生效。",
    confirmText: "删除",
  });
  if (!ok) return;
  const next = buildComponents(name); // 先确保别处的 JSON 是好的（这块自己跳过）
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
.comps {
  margin-top: 6px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.source-group {
  border: 1px solid var(--bg-3);
  border-radius: 8px;
  padding: 6px;
}
.source-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 2px 2px 6px;
  color: var(--text);
}
.source-head div {
  display: flex;
  align-items: baseline;
  gap: 6px;
}
.source-head code {
  color: var(--text-dim);
  font-size: 11px;
}
.lock {
  color: var(--accent);
  font-size: 10px;
  border: 1px solid var(--accent);
  border-radius: 999px;
  padding: 0 5px;
}
.empty-state {
  border: 1px dashed var(--bg-3);
  padding: 12px;
  text-align: center;
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
.dim {
  color: var(--text-dim);
  font-size: 12px;
}
</style>
