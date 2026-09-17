<template>
  <!-- 模板管理视图（D22：地块 / 实体两类；玩法包注册 + 管理端本地） -->
  <div class="template-manager">
    <div class="toolbar">
      <select v-model="scope" class="mini">
        <option value="">全部类别</option>
        <option value="location">地块模板</option>
        <option value="entity">实体模板</option>
      </select>
      <input v-model="q" class="mini search" placeholder="搜索模板名…" />
      <span class="grow" />
      <span class="dim">{{ list.length }} 个模板</span>
    </div>
    <p class="dim">
      玩法包注册的模板随包加载/卸载（标「玩法包」）；「本地」是管理员存在库里的，可删。
      新建方式：在「地图编辑」视图里选中地块 →「存为地块模板」；在「实体」视图详情里 →「存为模板」。
    </p>

    <table class="table">
      <thead>
        <tr>
          <th>名称</th>
          <th>类别</th>
          <th>来源</th>
          <th>负载</th>
          <th class="ops-col">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="t in list" :key="t.id" :class="{ on: picked === t.id }" @click="picked = t.id">
          <td>{{ t.name }}</td>
          <td>{{ t.scope === "location" ? "地块" : "实体" }}</td>
          <td>
            <span class="chip" :class="{ play: t.source === 'play' }">
              {{ t.source === "play" ? `玩法包 ${t.play_id}` : "本地" }}
            </span>
          </td>
          <td class="dim"><code>{{ summary(t) }}</code></td>
          <td class="ops-col">
            <button
              v-if="t.scope === 'location'"
              class="mini-btn"
              title="套用到下面填的坐标"
              @click.stop="apply(t)"
            >
              套用
            </button>
            <button v-if="t.source !== 'play'" class="mini-btn danger" @click.stop="emit('remove', t)">
              删除
            </button>
          </td>
        </tr>
        <tr v-if="!list.length">
          <td colspan="5" class="dim">还没有模板。</td>
        </tr>
      </tbody>
    </table>

    <div v-if="pickedTemplate && pickedTemplate.scope === 'location'" class="apply-bar">
      <b>套用「{{ pickedTemplate.name }}」到：</b>
      <input v-model.number="row" type="number" class="num" placeholder="行" />
      <input v-model.number="col" type="number" class="num" placeholder="列" />
      <button class="btn" @click="apply(pickedTemplate)">套用</button>
      <span class="dim">同图出口按放置位置平移，跨图出口原样；目标格已有地块会被拒绝。</span>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, watch } from "vue";

const props = defineProps({
  templates: { type: Array, default: () => [] },
  primary: { type: Object, default: null }, // 地图视图当前选中的格（用作默认套用坐标）
});
const emit = defineEmits(["remove", "apply"]);

const scope = ref("");
const q = ref("");
const picked = ref("");
const row = ref(0);
const col = ref(0);

watch(
  () => props.primary,
  (v) => {
    if (v) {
      row.value = v.row;
      col.value = v.col;
    }
  },
  { immediate: true }
);

const list = computed(() => {
  const needle = q.value.trim().toLowerCase();
  return props.templates.filter((t) => {
    if (scope.value && t.scope !== scope.value) return false;
    if (!needle) return true;
    return (t.name || "").toLowerCase().includes(needle);
  });
});

const pickedTemplate = computed(() => list.value.find((t) => t.id === picked.value) || null);

function summary(t) {
  const data = t.data || {};
  if (t.scope === "location") {
    const paths = Object.values(data.connections || {}).reduce(
      (n, slot) => n + (slot.enabled ? (slot.paths || []).length : 0),
      0
    );
    return `${data.name || "（无名称）"} · 出口 ${paths}`;
  }
  const tags = data.tags?.length ? ` · 标签 ${data.tags.join("/")}` : "";
  return `${data.kind || "?"}${tags}`;
}

function apply(t) {
  emit("apply", { templateId: t.id, row: Number(row.value), col: Number(col.value) });
}
</script>

<style scoped>
.template-manager {
  flex: 1;
  min-height: 0;
  overflow: auto;
}
.toolbar {
  display: flex;
  gap: 6px;
  align-items: center;
  margin-bottom: 6px;
}
.grow {
  flex: 1;
}
.apply-bar {
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
  margin-top: 10px;
  padding: 8px 10px;
  border: 1px solid var(--accent);
  border-radius: 8px;
  font-size: 13px;
}
tr.on td {
  background: var(--bg-3);
}
.ops-col {
  white-space: nowrap;
  text-align: right;
}
.chip {
  font-size: 11px;
  border: 1px solid var(--bg-3);
  border-radius: 999px;
  padding: 0 6px;
  color: var(--text-dim);
}
.chip.play {
  color: var(--accent);
  border-color: var(--accent);
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
  min-width: 200px;
}
.num {
  width: 68px;
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
  padding: 2px 5px;
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
  font-size: 12px;
}
</style>
