<template>
  <!-- 地块面板：名称/描述、移动、删除、存为模板、套用模板 -->
  <div class="tile-panel">
    <h3>
      地块 ({{ pos.row }}, {{ pos.col }})
      <button v-if="tile" class="mini-btn danger" @click="emit('remove')">删除地块</button>
    </h3>

    <div class="row coord-row">
      <span class="dim">坐标</span>
      <input v-model.number="row" type="number" class="num" @change="emit('pick-pos', { row, col })" />
      <input v-model.number="col" type="number" class="num" @change="emit('pick-pos', { row, col })" />
      <span class="dim">（可直接输入任意坐标，含负数——包围盒之外也能去）</span>
    </div>

    <label class="field">
      名称
      <input v-model="name" placeholder="地块名称" />
    </label>
    <label class="field">
      描述（纯文本，或分时段 JSON）
      <textarea v-model="description" rows="3" placeholder="如：小镇广场，人来人往。"></textarea>
    </label>
    <div class="row">
      <button class="btn" @click="saveMeta">{{ tile ? "保存地块" : "在此新建地块" }}</button>
      <button v-if="tile" class="mini-btn" @click="saveAsTemplate">存为地块模板</button>
    </div>

    <template v-if="tile">
      <h4>移动到别处</h4>
      <p class="dim">
        原子操作：自身坐标、全图指向它的连接、以及它上面的实体一起搬（内核已有能力）。
      </p>
      <div class="row">
        <input v-model.number="toRow" type="number" class="num" placeholder="新行" />
        <input v-model.number="toCol" type="number" class="num" placeholder="新列" />
        <button class="btn" @click="emit('move', { row: toRow, col: toCol })">移动</button>
      </div>
    </template>

    <h4>套用地块模板</h4>
    <p class="dim">模板里的同图目标会按放置位置平移，跨图目标原样复制。</p>
    <div class="row">
      <select v-model="picked" class="mini">
        <option value="">选择模板…</option>
        <option v-for="t in templates" :key="t.id" :value="t.id">
          {{ t.name }}{{ t.source === "play" ? `（${t.play_id}）` : "" }}
        </option>
      </select>
      <button class="btn" :disabled="!picked" @click="emit('apply-template', picked)">
        {{ tile ? "套用到本格（需先删掉本格）" : "套用到本坐标" }}
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from "vue";

const props = defineProps({
  tile: { type: Object, default: null },
  pos: { type: Object, required: true },
  templates: { type: Array, default: () => [] },
});
const emit = defineEmits([
  "save-meta",
  "move",
  "remove",
  "save-template",
  "apply-template",
  "pick-pos",
]);

const name = ref("");
const description = ref("");
const row = ref(0);
const col = ref(0);
const toRow = ref(0);
const toCol = ref(0);
const picked = ref("");

function descToText(desc) {
  if (!desc) return "";
  if (typeof desc === "string") return desc;
  const periods = desc.periods || [];
  if (periods.length === 1 && periods[0].items?.length === 1) {
    return periods[0].items[0].text || "";
  }
  return JSON.stringify(desc, null, 2);
}

function descToPayload(text) {
  if (!text.trim()) return null;
  try {
    const parsed = JSON.parse(text);
    if (parsed && typeof parsed === "object") return parsed;
    return text;
  } catch {
    return text;
  }
}

function sync() {
  name.value = props.tile ? props.tile.name : "";
  description.value = props.tile ? descToText(props.tile.description) : "";
  row.value = props.pos.row;
  col.value = props.pos.col;
  toRow.value = props.pos.row;
  toCol.value = props.pos.col;
}

function saveMeta() {
  emit("save-meta", { name: name.value, description: descToPayload(description.value) });
}

function saveAsTemplate() {
  if (!props.tile) return;
  const row = props.tile.row;
  const col = props.tile.col;
  // 存成**相对偏移**：同图目标减去本格坐标（放置时再按新位置平移）
  const connections = {};
  for (const [dir, slot] of Object.entries(props.tile.connections || {})) {
    connections[dir] = {
      enabled: slot.enabled,
      paths: (slot.paths || []).map((p) => ({
        label: p.label || null,
        reveal_target: p.reveal_target,
        targets: (p.targets || []).map((t) =>
          t.map_id
            ? { map_id: t.map_id, row: t.row, col: t.col, weight: t.weight }
            : { dr: t.row - row, dc: t.col - col, weight: t.weight }
        ),
      })),
    };
  }
  emit("save-template", {
    id: `loc_${Date.now().toString(36)}`,
    name: `${props.tile.name}（模板）`,
    data: { name: props.tile.name, description: props.tile.description, connections },
  });
}

watch(() => [props.tile, props.pos], sync, { immediate: true, deep: true });
</script>

<style scoped>
.tile-panel {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
h3,
h4 {
  margin: 4px 0;
  display: flex;
  justify-content: space-between;
  align-items: center;
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
  padding: 7px 9px;
  border-radius: 8px;
  border: 1px solid var(--bg-3);
  background: var(--bg);
  color: var(--text);
  font-size: 13px;
}
.row {
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
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
.mini {
  padding: 4px 6px;
  border-radius: 6px;
  border: 1px solid var(--bg-3);
  background: var(--bg);
  color: var(--text);
  font-size: 12px;
}
.mini-btn {
  border: none;
  background: transparent;
  color: var(--text-dim);
  font-size: 12px;
  cursor: pointer;
  padding: 2px 4px;
}
.mini-btn.danger:hover {
  color: var(--danger);
}
.dim {
  color: var(--text-dim);
  font-size: 12px;
  margin: 0;
  line-height: 1.5;
}
</style>
