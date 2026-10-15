<template>
  <!-- 实体管理视图：列表（筛选/排序/分页，按上千实体设计）+ 详情面板。
       D41：能力 = 组件的存在——实体上没有 kind / tags，只有组件字典。 -->
  <div class="entity-manager">
    <!-- 工具条 -->
    <div class="toolbar">
      <input v-model="q" class="mini search" placeholder="搜索名称 / 组件 / id…" />
      <select v-model="componentFilter" class="mini">
        <option value="">全部组件</option>
        <option v-for="k in componentOptions" :key="k" :value="k">{{ k }}</option>
      </select>
      <select v-model="sort" class="mini">
        <option value="pos">按位置</option>
        <option value="name">按名称</option>
        <option value="comp">按组件</option>
      </select>
      <label v-if="tileFilter" class="mini-label pinned">
        <input type="checkbox" v-model="tileOnly" />
        只看地块 ({{ tileFilter.row }}, {{ tileFilter.col }})
      </label>
      <span class="grow" />
      <span class="dim">{{ filtered.length }} 个实体</span>
      <button class="btn" @click="showCreate = !showCreate">
        {{ showCreate ? "收起放置" : "＋ 放置实体" }}
      </button>
    </div>

    <!-- 放置（从模板 + 组件 + 组件数据组合） -->
    <div v-if="showCreate" class="create">
      <div class="row">
        <select v-model="draft.template_id" class="mini" @change="applyTemplate">
          <option value="">（不用模板）</option>
          <option v-for="t in entityTemplates" :key="t.id" :value="t.id">
            {{ t.name }}{{ t.source === "play" ? `（${t.play_id}）` : "" }}
          </option>
        </select>
        <input
          v-model="draft.ability"
          class="mini"
          list="component-options"
          placeholder="组件（可自由输入，裸名由后端解析）"
        />
        <datalist id="component-options">
          <option v-for="k in kinds" :key="k.key" :value="k.key">{{ k.label }}</option>
        </datalist>
        <input v-model="draft.name" class="mini" placeholder="名称（默认取组件文案）" />
        <!-- D36：位置可有可无。只有"实体治理"视角（全局页）才允许造一个不进世界的
             实体——地图编辑器里造了它不会出现在本图（`_map_detail` 只看在场实体），
             用户会以为"创建失败"。 -->
        <template v-if="allowAbsent">
          <label class="mini-label" title="不勾 = 造一个不在世界上的实体（先造出来，之后再放）">
            <input v-model="draft.place" type="checkbox" />
            放进世界
          </label>
          <template v-if="draft.place">
            <span class="dim">@</span>
            <input v-model.number="draft.row" type="number" class="num" placeholder="行" />
            <input v-model.number="draft.col" type="number" class="num" placeholder="列" />
          </template>
          <span v-else class="dim">不在世界上</span>
        </template>
        <template v-else>
          <span class="dim">@</span>
          <input v-model.number="draft.row" type="number" class="num" placeholder="行" />
          <input v-model.number="draft.col" type="number" class="num" placeholder="列" />
        </template>
        <button class="btn" @click="create">{{ draft.place ? "放置" : "创建" }}</button>
      </div>
      <ComponentPicker :model-value="draftKeys" :kinds="kinds" @update:model-value="setDraftKeys" />
      <FieldForm
        :kinds="kinds"
        :components="draft.components"
        @update="(v) => (draft.components = v.components)"
      />
    </div>

    <p v-if="error" class="error-text">{{ error }}</p>

    <div class="split">
      <!-- 列表 -->
      <div class="list-wrap">
        <table class="table tight">
          <thead>
            <tr>
              <th>名称</th>
              <th class="ops-col">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="e in pageItems"
              :key="e.id"
              :class="{ on: selectedId === e.id }"
              @click="select(e)"
            >
              <td>
                <!-- 名字在 core:info 组件里；entityName() 负责兜底到 id 前 8 位 -->
                <span class="name">{{ entityName(e) }}</span>
                <div v-if="entityDesc(e)" class="dim ell">{{ entityDesc(e) }}</div>
              </td>
              <td class="ops-col">
                <button
                  class="mini-btn"
                  :disabled="!hasPosition(e)"
                  :title="
                    hasPosition(e)
                      ? '在地图上选中它所在的地块'
                      : '它不在世界上（没有 core:position），没有地块可定位'
                  "
                  @click.stop="emit('locate', e)"
                >
                  定位
                </button>
                <button class="mini-btn danger" @click.stop="emit('remove', e)">删除</button>
              </td>
            </tr>
            <tr v-if="!filtered.length">
              <td colspan="2" class="dim">
                {{ tileFilter && tileOnly ? "这个地块上没有实体。" : "没有匹配的实体。" }}
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="pages > 1" class="pager">
          <button class="mini-btn" :disabled="page <= 1" @click="page -= 1">‹ 上一页</button>
          <span class="dim">第 {{ page }} / {{ pages }} 页</span>
          <button class="mini-btn" :disabled="page >= pages" @click="page += 1">下一页 ›</button>
          <select v-model.number="pageSize" class="mini">
            <option :value="50">50 / 页</option>
            <option :value="100">100 / 页</option>
            <option :value="200">200 / 页</option>
          </select>
        </div>
      </div>

      <!-- 详情 -->
      <aside class="detail">
        <template v-if="current">
          <div class="detail-head">
            <div>
              <b>{{ entityName(current) }}</b>
              <div class="dim">实体详情 · {{ current.id.slice(0, 8) }}</div>
            </div>
            <span class="component-count">{{ componentKeys(current).length }} 个组件</span>
          </div>
          <div class="component-summary">
            <span
              v-for="key in componentKeys(current)"
              :key="key"
              class="summary-chip"
              :class="{ core: isCoreComponent(key), unknown: isUnknown(current, key) }"
              :title="chipTitle(current, key)"
            >
              {{ key }}
              <span v-if="componentSummary(current, key)" class="sum">
                · {{ componentSummary(current, key) }}
              </span>
            </span>
            <span v-if="!componentKeys(current).length" class="dim">暂无组件</span>
          </div>
          <label class="field">
            名称
            <input
              v-model="edit.name"
              :placeholder="`未设名字 → 显示 ${current.id.slice(0, 8)}（core:info.name）`"
            />
          </label>
          <label class="field">
            描述
            <textarea
              v-model="edit.desc"
              rows="2"
              placeholder="core:info.desc（可留空）"
            ></textarea>
          </label>
          <ComponentPicker :model-value="editKeys" :kinds="kinds" @update:model-value="setEditKeys" />
          <FieldForm
            :kinds="kinds"
            :components="edit.components"
            @update="(v) => (edit.components = v.components)"
          />
          <div v-if="current.capabilities" class="caps">
            <b>组件声明的汇总</b>
            <div class="dim">
              实体本身只有组件；下面这些是**声明**（玩法包 / 内核）按组件算出来的结果。
            </div>
            <div>生效组件：{{ caps.active.join("、") || "（无）" }}</div>
            <div v-if="caps.inactive.length" class="bad">
              本世界未启用：{{ caps.inactive.join("、") }}
              （有声明，但该玩法包在本世界没启用）
            </div>
            <div v-if="caps.orphan.length" class="bad">
              声明已不在：{{ caps.orphan.join("、") }}
              （声明它的玩法包已停用 / 卸载，暂时不贡献能力）
            </div>
            <div v-if="caps.fictional.length" class="bad">
              没有声明：{{ caps.fictional.join("、") }}
              （虚构组件，不贡献能力）
            </div>
            <div>动作：{{ caps.interactions.join("、") || "（无）" }}</div>
            <div v-if="fieldGroups.length">
              字段：
              <div v-for="g in fieldGroups" :key="g.key" class="fields-row">
                <code>{{ g.key }}</code
                >: {{ g.names }}
              </div>
            </div>
            <div v-else>字段：（无）</div>
          </div>
          <div class="detail-ops">
            <button class="btn" @click="save">保存</button>
            <button class="mini-btn" @click="emit('save-template', current)">存为模板</button>
            <button
              class="mini-btn"
              :disabled="!hasPosition(current)"
              @click="emit('locate', current)"
            >
              定位
            </button>
            <button class="mini-btn danger" @click="emit('remove', current)">删除</button>
          </div>
        </template>
        <p v-else class="dim">从左边选一个实体查看/编辑详情；也可以用上方的「放置实体」新建。</p>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue";
import {
  componentJson,
  componentKeys,
  componentSummary,
  entityDesc,
  entityName,
  entityPosition,
  hasComponent,
  hasPosition,
  isCoreComponent,
  positionLabel,
  positionSortKey,
  rawEntityDesc,
  rawEntityName,
  withoutPosition,
} from "../../entity.js";
import ComponentPicker from "./ComponentPicker.vue";
import FieldForm from "./FieldForm.vue";

const props = defineProps({
  entities: { type: Array, default: () => [] },
  kinds: { type: Array, default: () => [] },
  entityTemplates: { type: Array, default: () => [] },
  tileFilter: { type: Object, default: null }, // {row, col} | null（从地图跳进来时带的）
  // 是否允许"造一个不在世界上的实体"（D36）——只有实体治理视角（全局实体页）为真
  allowAbsent: { type: Boolean, default: false },
});
const emit = defineEmits(["create", "update", "remove", "save-template", "locate"]);

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
  ability: "", // 单个组件键：自由输入，裸名由后端解析（省略 = 不带任何内容组件）
  name: "",
  components: {}, // 组件键 → 数据（实体数据的唯一单位）
  row: 0,
  col: 0,
  place: true, // D36：勾选 = 放进世界（发坐标）；不勾 = 造一个不在世界上的实体
});
const edit = reactive({ name: "", desc: "", components: {} });

/** 组件键清单（读法只在 entity.js 里）——组件选择器与组件字典之间的桥。 */
const draftKeys = computed(() => componentKeys({ components: draft.components }));
const editKeys = computed(() => componentKeys({ components: edit.components }));

/** 按选择器给的键重建组件字典：留下的键保数据，新增的键从 `{}` 开始。 */
function withKeys(components, keys) {
  const out = {};
  for (const key of keys) {
    out[key] = Object.prototype.hasOwnProperty.call(components || {}, key)
      ? components[key]
      : {};
  }
  return out;
}
function setDraftKeys(keys) {
  draft.components = withKeys(draft.components, keys);
}
function setEditKeys(keys) {
  edit.components = withKeys(edit.components, keys);
}

/** 组件筛选选项 = 所有实体带的组件键（先非 core:，再字典序——内容组件排在前面）。 */
const componentOptions = computed(() => {
  const rank = (key) => (isCoreComponent(key) ? 1 : 0);
  return [...new Set(props.entities.flatMap((e) => componentKeys(e)))].sort(
    (a, b) => rank(a) - rank(b) || a.localeCompare(b)
  );
});

/** "按组件"排序键：内容组件键排好序拼起来（core: 是协议数据，每个实体都有，排序无信息）。 */
function componentSortKey(e) {
  return contentComponents(e).sort().join("、");
}

const filtered = computed(() => {
  const needle = q.value.trim().toLowerCase();
  const list = props.entities.filter((e) => {
    if (tileOnly.value && props.tileFilter) {
      // 位置在 core:position 组件里；不在世界上的实体没有格子，直接排除
      const p = entityPosition(e);
      if (!p || p.row !== props.tileFilter.row || p.col !== props.tileFilter.col) return false;
    }
    if (componentFilter.value && !hasComponent(e, componentFilter.value)) return false;
    if (!needle) return true;
    return (
      entityName(e).toLowerCase().includes(needle) ||
      e.id.toLowerCase().includes(needle) ||
      // 组件键也是可搜的（"哪些实体带 core:perception" 这类排查）
      componentKeys(e).some((n) => n.toLowerCase().includes(needle))
    );
  });
  // 名字在 core:info 组件里 → 一律经 entityName（带 id 兜底），别直接读 e.name
  // 位置在 core:position 组件里 → 经 positionSortKey（不在世界上的排最后）
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

/** 能力面板的字段（后端是 `{组件键: [字段]}`，按组件分组显示，不摊平）。 */
const fieldGroups = computed(() => {
  const fields = (current.value && current.value.capabilities?.fields) || {};
  return Object.entries(fields).map(([key, list]) => ({
    key,
    names: (list || []).map((f) => f.label || f.name).join("、") || "（无）",
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

/**
 * 能力裁决的**归一化读取**（D44 四象限）。
 *
 * ⚠️ v0.7.1 事故：这里原来直读 `capabilities.unknown_components`——D44 把该键
 * 拆成 `orphan_components`（声明它的包不在了）+ `fictional_components`（`local:`
 * 且查无声明），后端不再返回旧键，于是详情面板在 `.length` 上抛
 * `TypeError: can't access property "length", ... is undefined`，
 * **整块实体编辑 UI 白屏**。模板直读后端可选字段就是这类缺陷的温床，
 * 所以统一经这里收口：缺键 = 空数组，前端永远拿到可安全 `.length` / `.join` 的形状。
 */
function capsOf(e) {
  const raw = (e && e.capabilities) || {};
  const list = (key) => (Array.isArray(raw[key]) ? raw[key] : []);
  return {
    components: list("components"),
    active: list("active_components"),
    inactive: list("inactive_components"),
    orphan: list("orphan_components"),
    fictional: list("fictional_components"),
    interactions: list("interactions"),
  };
}

/** 当前实体的声明快照（详情面板用）。 */
const caps = computed(() => capsOf(current.value));

/** 这个组件键有没有声明（后端裁决：orphan / fictional 都是"查无声明"）。 */
function isUnknown(e, key) {
  const c = capsOf(e);
  return c.orphan.includes(key) || c.fictional.includes(key);
}

/** 组件 chip 的悬浮说明：声明状态 + 该组件的完整数据（摘要只有几个字，细节在这里）。 */
function chipTitle(e, key) {
  const state = isUnknown(e, key)
    ? capsOf(e).orphan.includes(key)
      ? "声明它的玩法包已停用 / 卸载（启用即恢复）"
      : "没有声明（虚构组件，允许存在）"
    : "已声明";
  return `${key} · ${state}\n${componentJson(e, key)}`;
}

/** 深拷贝组件字典：编辑面板不能直接改 props.entities 里的对象。 */
function cloneComponents(components) {
  return JSON.parse(JSON.stringify(components || {}));
}

function select(e) {
  selectedId.value = e.id;
  // 回填 **原始** 名字/描述（不填 id 兜底）——否则"打开一个没名字的实体再保存"
  // 会把兜底串当成真名写进去。展示侧的兜底在 entityName()。
  edit.name = rawEntityName(e);
  edit.desc = rawEntityDesc(e);
  edit.components = cloneComponents(e.components);
}

function applyTemplate() {
  const t = props.entityTemplates.find((x) => x.id === draft.template_id);
  if (!t) return;
  const d = t.data || {};
  // 实体模板负载 = {name, desc, components}（D41：能力 = 一组组件键，没有 kind / tags）
  draft.name = d.name || "";
  draft.components = cloneComponents(d.components);
}

function create() {
  error.value = "";
  // D36：位置三参数要么全给、要么全不给——"放进世界"不勾就一个坐标都不发
  // （后端据此造一个不在世界上的实体）。半截坐标会被后端拒绝。
  const pos = draft.place ? { row: Number(draft.row), col: Number(draft.col) } : {};
  // 组件里若漏进一个 core:position（如从带位置的组件/模板抄来的），"不放进世界"会失效
  const components = draft.place
    ? cloneComponents(draft.components)
    : withoutPosition(draft.components);
  emit("create", {
    // 组件键是**输入便利**：裸名由后端解析成 `source:name`；不填 = 不带内容组件
    kind: draft.ability.trim() || undefined,
    name: draft.name.trim() || undefined,
    components,
    ...pos,
  });
  draft.name = "";
  draft.ability = "";
}

function save() {
  if (!current.value) return;
  // name/desc 走顶层键（后端折进 core:info）。空 name 也要发送：
  // 后端将空串解释为删除名字，恢复 id 前 8 位的兜底显示。
  const patch = {
    name: edit.name.trim(),
    desc: edit.desc,
    components: cloneComponents(edit.components), // PATCH 里 components 是整体替换
  };
  emit("update", current.value, patch);
}

defineExpose({
  setError: (msg) => (error.value = msg),
  focus: (id) => {
    selectedId.value = id;
    const e = props.entities.find((x) => x.id === id);
    if (e) select(e);
  },
});
</script>

<style scoped>
.entity-manager {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.toolbar {
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
  flex-shrink: 0;
}
.grow {
  flex: 1;
}
.create {
  border: 1px solid var(--bg-3);
  border-radius: 8px;
  padding: 8px;
  flex-shrink: 0;
}
.row {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  align-items: center;
  margin-bottom: 4px;
}
.split {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 12px;
}
.list-wrap {
  flex: 1;
  min-width: 0;
  overflow: auto;
  display: flex;
  flex-direction: column;
}
table.tight td,
table.tight th {
  padding: 5px 8px;
  font-size: 13px;
}
.name {
  font-weight: 600;
}
.ops-col {
  white-space: nowrap;
  text-align: right;
}
tr.on td {
  background: var(--bg-3);
}
.pager {
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 6px 2px;
  position: sticky;
  bottom: 0;
  background: var(--bg);
}
.detail {
  width: 400px;
  flex-shrink: 0;
  overflow: auto;
  border-left: 1px solid var(--bg-3);
  padding-left: 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.detail-head {
  display: flex;
  gap: 8px;
  align-items: center;
  justify-content: space-between;
}
.detail-head > div {
  min-width: 0;
}
.component-count {
  color: var(--text-dim);
  font-size: 12px;
  white-space: nowrap;
}
.component-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding: 6px 0;
  border-bottom: 1px solid var(--bg-3);
}
.summary-chip {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  font-family: ui-monospace, monospace;
  font-size: 11px;
  border: 1px solid var(--bg-3);
  border-radius: 999px;
  padding: 2px 6px;
  color: var(--text-dim);
}
/* 组件 chip：空组件（纯标记）只有键名，带数据的跟一个中性摘要 */
.summary-chip .sum {
  color: var(--text-dim);
  opacity: 0.75;
}
.summary-chip.core {
  color: var(--accent);
  border-color: var(--accent);
}
.summary-chip.unknown {
  color: var(--danger);
  border-color: var(--danger);
}
.field {
  display: flex;
  flex-direction: column;
  gap: 3px;
  font-size: 13px;
  color: var(--text-dim);
}
.field input,
.field textarea {
  padding: 6px 8px;
  border-radius: 8px;
  border: 1px solid var(--bg-3);
  background: var(--bg);
  color: var(--text);
  font-size: 13px;
}
.caps {
  font-size: 12px;
  color: var(--text-dim);
  line-height: 1.6;
  border-top: 1px solid var(--bg-3);
  padding-top: 6px;
}
.fields-row {
  padding-left: 10px;
}
.detail-ops {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 6px;
}
.chip {
  display: inline-block;
  margin-right: 3px;
  font-size: 11px;
  border: 1px solid var(--bg-3);
  border-radius: 999px;
  padding: 0 6px;
  color: var(--text-dim);
}
.chip.bad {
  color: var(--danger);
  border-color: var(--danger);
}
.mini {
  padding: 5px 8px;
  border-radius: 6px;
  border: 1px solid var(--bg-3);
  background: var(--bg);
  color: var(--text);
  font-size: 13px;
}
.search {
  min-width: 220px;
}
.num {
  width: 62px;
  padding: 5px 8px;
  border-radius: 6px;
  border: 1px solid var(--bg-3);
  background: var(--bg);
  color: var(--text);
  font-size: 13px;
}
.mini-btn {
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
.mini-btn:disabled {
  opacity: 0.4;
  cursor: default;
}
.mini-label {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--text-dim);
}
.mini-label.pinned {
  color: var(--accent);
}
.ell {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 220px;
}
.bad {
  color: var(--danger);
}
.dim {
  color: var(--text-dim);
  font-size: 12px;
}

@media (max-width: 1100px) {
  .split {
    flex-direction: column;
  }
  .detail {
    width: 100%;
    border-left: none;
    padding-left: 0;
  }
}
</style>
