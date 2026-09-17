<template>
  <!-- 实体面板（D18–D23）：类型 + 标签组合、按声明渲染字段、未声明字段走原始 JSON -->
  <div class="entities">
    <h3>实体（{{ entities.length }}）</h3>

    <!-- 新建：从模板 / 类型 / 标签组合 -->
    <div class="create card">
      <div class="row">
        <select v-model="draft.template_id" class="mini" @change="applyTemplate">
          <option value="">（不用模板）</option>
          <option v-for="t in entityTemplates" :key="t.id" :value="t.id">
            {{ t.name }}{{ t.source === "play" ? `（${t.play_id}）` : "" }}
          </option>
        </select>
        <input
          v-model="draft.kind"
          class="mini"
          list="kind-options"
          placeholder="类型（可自由输入）"
        />
        <datalist id="kind-options">
          <option v-for="k in kinds" :key="k.tag" :value="k.tag">{{ k.label }}</option>
        </datalist>
        <input v-model="draft.name" class="mini" placeholder="名称（默认取类型文案）" />
        <input v-model.number="draft.row" type="number" class="num" placeholder="行" />
        <input v-model.number="draft.col" type="number" class="num" placeholder="列" />
        <button class="mini-btn" @click="useSelectedPos">用选中格</button>
        <button class="btn" @click="create">放置</button>
      </div>

      <TagPicker v-model="draft.tags" :kinds="kinds" :preset="presetOf(draft.kind)" />

      <FieldForm
        :kinds="kinds"
        :kind="draft.kind"
        :tags="draft.tags"
        :attrs="draft.attrs"
        :state="draft.state"
        @update="onDraftData"
      />
      <p v-if="draft.desc" class="dim">{{ draft.desc }}</p>
    </div>

    <p v-if="error" class="error-text">{{ error }}</p>

    <!-- 列表 + 就地编辑 -->
    <table class="table">
      <thead>
        <tr>
          <th>名称</th>
          <th>类型 / 标签</th>
          <th>位置</th>
          <th>能力</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <template v-for="e in entities" :key="e.id">
          <tr :class="{ on: editingId === e.id }">
            <td>
              <span>{{ e.name }}</span>
              <div v-if="e.desc" class="dim">{{ e.desc }}</div>
            </td>
            <td>
              <code>{{ e.kind }}</code>
              <span v-for="t in e.tags" :key="t" class="chip">{{ t }}</span>
            </td>
            <td class="dim">({{ e.row }}, {{ e.col }})</td>
            <td>
              <span v-if="e.capabilities">
                <span v-if="e.capabilities.block_move" class="chip warn">挡路</span>
                <span v-for="a in e.capabilities.interactions" :key="a" class="chip">{{ a }}</span>
                <span v-if="e.capabilities.unknown_tags.length" class="chip bad" title="未注册的标签：不贡献任何能力">
                  ⚠ {{ e.capabilities.unknown_tags.join("、") }}
                </span>
                <span v-if="e.capabilities.inactive_tags.length" class="chip bad" title="标签所属玩法包在本世界未启用">
                  ⏸ {{ e.capabilities.inactive_tags.join("、") }}
                </span>
                <span v-if="!e.capabilities.interactions.length && !e.capabilities.block_move" class="dim">
                  无声明能力
                </span>
              </span>
            </td>
            <td class="ops">
              <button class="mini-btn" @click="toggleEdit(e)">
                {{ editingId === e.id ? "收起" : "编辑" }}
              </button>
              <button class="mini-btn" @click="saveAsTemplate(e)">存为模板</button>
              <button class="mini-btn danger" @click="emit('remove', e)">删除</button>
            </td>
          </tr>
          <tr v-if="editingId === e.id" :key="`${e.id}-edit`">
            <td colspan="5" class="edit-cell">
              <div class="row">
                <input v-model="edit.name" class="mini" placeholder="名称" />
                <input v-model="edit.desc" class="mini wide" placeholder="描述" />
                <code v-if="isIdentity(e)" class="dim" title="身份化实体的类型由身份服务管理（D20）">
                  {{ e.kind }}（身份，类型不可改）
                </code>
                <input v-else v-model="edit.kind" class="mini" list="kind-options" placeholder="类型" />
                <button class="btn" @click="save(e)">保存</button>
              </div>
              <TagPicker v-model="edit.tags" :kinds="kinds" :preset="presetOf(edit.kind)" />
              <FieldForm
                :kinds="kinds"
                :kind="edit.kind"
                :tags="edit.tags"
                :attrs="edit.attrs"
                :state="edit.state"
                @update="onEditData"
              />
              <div class="caps" v-if="e.capabilities">
                <b>合并后的能力</b>
                <div>有效标签：{{ e.capabilities.active_tags.join("、") || "（无）" }}</div>
                <div>挡路：{{ e.capabilities.block_move ? "是" : "否" }}</div>
                <div>动作：{{ e.capabilities.interactions.join("、") || "（无）" }}</div>
                <div>字段：{{ e.capabilities.fields.map((f) => f.name).join("、") || "（无）" }}</div>
              </div>
            </td>
          </tr>
        </template>
      </tbody>
    </table>
    <p v-if="!entities.length" class="dim">这张图上还没有实体。</p>
  </div>
</template>

<script setup>
import { reactive, ref } from "vue";
import FieldForm from "./FieldForm.vue";
import TagPicker from "./TagPicker.vue";

const props = defineProps({
  entities: { type: Array, default: () => [] },
  kinds: { type: Array, default: () => [] },
  entityTemplates: { type: Array, default: () => [] },
  placeAt: { type: Object, default: () => ({ row: 0, col: 0 }) },
});
const emit = defineEmits(["create", "update", "remove", "save-template"]);

const error = ref("");
const editingId = ref("");
const draft = reactive({
  template_id: "",
  kind: "",
  name: "",
  desc: "",
  tags: [],
  attrs: {},
  state: {},
  row: 0,
  col: 0,
});
const edit = reactive({ kind: "", name: "", desc: "", tags: [], attrs: {}, state: {} });

function isIdentity(e) {
  return e.kind === "player";
}

function specOf(name) {
  return props.kinds.find((k) => k.tag === name) || null;
}

/** 类型预设标签（D18：类型 A = {A, C} 里的 C，不可在实例上摘除） */
function presetOf(kind) {
  return specOf(kind)?.preset_tags || [];
}

function useSelectedPos() {
  draft.row = props.placeAt.row;
  draft.col = props.placeAt.col;
}

function applyTemplate() {
  const t = props.entityTemplates.find((x) => x.id === draft.template_id);
  if (!t) return;
  const d = t.data || {};
  draft.kind = d.kind || draft.kind;
  draft.tags = [...(d.tags || [])];
  draft.name = d.name || "";
  draft.desc = d.desc || "";
  draft.attrs = { ...(d.attrs || {}) };
  draft.state = { ...(d.state || {}) };
}

function onDraftData({ attrs, state }) {
  draft.attrs = attrs;
  draft.state = state;
}
function onEditData({ attrs, state }) {
  edit.attrs = attrs;
  edit.state = state;
}

function create() {
  error.value = "";
  if (!draft.kind.trim()) {
    error.value = "类型不能为空（可以自由输入一个玩法包声明的类型名）";
    return;
  }
  emit("create", {
    kind: draft.kind.trim(),
    name: draft.name.trim() || undefined,
    desc: draft.desc,
    tags: [...draft.tags],
    attrs: draft.attrs,
    state: draft.state,
    row: Number(draft.row),
    col: Number(draft.col),
  });
  draft.name = "";
  draft.desc = "";
}

function toggleEdit(e) {
  if (editingId.value === e.id) {
    editingId.value = "";
    return;
  }
  editingId.value = e.id;
  edit.kind = e.kind;
  edit.name = e.name;
  edit.desc = e.desc || "";
  edit.tags = [...(e.tags || [])];
  edit.attrs = { ...(e.attrs || {}) };
  edit.state = { ...(e.state || {}) };
}

function save(e) {
  error.value = "";
  const patch = {
    name: edit.name,
    desc: edit.desc,
    tags: [...edit.tags],
    attrs: edit.attrs,
    state: edit.state,
  };
  if (!isIdentity(e)) patch.kind = edit.kind; // 类型改动需重建实体（下方由父级处理）
  emit("update", e, patch);
  editingId.value = "";
}

function saveAsTemplate(e) {
  emit("save-template", {
    id: `entity_${e.kind}_${Date.now().toString(36)}`,
    name: `${e.name}（模板）`,
    data: {
      kind: e.kind,
      tags: [...(e.tags || [])],
      name: e.name,
      desc: e.desc || "",
      attrs: { ...(e.attrs || {}) },
      state: { ...(e.state || {}) },
    },
  });
}

defineExpose({ setError: (msg) => (error.value = msg) });
</script>

<style scoped>
.entities {
  margin-top: 14px;
  border-top: 1px solid var(--bg-3);
  padding-top: 10px;
}
.card {
  border: 1px solid var(--bg-3);
  border-radius: 8px;
  padding: 8px;
  margin-bottom: 8px;
}
.row {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  align-items: center;
  margin-bottom: 6px;
}
.mini {
  padding: 5px 8px;
  border-radius: 6px;
  border: 1px solid var(--bg-3);
  background: var(--bg);
  color: var(--text);
  font-size: 13px;
}
.mini.wide {
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
.chip {
  display: inline-block;
  margin-left: 4px;
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
.edit-cell {
  background: var(--bg-2);
}
.caps {
  font-size: 12px;
  color: var(--text-dim);
  line-height: 1.6;
  margin-top: 6px;
}
tr.on td {
  background: var(--bg-2);
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
.dim {
  color: var(--text-dim);
  font-size: 13px;
}
</style>
