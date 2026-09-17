<template>
  <!-- 地图网格：单选/多选（Ctrl）/框选（按住拖过格子）/方向箭头/实体徽标 -->
  <div class="grid-wrap">
    <div
      class="grid"
      :style="{ gridTemplateColumns: `repeat(${cols}, 68px)` }"
      @mousedown="onMouseDown"
      @mouseup="onMouseUp"
      @mouseleave="dragging = false"
    >
      <button
        v-for="cell in cells"
        :key="cell.key"
        class="cell"
        :class="{
          empty: !cell.loc,
          sel: isSelected(cell),
          primary: isPrimary(cell),
          picking: inRect(cell),
        }"
        :data-cell="cell.key"
        @mouseenter="onMouseEnter(cell)"
        @click="onClick(cell, $event)"
      >
        <template v-if="cell.loc">
          <span class="cell-name">{{ shortName(cell.loc.name) }}</span>
          <span class="dirs">
            <span v-for="d in activeDirs(cell.loc)" :key="d" class="dir" :title="dirLabel[d]">
              {{ dirArrow[d] }}
            </span>
            <span v-if="!activeDirs(cell.loc).length" class="dir none">·</span>
          </span>
          <span v-if="cell.entities.length" class="cell-badge" :title="cell.entities.map((e) => e.name).join('、')">
            {{ cell.entities.length }}
          </span>
          <span v-for="e in cell.entities.slice(0, 3)" :key="e.id" class="dot" />
        </template>
        <span v-else class="cell-add" title="点击新建地块">＋</span>
      </button>
    </div>
    <p class="dim">
      行 {{ minRow }}..{{ maxRow }} × 列 {{ minCol }}..{{ maxCol }}
      ——单击选中（点空格 = 在此新建），Ctrl/⌘ 点击多选，**按住左键拖过格子框选**，
      选中后可整体复制/粘贴。
    </p>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";

const props = defineProps({
  locations: { type: Array, default: () => [] },
  entities: { type: Array, default: () => [] },
  selection: { type: Array, default: () => [] }, // ["row:col", ...]
  primary: { type: Object, default: null }, // {row, col}
  span: { type: Number, default: 12 },
});
const emit = defineEmits(["pick", "rect"]);

const DIR_KEYS = ["up", "right", "down", "left"];
const dirLabel = { up: "北↑", right: "东→", down: "南↓", left: "西←" };
const dirArrow = { up: "▲", right: "▶", down: "▼", left: "◀" };

const dragging = ref(false);
const dragFrom = ref(null);
const rectTo = ref(null);

const minRow = computed(() =>
  props.locations.length ? Math.min(...props.locations.map((l) => l.row)) : 0
);
// 右下各多留一行/一列：包围盒之外也要有可点的空格，否则"在别处新建地块"没入口
// （配合地块面板的坐标输入，负方向也能去）
const maxRow = computed(() =>
  props.locations.length ? Math.max(...props.locations.map((l) => l.row)) + 1 : props.span - 1
);
const minCol = computed(() =>
  props.locations.length ? Math.min(...props.locations.map((l) => l.col)) : 0
);
const maxCol = computed(() =>
  props.locations.length ? Math.max(...props.locations.map((l) => l.col)) + 1 : props.span - 1
);
const cols = computed(() => maxCol.value - minCol.value + 1);

const cells = computed(() => {
  const byPos = {};
  for (const l of props.locations) byPos[`${l.row}:${l.col}`] = l;
  const ents = {};
  for (const e of props.entities) {
    const key = `${e.row}:${e.col}`;
    (ents[key] = ents[key] || []).push(e);
  }
  const out = [];
  for (let r = minRow.value; r <= maxRow.value; r += 1) {
    for (let c = minCol.value; c <= maxCol.value; c += 1) {
      const key = `${r}:${c}`;
      out.push({ row: r, col: c, key, loc: byPos[key] || null, entities: ents[key] || [] });
    }
  }
  return out;
});

function shortName(name) {
  return name && name.length > 5 ? `${name.slice(0, 5)}…` : name || "";
}

function activeDirs(loc) {
  return DIR_KEYS.filter((d) => loc.connections?.[d]?.enabled);
}

function isSelected(cell) {
  return props.selection.includes(cell.key);
}
function isPrimary(cell) {
  return Boolean(props.primary && props.primary.row === cell.row && props.primary.col === cell.col);
}

/** 框选矩形（拖拽中实时高亮） */
function inRect(cell) {
  if (!dragging.value || !dragFrom.value || !rectTo.value) return false;
  const r1 = Math.min(dragFrom.value.row, rectTo.value.row);
  const r2 = Math.max(dragFrom.value.row, rectTo.value.row);
  const c1 = Math.min(dragFrom.value.col, rectTo.value.col);
  const c2 = Math.max(dragFrom.value.col, rectTo.value.col);
  return cell.row >= r1 && cell.row <= r2 && cell.col >= c1 && cell.col <= c2;
}

function onMouseDown(cell) {
  dragging.value = true;
  dragFrom.value = cell;
  rectTo.value = cell;
}
function onMouseEnter(cell) {
  if (dragging.value) rectTo.value = cell;
}
function onMouseUp() {
  const from = dragFrom.value;
  const to = rectTo.value;
  dragging.value = false;
  dragFrom.value = null;
  rectTo.value = null;
  if (!from || !to) return;
  if (from.key !== to.key) {
    // 拖过多个格子 = 框选（不触发单击语义）
    const r1 = Math.min(from.row, to.row);
    const r2 = Math.max(from.row, to.row);
    const c1 = Math.min(from.col, to.col);
    const c2 = Math.max(from.col, to.col);
    const keys = [];
    for (let r = r1; r <= r2; r += 1) {
      for (let c = c1; c <= c2; c += 1) keys.push(`${r}:${c}`);
    }
    emit("rect", keys);
  }
}

function onClick(cell, event) {
  emit("pick", cell, { ctrl: event.ctrlKey || event.metaKey, shift: event.shiftKey });
}

onMounted(() => window.addEventListener("mouseup", onMouseUp));
onUnmounted(() => window.removeEventListener("mouseup", onMouseUp));
</script>

<style scoped>
.grid-wrap {
  flex: 1;
  min-width: 0;
  overflow: auto;
}
.grid {
  display: grid;
  gap: 3px;
  width: max-content;
  user-select: none;
}
.cell {
  width: 68px;
  height: 68px;
  border: 1px solid var(--bg-3);
  border-radius: 8px;
  background: var(--bg-2);
  color: var(--text);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 1px;
  padding: 2px;
  font-size: 15px;
  position: relative;
}
.cell.empty {
  background: transparent;
  border-style: dashed;
  color: var(--text-dim);
}
.cell.sel {
  border-color: var(--accent);
  background: var(--bg-3);
}
.cell.primary {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}
.cell.picking {
  border-color: var(--accent);
  border-style: dashed;
}
.cell-name {
  font-size: 10px;
  line-height: 1.1;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dirs {
  display: flex;
  gap: 2px;
  font-size: 9px;
  color: var(--accent);
  line-height: 1;
}
.dir.none {
  color: var(--text-dim);
}
.cell-badge {
  position: absolute;
  top: 2px;
  right: 3px;
  background: var(--accent-dim);
  border-radius: 8px;
  font-size: 10px;
  padding: 0 4px;
  color: #fff;
}
.dot {
  position: absolute;
  bottom: 3px;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--text-dim);
}
.dot:nth-of-type(1) {
  left: 6px;
}
.dot:nth-of-type(2) {
  left: 14px;
}
.dot:nth-of-type(3) {
  left: 22px;
}
.dim {
  color: var(--text-dim);
  font-size: 13px;
}
</style>
