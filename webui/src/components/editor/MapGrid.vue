<template>
  <!-- 可视化地图：缩放 / 平移 / 框选 / 方向箭头（地图编辑视图的主区域） -->
  <div class="canvas-wrap">
    <div class="canvas-toolbar">
      <button class="mini-btn" title="缩小" @click="zoomBy(1 / 1.2)">－</button>
      <span class="zoom-label">{{ Math.round(scale * 100) }}%</span>
      <button class="mini-btn" title="放大" @click="zoomBy(1.2)">＋</button>
      <button class="mini-btn" title="适应窗口" @click="fit">适应</button>
      <button class="mini-btn" title="还原 100%" @click="resetView">1:1</button>
      <span class="sep" />
      <button
        class="mini-btn"
        :class="{ on: panMode }"
        :title="panMode ? '平移模式：拖动任意位置都平移' : '框选模式：拖动格子框选，拖空白处平移'"
        @click="panMode = !panMode"
      >
        {{ panMode ? "✋ 平移" : "▭ 框选" }}
      </button>
      <span class="hint">滚轮缩放 · 拖空白平移 · {{ panMode ? "点格子选中" : "拖格子框选" }}</span>
    </div>

    <div
      ref="canvasEl"
      class="canvas"
      :class="{ panning: panMode, dragging: dragging }"
      @wheel.prevent="onWheel"
      @mousedown="onCanvasDown"
      @mouseleave="dragging = false"
    >
      <div ref="stageEl" class="stage" :style="stageStyle">
        <div
          class="grid"
          :style="{ gridTemplateColumns: `repeat(${cols}, ${CELL}px)` }"
          @mousedown.stop="onGridDown"
        >
          <button
            v-for="cellBox in cells"
            :key="cellBox.key"
            class="cell"
            :class="{
              empty: !cellBox.loc,
              sel: isSelected(cellBox),
              primary: isPrimary(cellBox),
              picking: inRect(cellBox),
            }"
            :style="{ width: `${CELL}px`, height: `${CELL}px` }"
            :data-cell="cellBox.key"
            @mouseenter="onMouseEnter(cellBox)"
            @click="onClick(cellBox, $event)"
          >
            <template v-if="cellBox.loc">
              <span class="cell-name">{{ shortName(cellBox.loc.name) }}</span>
              <span class="dirs">
                <span v-for="d in activeDirs(cellBox.loc)" :key="d" class="dir" :title="dirLabel[d]">
                  {{ dirArrow[d] }}
                </span>
                <span v-if="!activeDirs(cellBox.loc).length" class="dir none">·</span>
              </span>
              <span
                v-if="cellBox.entities.length"
                class="cell-badge"
                :title="cellBox.entities.map((e) => e.name).join('、')"
              >
                {{ cellBox.entities.length }}
              </span>
            </template>
            <span v-else class="cell-add" title="点击新建地块">＋</span>
          </button>
        </div>
      </div>
    </div>
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

const CELL = 68; // 100% 时的格子边长（间距另计）
const GAP = 3;
const BASE = CELL + GAP;

const canvasEl = ref(null);
const stageEl = ref(null);
const scale = ref(1);
const tx = ref(0);
const ty = ref(0);
const panMode = ref(false);
const dragging = ref(false);
const dragFrom = ref(null);
const rectTo = ref(null);
const panFrom = ref(null);
const moved = ref(0);

const minRow = computed(() =>
  props.locations.length ? Math.min(...props.locations.map((l) => l.row)) : 0
);
// 右下多留一行一列：包围盒之外也有可点的空格（配合坐标输入框可达任意位置）
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
const rows = computed(() => maxRow.value - minRow.value + 1);

const stageStyle = computed(() => ({
  transform: `translate(${tx.value}px, ${ty.value}px) scale(${scale.value})`,
}));

const cells = computed(() => {
  const byPos = {};
  for (const loc of props.locations) byPos[`${loc.row}:${loc.col}`] = loc;
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
function isSelected(box) {
  return props.selection.includes(box.key);
}
function isPrimary(box) {
  return Boolean(props.primary && props.primary.row === box.row && props.primary.col === box.col);
}
function inRect(box) {
  if (!dragging.value || !dragFrom.value || !rectTo.value || panMode.value) return false;
  const r1 = Math.min(dragFrom.value.row, rectTo.value.row);
  const r2 = Math.max(dragFrom.value.row, rectTo.value.row);
  const c1 = Math.min(dragFrom.value.col, rectTo.value.col);
  const c2 = Math.max(dragFrom.value.col, rectTo.value.col);
  return box.row >= r1 && box.row <= r2 && box.col >= c1 && box.col <= c2;
}

// ---------- 缩放 / 平移 ----------

function clampScale(value) {
  return Math.min(2.5, Math.max(0.25, value));
}

function zoomBy(factor, origin) {
  const canvas = canvasEl.value;
  const rect = canvas ? canvas.getBoundingClientRect() : { left: 0, top: 0, width: 0, height: 0 };
  const mx = origin?.x ?? rect.width / 2;
  const my = origin?.y ?? rect.height / 2;
  const prev = scale.value;
  const next = clampScale(prev * factor);
  if (next === prev) return;
  tx.value = mx - (mx - tx.value) * (next / prev);
  ty.value = my - (my - ty.value) * (next / prev);
  scale.value = next;
}

function onWheel(event) {
  const rect = canvasEl.value.getBoundingClientRect();
  zoomBy(event.deltaY < 0 ? 1.12 : 1 / 1.12, {
    x: event.clientX - rect.left,
    y: event.clientY - rect.top,
  });
}

function resetView() {
  scale.value = 1;
  tx.value = 0;
  ty.value = 0;
}

/** 适应窗口：按网格自然尺寸缩放并居中（小图最多放到 150%，别把三个格子撑满屏）。 */
function fit() {
  const canvas = canvasEl.value;
  const stage = stageEl.value;
  if (!canvas || !stage) return;
  const cw = canvas.clientWidth - 24;
  const ch = canvas.clientHeight - 24;
  const sw = cols.value * BASE;
  const sh = rows.value * BASE;
  if (!sw || !sh) return;
  const next = Math.min(1.5, Math.max(0.25, Math.min(cw / sw, ch / sh)));
  scale.value = next;
  tx.value = Math.max(0, (canvas.clientWidth - sw * next) / 2);
  ty.value = Math.max(0, (canvas.clientHeight - sh * next) / 2);
}

function beginPan(event) {
  dragging.value = true;
  panFrom.value = { x: event.clientX, y: event.clientY, tx: tx.value, ty: ty.value };
  moved.value = 0;
}

/** 画布空白处 = 平移（格子上按下的事件已被 .grid 的 stopPropagation 拦下）。 */
function onCanvasDown(event) {
  if (event.button !== 0) return;
  beginPan(event);
}

/** 网格内按下：平移模式或落在空白 = 平移；落在格子上 = 开始框选。 */
function onGridDown(event) {
  if (event.button !== 0) return;
  const cellEl = event.target.closest?.(".cell");
  if (panMode.value || !cellEl) {
    beginPan(event);
    return;
  }
  const box = cells.value.find((b) => b.key === cellEl.dataset.cell);
  if (!box) return;
  dragging.value = true;
  dragFrom.value = box;
  rectTo.value = box;
}

function onMouseEnter(box) {
  if (panFrom.value) return;
  if (dragging.value) rectTo.value = box;
}

function onMove(event) {
  if (!panFrom.value) return;
  const dx = event.clientX - panFrom.value.x;
  const dy = event.clientY - panFrom.value.y;
  moved.value = Math.max(moved.value, Math.abs(dx) + Math.abs(dy));
  tx.value = panFrom.value.tx + dx;
  ty.value = panFrom.value.ty + dy;
}

let suppressClick = false;

function onUp() {
  const panning = Boolean(panFrom.value);
  const panned = moved.value > 4;
  const from = dragFrom.value;
  const to = rectTo.value;
  panFrom.value = null;
  dragging.value = false;
  dragFrom.value = null;
  rectTo.value = null;
  if (panning) {
    if (panned) suppressClick = true; // 平移过就别把这次鼠标当点击
    return;
  }
  if (!from || !to || from.key === to.key) return;
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

function onClick(box, event) {
  if (suppressClick) {
    suppressClick = false;
    return;
  }
  emit("pick", box, { ctrl: event.ctrlKey || event.metaKey, shift: event.shiftKey });
}

onMounted(() => {
  window.addEventListener("mousemove", onMove);
  window.addEventListener("mouseup", onUp);
});
onUnmounted(() => {
  window.removeEventListener("mousemove", onMove);
  window.removeEventListener("mouseup", onUp);
});

defineExpose({ fit, resetView, zoomBy });
</script>

<style scoped>
.canvas-wrap {
  flex: 1;
  min-width: 0;
  min-height: 0;
  display: flex;
  flex-direction: column;
  border: 1px solid var(--bg-3);
  border-radius: 10px;
  overflow: hidden;
  background: var(--bg-2);
}
.canvas-toolbar {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 5px 8px;
  border-bottom: 1px solid var(--bg-3);
  font-size: 12px;
  flex-shrink: 0;
}
.zoom-label {
  min-width: 42px;
  text-align: center;
  color: var(--text-dim);
}
.sep {
  width: 1px;
  height: 14px;
  background: var(--bg-3);
  margin: 0 4px;
}
.hint {
  margin-left: auto;
  color: var(--text-dim);
  font-size: 11px;
}
.canvas {
  flex: 1;
  min-height: 0;
  position: relative;
  overflow: hidden;
  cursor: default;
  background-image: radial-gradient(var(--bg-3) 1px, transparent 1px);
  background-size: 16px 16px;
}
.canvas.panning {
  cursor: grab;
}
.canvas.dragging {
  cursor: grabbing;
}
.stage {
  position: absolute;
  left: 0;
  top: 0;
  transform-origin: 0 0;
  will-change: transform;
}
.grid {
  display: grid;
  gap: 3px;
  width: max-content;
  user-select: none;
}
.cell {
  border: 1px solid var(--bg-3);
  border-radius: 8px;
  background: var(--bg);
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
.mini-btn {
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-dim);
  font-size: 12px;
  cursor: pointer;
  padding: 2px 6px;
  border-radius: 6px;
}
.mini-btn:hover {
  color: var(--accent);
  background: var(--bg-3);
}
.mini-btn.on {
  color: var(--accent);
  border-color: var(--accent);
}
</style>
