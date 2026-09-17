<template>
  <!-- 实体管理视图：列表（筛选/排序/分页，按上千实体设计）+ 详情面板 -->
  <div class="entity-manager">
    <!-- 工具条 -->
    <div class="toolbar">
      <input v-model="q" class="mini search" placeholder="搜索名称 / 类型 / 标签 / id…" />
      <select v-model="kindFilter" class="mini">
        <option value="">全部类型</option>
        <option v-for="k in kindOptions" :key="k" :value="k">{{ k }}</option>
      </select>
      <select v-model="tagFilter" class="mini">
        <option value="">全部标签</option>
        <option v-for="t in tagOptions" :key="t" :value="t">{{ t }}</option>
      </select>
      <select v-model="sort" class="mini">
        <option value="pos">按位置</option>
        <option value="name">按名称</option>
        <option value="kind">按类型</option>
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

    <!-- 放置（从模板 / 类型 / 标签组合） -->
    <div v-if="showCreate" class="create">
      <div class="row">
        <select v-model="draft.template_id" class="mini" @change="applyTemplate">
          <option value="">（不用模板）</option>
          <option v-for="t in entityTemplates" :key="t.id" :value="t.id">
            {{ t.name }}{{ t.source === "play" ? `（${t.play_id}）` : "" }}
          </option>
        </select>
        <input v-model="draft.kind" class="mini" list="kind-options" placeholder="类型（可自由输入）" />
        <datalist id="kind-options">
          <option v-for="k in kinds" :key="k.tag" :value="k.tag">{{ k.label }}</option>
        </datalist>
        <input v-model="draft.name" class="mini" placeholder="名称（默认取类型文案）" />
        <span class="dim">@</span>
        <input v-model.number="draft.row" type="number" class="num" placeholder="行" />
        <input v-model.number="draft.col" type="number" class="num" placeholder="列" />
        <button class="btn" @click="create">放置</button>
      </div>
      <TagPicker v-model="draft.tags" :kinds="kinds" :preset="presetOf(draft.kind)" :kind="draft.kind" />
      <FieldForm
        :kinds="kinds"
        :kind="draft.kind"
        :tags="draft.tags"
        :attrs="draft.attrs"
        :state="draft.state"
        @update="(v) => { draft.attrs = v.attrs; draft.state = v.state; }"
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
              <th>类型</th>
              <th>标签</th>
              <th>位置</th>
              <th>能力</th>
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
                <span class="name">{{ e.name }}</span>
                <div v-if="e.desc" class="dim ell">{{ e.desc }}</div>
              </td>
              <td><code>{{ e.kind }}</code></td>
              <td>
                <span v-for="t in e.tags" :key="t" class="chip" :class="{ bad: !specOf(t) }">
                  {{ t }}
                </span>
              </td>
              <td class="dim">({{ e.row }}, {{ e.col }})</td>
              <td class="caps-cell">
                <span v-if="e.capabilities?.block_move" class="chip warn">挡路</span>
                <span v-for="a in (e.capabilities?.interactions || []).slice(0, 2)" :key="a" class="chip">
                  {{ a }}
                </span>
                <span v-if="(e.capabilities?.interactions || []).length > 2" class="dim">
                  +{{ e.capabilities.interactions.length - 2 }}
                </span>
                <span v-if="e.capabilities?.unknown_tags?.length" class="chip bad" title="未注册标签：不贡献能力">
                  ⚠{{ e.capabilities.unknown_tags.length }}
                </span>
                <span v-if="e.capabilities?.inactive_tags?.length" class="chip bad" title="标签所属玩法包在本世界未启用">
                  ⏸{{ e.capabilities.inactive_tags.length }}
                </span>
              </td>
              <td class="ops-col">
                <button class="mini-btn" title="在地图上选中它所在的地块" @click.stop="emit('locate', e)">
                  定位
                </button>
                <button class="mini-btn danger" @click.stop="emit('remove', e)">删除</button>
              </td>
            </tr>
            <tr v-if="!filtered.length">
              <td colspan="6" class="dim">
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
            <b>实体详情</b>
            <code class="dim">{{ current.id.slice(0, 8) }}</code>
          </div>
          <label class="field">
            名称
            <input v-model="edit.name" />
          </label>
          <label class="field">
            描述
            <textarea v-model="edit.desc" rows="2"></textarea>
          </label>
          <label class="field">
            类型（基底）
            <template v-if="isIdentity(current)">
              <code class="dim">{{ current.kind }} · 身份实体的类型由身份服务管理（D20）</code>
            </template>
            <input v-else v-model="edit.kind" list="kind-options" />
          </label>
          <TagPicker v-model="edit.tags" :kinds="kinds" :preset="presetOf(edit.kind)" :kind="edit.kind" />
          <FieldForm
            :kinds="kinds"
            :kind="edit.kind"
            :tags="edit.tags"
            :attrs="edit.attrs"
            :state="edit.state"
            @update="(v) => { edit.attrs = v.attrs; edit.state = v.state; }"
          />
          <div v-if="current.capabilities" class="caps">
            <b>合并后的能力</b>
            <div>有效标签：{{ current.capabilities.active_tags.join("、") || "（无）" }}</div>
            <div>挡路：{{ current.capabilities.block_move ? "是" : "否" }}</div>
            <div>动作：{{ current.capabilities.interactions.join("、") || "（无）" }}</div>
            <div>字段：{{ current.capabilities.fields.map((f) => f.name).join("、") || "（无）" }}</div>
            <div v-if="current.capabilities.unknown_tags.length" class="bad">
              未注册：{{ current.capabilities.unknown_tags.join("、") }}（不贡献能力）
            </div>
            <div v-if="current.capabilities.inactive_tags.length" class="bad">
              本世界未启用：{{ current.capabilities.inactive_tags.join("、") }}
            </div>
          </div>
          <div class="detail-ops">
            <button class="btn" @click="save">保存</button>
            <button class="mini-btn" @click="emit('save-template', current)">存为模板</button>
            <button class="mini-btn" @click="emit('locate', current)">定位</button>
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
import FieldForm from "./FieldForm.vue";
import TagPicker from "./TagPicker.vue";

const props = defineProps({
  entities: { type: Array, default: () => [] },
  kinds: { type: Array, default: () => [] },
  entityTemplates: { type: Array, default: () => [] },
  tileFilter: { type: Object, default: null }, // {row, col} | null（从地图跳进来时带的）
});
const emit = defineEmits(["create", "update", "remove", "save-template", "locate"]);

const error = ref("");
const q = ref("");
const kindFilter = ref("");
const tagFilter = ref("");
const sort = ref("pos");
const tileOnly = ref(true);
const page = ref(1);
const pageSize = ref(50);
const showCreate = ref(false);
const selectedId = ref("");

const draft = reactive({
  template_id: "",
  kind: "",
  name: "",
  tags: [],
  attrs: {},
  state: {},
  row: 0,
  col: 0,
});
const edit = reactive({ kind: "", name: "", desc: "", tags: [], attrs: {}, state: {} });

const kindOptions = computed(() => [...new Set(props.entities.map((e) => e.kind))].sort());
const tagOptions = computed(
  () => [...new Set(props.entities.flatMap((e) => e.tags || []))].sort()
);

const filtered = computed(() => {
  const needle = q.value.trim().toLowerCase();
  const list = props.entities.filter((e) => {
    if (tileOnly.value && props.tileFilter) {
      if (e.row !== props.tileFilter.row || e.col !== props.tileFilter.col) return false;
    }
    if (kindFilter.value && e.kind !== kindFilter.value) return false;
    if (tagFilter.value && !(e.tags || []).includes(tagFilter.value)) return false;
    if (!needle) return true;
    return (
      e.name.toLowerCase().includes(needle) ||
      e.kind.toLowerCase().includes(needle) ||
      e.id.toLowerCase().includes(needle) ||
      (e.tags || []).some((t) => t.toLowerCase().includes(needle))
    );
  });
  const byPos = (a, b) => a.row - b.row || a.col - b.col || a.name.localeCompare(b.name);
  if (sort.value === "name") list.sort((a, b) => a.name.localeCompare(b.name));
  else if (sort.value === "kind") list.sort((a, b) => a.kind.localeCompare(b.kind) || byPos(a, b));
  else list.sort(byPos);
  return list;
});

const pages = computed(() => Math.max(1, Math.ceil(filtered.value.length / pageSize.value)));
const pageItems = computed(() => {
  const start = (page.value - 1) * pageSize.value;
  return filtered.value.slice(start, start + pageSize.value);
});
const current = computed(() => props.entities.find((e) => e.id === selectedId.value) || null);

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

function specOf(tag) {
  return props.kinds.find((k) => k.tag === tag) || null;
}
function presetOf(kind) {
  return specOf(kind)?.preset_tags || [];
}
function isIdentity(e) {
  return e.kind === "player";
}

function select(e) {
  selectedId.value = e.id;
  edit.kind = e.kind;
  edit.name = e.name;
  edit.desc = e.desc || "";
  edit.tags = [...(e.tags || [])];
  edit.attrs = { ...(e.attrs || {}) };
  edit.state = { ...(e.state || {}) };
}

function applyTemplate() {
  const t = props.entityTemplates.find((x) => x.id === draft.template_id);
  if (!t) return;
  const d = t.data || {};
  draft.kind = d.kind || draft.kind;
  draft.tags = [...(d.tags || [])];
  draft.name = d.name || "";
  draft.attrs = { ...(d.attrs || {}) };
  draft.state = { ...(d.state || {}) };
}

function create() {
  error.value = "";
  if (!draft.kind.trim()) {
    error.value = "类型不能为空（可自由输入一个玩法包声明的类型名）";
    return;
  }
  emit("create", {
    kind: draft.kind.trim(),
    name: draft.name.trim() || undefined,
    tags: [...draft.tags],
    attrs: draft.attrs,
    state: draft.state,
    row: Number(draft.row),
    col: Number(draft.col),
  });
  draft.name = "";
}

function save() {
  if (!current.value) return;
  const patch = {
    name: edit.name,
    desc: edit.desc,
    tags: [...edit.tags],
    attrs: edit.attrs,
    state: edit.state,
  };
  if (!isIdentity(current.value)) patch.kind = edit.kind;
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
.caps-cell {
  white-space: nowrap;
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
  align-items: baseline;
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
.chip.warn {
  color: var(--accent);
  border-color: var(--accent);
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
