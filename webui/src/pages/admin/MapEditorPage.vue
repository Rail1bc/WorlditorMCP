<template>
  <section class="card">
    <h2 class="head">
      地图编辑器
      <code class="dim">{{ mapId || "未选择" }}</code>
      <button class="btn btn-ghost" @click="goBack">← 返回世界页</button>
    </h2>
    <p v-if="error" class="error-text">{{ error }}</p>

    <!-- 未选地图：列表选择 -->
    <div v-if="!mapId" class="picker">
      <button
        v-for="m in maps"
        :key="m.id"
        class="page-entry"
        @click="openMap(m.id)"
      >
        <span>🗺 {{ m.name || m.id }}</span>
        <span class="dim">
          {{ m.location_count }} 地块 · {{ m.entity_count }} 实体
          <template v-if="m.world_id"> · 属于 {{ m.world_id }}</template>
        </span>
      </button>
      <button class="btn" @click="createMapForm = !createMapForm">＋ 新建地图</button>
      <div v-if="createMapForm" class="inline-form">
        <input v-model="nm.id" placeholder="地图 id（如 arena）" />
        <input v-model="nm.name" placeholder="名称" />
        <button class="btn" @click="createMap">创建</button>
      </div>
    </div>

    <template v-else>
      <!-- 地图元信息 -->
      <div class="map-meta">
        <label class="field">
          名称
          <input v-model="meta.name" />
        </label>
        <label class="field">
          可见性
          <select v-model="meta.visible">
            <option value="public">public（所有人可见）</option>
            <option value="private">private（在场玩家可见）</option>
          </select>
        </label>
        <label class="field">
          出生点
          <span class="pos-inputs">
            <input v-model.number="meta.spawn_row" type="number" /> ×
            <input v-model.number="meta.spawn_col" type="number" />
          </span>
        </label>
        <label class="field">
          时区
          <input v-model="meta.timezone" placeholder="Asia/Shanghai" />
        </label>
        <button class="btn" @click="saveMeta">保存地图信息</button>
        <button class="btn btn-danger" @click="removeMap">删除地图</button>
      </div>

      <!-- 编辑器主体：网格 + 侧栏 -->
      <div class="editor">
        <div class="grid-wrap">
          <div class="grid" :style="{ gridTemplateColumns: `repeat(${cols}, 64px)` }">
            <button
              v-for="cell in gridCells"
              :key="cell.row + ':' + cell.col"
              class="cell"
              :class="{ empty: !cell.loc, on: sel && sel.row === cell.row && sel.col === cell.col }"
              @click="select(cell)"
            >
              <template v-if="cell.loc">
                <span class="cell-name">{{ shortName(cell.loc.name) }}</span>
                <span class="cell-dirs">{{ dirMarks(cell.loc.connections) }}</span>
                <span v-if="cell.entities.length" class="cell-badge">
                  {{ cell.entities.length }}
                </span>
              </template>
              <span v-else class="cell-add" title="点击新建地块">＋</span>
            </button>
          </div>
          <p class="dim">
            行 {{ minRow }}..{{ maxRow }} × 列 {{ minCol }}..{{ maxCol }}（点空白格新建地块，
            点已有地块编辑）
          </p>
        </div>

        <aside class="side">
          <template v-if="sel">
            <h3>
              地块 ({{ sel.row }}, {{ sel.col }})
              <button
                v-if="sel.loc"
                class="btn btn-danger"
                @click="removeLocation(sel)"
              >
                删除地块
              </button>
            </h3>
            <label class="field">
              名称
              <input v-model="locForm.name" placeholder="地块名称" />
            </label>
            <label class="field">
              描述（纯文本或分时段 JSON）
              <textarea
                v-model="locForm.description"
                rows="3"
                placeholder="如：小镇广场，人来人往。"
              ></textarea>
            </label>
            <button class="btn" @click="saveLocation">保存地块</button>

            <!-- 连接 -->
            <h4>四向连接</h4>
            <div v-for="(slot, dir) in connForm" :key="dir" class="conn-card">
              <label class="conn-head">
                <input type="checkbox" v-model="slot.enabled" />
                {{ dirLabel[dir] }}
              </label>
              <div v-for="(p, i) in slot.paths" :key="i" class="conn-path">
                <input v-model="p.label" placeholder="路径文案（可选）" />
                <input
                  v-model="p.targetsText"
                  placeholder="目标 row,col（分号分隔）"
                />
                <label class="mini-label">
                  <input type="checkbox" v-model="p.reveal_target" /> 揭示
                </label>
                <button class="mini-btn danger" @click="slot.paths.splice(i, 1)">×</button>
              </div>
              <button class="mini-btn" @click="slot.paths.push(newPath())">
                ＋ 添加路径
              </button>
            </div>
            <button v-if="sel.loc" class="btn" @click="saveConnections">保存连接</button>
          </template>
          <p v-else class="dim">点击网格中的地块进行编辑；空白格 = 在此坐标新建</p>
        </aside>
      </div>

      <!-- 实体管理 -->
      <div class="block">
        <h3>实体（{{ entities.length }}）</h3>
        <div class="inline-form">
          <input v-model="nf.kind" placeholder="kind（如 merchant）" />
          <input v-model="nf.name" placeholder="名称" />
          <input v-model="nf.desc" placeholder="描述（可选）" />
          <span class="dim">
            @ ({{ nf.row }}, {{ nf.col }})
            <button class="mini-btn" @click="nf.row = sel?.row ?? 0; nf.col = sel?.col ?? 0">
              用选中格
            </button>
          </span>
          <button class="btn" @click="createEntity">放置</button>
        </div>
        <table class="table">
          <thead>
            <tr>
              <th>名称</th>
              <th>kind</th>
              <th>位置</th>
              <th>动作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="e in entities" :key="e.id">
              <td>
                <input class="mini" v-model="e.name" @change="saveEntityName(e)" />
              </td>
              <td>{{ e.kind }}</td>
              <td class="dim">{{ e.map_id }} ({{ e.row }}, {{ e.col }})</td>
              <td class="ops">
                <button
                  class="btn btn-ghost"
                  @click="locate(e)"
                >
                  定位
                </button>
                <button class="btn btn-danger" @click="removeEntity(e)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 模板管理 -->
      <div class="block">
        <h3>模板（{{ templates.length }}）</h3>
        <div class="inline-form">
          <input v-model="nt.id" placeholder="模板 id" />
          <input v-model="nt.name" placeholder="模板名" />
          <input v-model="nt.data" placeholder='data JSON（如 {"name":"X"}）' />
          <button class="btn" @click="createTemplate">创建</button>
        </div>
        <table class="table">
          <tbody>
            <tr v-for="t in templates" :key="t.id">
              <td><code>{{ t.id }}</code></td>
              <td>{{ t.name }}</td>
              <td class="dim"><code>{{ JSON.stringify(t.data) }}</code></td>
              <td class="ops">
                <button class="btn btn-danger" @click="removeTemplate(t)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </template>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { apiGet, apiPost, apiPatch, apiDelete } from "../../api";

const DIR_KEYS = ["up", "right", "down", "left"];
const dirLabel = { up: "北↑", right: "东→", down: "南↓", left: "西←" };

const maps = ref([]);
const mapId = ref("");
const meta = reactive({ name: "", visible: "public", spawn_row: 0, spawn_col: 0, timezone: "" });
const locations = ref([]);
const entities = ref([]);
const templates = ref([]);
const error = ref("");
const sel = ref(null);
const locForm = reactive({ name: "", description: "" });
const connForm = reactive({});
const nf = reactive({ kind: "", name: "", desc: "", row: 0, col: 0 });
const nt = reactive({ id: "", name: "", data: "" });
const nm = reactive({ id: "", name: "" });
const createMapForm = ref(false);
const gridSpan = 12; // 空地图默认网格跨度

function syncFromHash() {
  const parts = location.hash.replace(/^#/, "").split("/").filter(Boolean);
  mapId.value = parts[2] || "";
}

const minRow = computed(() =>
  locations.value.length ? Math.min(...locations.value.map((l) => l.row)) : 0
);
const maxRow = computed(() =>
  locations.value.length ? Math.max(...locations.value.map((l) => l.row)) : gridSpan - 1
);
const minCol = computed(() =>
  locations.value.length ? Math.min(...locations.value.map((l) => l.col)) : 0
);
const maxCol = computed(() =>
  locations.value.length ? Math.max(...locations.value.map((l) => l.col)) : gridSpan - 1
);
const cols = computed(() => maxCol.value - minCol.value + 1);

const gridCells = computed(() => {
  const byPos = {};
  for (const l of locations.value) byPos[`${l.row}:${l.col}`] = l;
  const out = [];
  for (let r = minRow.value; r <= maxRow.value; r++) {
    for (let c = minCol.value; c <= maxCol.value; c++) {
      const loc = byPos[`${r}:${c}`] || null;
      const ents = loc
        ? entities.value.filter((e) => e.row === r && e.col === c)
        : [];
      out.push({ row: r, col: c, loc, entities: ents });
    }
  }
  return out;
});

function shortName(name) {
  return name.length > 5 ? name.slice(0, 5) + "…" : name;
}

function dirMarks(conns) {
  return DIR_KEYS.map((d) => (conns[d]?.enabled ? "●" : "○")).join("");
}

function newPath() {
  return { label: "", targetsText: "", reveal_target: true };
}

async function loadMaps() {
  try {
    maps.value = (await apiGet("/admin/maps")).maps || [];
  } catch (e) {
    error.value = e.message;
  }
}

async function loadDetail() {
  error.value = "";
  try {
    const data = await apiGet(`/admin/maps/${mapId.value}`);
    Object.assign(meta, {
      name: data.map.name,
      visible: data.map.visible,
      spawn_row: data.map.spawn_row,
      spawn_col: data.map.spawn_col,
      timezone: data.map.timezone || "",
    });
    locations.value = data.locations || [];
    entities.value = data.entities || [];
    templates.value = (await apiGet("/admin/templates")).templates || [];
    sel.value = null;
  } catch (e) {
    error.value = e.message;
  }
}

function select(cell) {
  sel.value = cell;
  if (cell.loc) {
    locForm.name = cell.loc.name;
    locForm.description = descToText(cell.loc.description);
    for (const d of DIR_KEYS) {
      const slot = cell.loc.connections[d] || { enabled: false, paths: [] };
      connForm[d] = {
        enabled: !!slot.enabled,
        paths: (slot.paths || []).map((p) => ({
          label: p.label || "",
          targetsText: (p.targets || [])
            .map((t) => `${t.row},${t.col}`)
            .join("; "),
          reveal_target: p.reveal_target,
        })),
      };
    }
  } else {
    locForm.name = "";
    locForm.description = "";
    for (const d of DIR_KEYS) connForm[d] = { enabled: false, paths: [newPath()] };
  }
}

function descToText(desc) {
  if (!desc) return "";
  if (typeof desc === "string") return desc;
  // 分时段结构：单时段单条 → 纯文本；否则 JSON
  const periods = desc.periods || [];
  if (
    periods.length === 1 &&
    periods[0].items?.length === 1
  ) {
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

async function saveLocation() {
  try {
    await apiPost("/admin/locations", {
      map_id: mapId.value,
      row: sel.value.row,
      col: sel.value.col,
      name: locForm.name,
      description: descToPayload(locForm.description),
    });
    await loadDetail();
    select({
      row: sel.value.row,
      col: sel.value.col,
      loc: locations.value.find(
        (l) => l.row === sel.value.row && l.col === sel.value.col
      ),
      entities: [],
    });
  } catch (e) {
    error.value = e.message;
  }
}

async function removeLocation(cell) {
  if (!confirm(`删除地块 (${cell.row}, ${cell.col})「${cell.loc.name}」？其上实体一并删除。`))
    return;
  try {
    await apiDelete("/admin/locations", {
      map_id: mapId.value,
      row: cell.row,
      col: cell.col,
    });
    await loadDetail();
  } catch (e) {
    error.value = e.message;
  }
}

async function saveConnections() {
  try {
    for (const d of DIR_KEYS) {
      const slot = connForm[d];
      await apiPost("/admin/connections", {
        map_id: mapId.value,
        row: sel.value.row,
        col: sel.value.col,
        direction: d,
        enabled: slot.enabled,
        paths: slot.paths
          .filter((p) => p.targetsText.trim())
          .map((p) => ({
            label: p.label || null,
            reveal_target: p.reveal_target,
            targets: p.targetsText
              .split(/[;,，]/)
              .map((s) => s.trim())
              .filter(Boolean)
              .map((s) => {
                const [r, c] = s.split(",").map((v) => parseInt(v, 10));
                return { row: r, col: c };
              })
              .filter((t) => Number.isInteger(t.row) && Number.isInteger(t.col)),
          })),
      });
    }
    await loadDetail();
    select({
      row: sel.value.row,
      col: sel.value.col,
      loc: locations.value.find(
        (l) => l.row === sel.value.row && l.col === sel.value.col
      ),
      entities: [],
    });
  } catch (e) {
    error.value = e.message;
  }
}

async function saveMeta() {
  try {
    await apiPatch(`/admin/maps/${mapId.value}`, {
      name: meta.name,
      visible: meta.visible,
      spawn_row: meta.spawn_row,
      spawn_col: meta.spawn_col,
      timezone: meta.timezone || null,
    });
    await loadMaps();
  } catch (e) {
    error.value = e.message;
  }
}

async function removeMap() {
  if (!confirm(`删除地图「${meta.name}」？地块/实体/归属将级联删除，不可恢复。`)) return;
  try {
    await apiDelete(`/admin/maps/${mapId.value}`);
    goBack();
  } catch (e) {
    error.value = e.message;
  }
}

async function createMap() {
  try {
    await apiPost("/admin/maps", { id: nm.id, name: nm.name });
    await loadMaps();
    openMap(nm.id);
  } catch (e) {
    error.value = e.message;
  }
}

async function createEntity() {
  try {
    await apiPost("/admin/entities", {
      kind: nf.kind,
      map_id: mapId.value,
      row: nf.row,
      col: nf.col,
      name: nf.name,
      desc: nf.desc,
    });
    nf.kind = "";
    nf.name = "";
    nf.desc = "";
    await loadDetail();
  } catch (e) {
    error.value = e.message;
  }
}

async function saveEntityName(e) {
  try {
    await apiPatch(`/admin/entities/${e.id}`, { name: e.name });
  } catch (err) {
    error.value = err.message;
  }
}

async function removeEntity(e) {
  if (!confirm(`删除实体「${e.name}」（${e.kind}）？`)) return;
  try {
    await apiDelete(`/admin/entities/${e.id}`);
    await loadDetail();
  } catch (err) {
    error.value = err.message;
  }
}

function locate(e) {
  // 定位实体所在格
  const target = e;
  const found = gridCells.value.find(
    (c) => c.row === target.row && c.col === target.col
  );
  if (found) select(found);
}

async function createTemplate() {
  let data = {};
  try {
    data = nt.data.trim() ? JSON.parse(nt.data) : {};
  } catch {
    error.value = "模板 data 不是合法 JSON";
    return;
  }
  try {
    await apiPost("/admin/templates", { id: nt.id, name: nt.name, data });
    nt.id = "";
    nt.name = "";
    nt.data = "";
    templates.value = (await apiGet("/admin/templates")).templates || [];
  } catch (e) {
    error.value = e.message;
  }
}

async function removeTemplate(t) {
  if (!confirm(`删除模板「${t.name}」？`)) return;
  try {
    await apiDelete(`/admin/templates/${t.id}`);
    templates.value = (await apiGet("/admin/templates")).templates || [];
  } catch (e) {
    error.value = e.message;
  }
}

function openMap(id) {
  location.hash = `#/admin/maps/${id}`;
}

function goBack() {
  location.hash = "#/admin/worlds";
}

onMounted(async () => {
  syncFromHash();
  await loadMaps();
  window.addEventListener("hashchange", async () => {
    const prev = mapId.value;
    syncFromHash();
    if (mapId.value !== prev) {
      if (mapId.value) await loadDetail();
    }
  });
  if (mapId.value) await loadDetail();
});
</script>

<style scoped>
.head {
  display: flex;
  align-items: center;
  gap: 10px;
}
.picker {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.page-entry {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 10px;
  padding: 12px 14px;
  border: 1px solid var(--bg-3);
  border-radius: var(--radius);
  background: var(--bg-2);
  color: var(--text);
  cursor: pointer;
  font-size: 14px;
}
.map-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: flex-end;
  margin-bottom: 12px;
}
.editor {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}
.grid-wrap {
  flex: 1;
  min-width: 0;
  overflow: auto;
}
.grid {
  display: grid;
  gap: 3px;
  width: max-content;
}
.cell {
  width: 64px;
  height: 64px;
  border: 1px solid var(--bg-3);
  border-radius: 8px;
  background: var(--bg-2);
  color: var(--text);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 2px;
  padding: 2px;
  font-size: 15px;
  position: relative;
}
.cell.empty {
  background: transparent;
  border-style: dashed;
  color: var(--text-dim);
}
.cell.on {
  border-color: var(--accent);
}
.cell-name {
  font-size: 10px;
  line-height: 1.1;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.cell-dirs {
  font-size: 9px;
  color: var(--text-dim);
  letter-spacing: 1px;
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
.side {
  width: 300px;
  flex-shrink: 0;
  border-left: 1px solid var(--bg-3);
  padding-left: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.side h3,
.side h4 {
  margin: 4px 0;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.conn-card {
  border: 1px solid var(--bg-3);
  border-radius: 8px;
  padding: 6px 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.conn-head {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
}
.conn-path {
  display: flex;
  flex-direction: column;
  gap: 3px;
  border-left: 2px solid var(--bg-3);
  padding-left: 6px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
  color: var(--text-dim);
}
.field input,
.field textarea,
.field select,
.inline-form input {
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid var(--bg-3);
  background: var(--bg);
  color: var(--text);
  font-size: 13px;
}
.pos-inputs {
  display: flex;
  gap: 6px;
  align-items: center;
}
.pos-inputs input {
  width: 70px;
}
.inline-form {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
  margin-bottom: 8px;
}
.block {
  margin-top: 14px;
  border-top: 1px solid var(--bg-3);
  padding-top: 8px;
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
  padding: 0 4px;
}
.mini-btn.danger {
  color: var(--danger);
}
.mini-label {
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--text-dim);
}
.dim {
  color: var(--text-dim);
  font-size: 13px;
}
</style>
