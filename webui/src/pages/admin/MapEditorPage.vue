<template>
  <section class="card editor-shell">
    <div class="head">
      <h2>
        地图
        <code class="dim">{{ mapId || "未选择" }}</code>
        <code v-if="worldId" class="dim">· {{ worldId }}</code>
        <span class="dim">{{ meta.name }}</span>
      </h2>
      <button class="btn btn-ghost" @click="goBack">← 地图列表</button>
    </div>

    <p v-if="error" class="error-text">{{ error }}</p>

    <div v-if="!mapId" class="picker">
      <p class="dim">没有指定地图——正在跳转到「全部地图」…</p>
    </div>

    <template v-else>
      <!-- 三个视图：一次只专注一件事 -->
      <nav class="tabs">
        <button
          v-for="t in TABS"
          :key="t.key"
          class="tab"
          :class="{ on: tab === t.key }"
          @click="gotoTab(t.key)"
        >
          <span class="icon">{{ t.icon }}</span>{{ t.title }}
          <span v-if="t.key === 'entities'" class="count">{{ entities.length }}</span>
          <span v-else-if="t.key === 'templates'" class="count">{{ templates.length }}</span>
        </button>
        <span class="grow" />
        <code class="dim">{{ locationCount }} 地块</code>
      </nav>

      <!-- ① 地图编辑：可视化面板占主区，不纵向滚动 -->
      <div v-if="tab === 'map'" class="view map-view">
        <MapGrid
          ref="grid"
          :locations="locations"
          :entities="entities"
          :selection="selection"
          :primary="primary"
          @pick="onPick"
          @rect="onRectSelect"
        />
        <aside class="side">
          <TilePanel
            :tile="primaryTile"
            :pos="primary || { row: 0, col: 0 }"
            :templates="locationTemplates"
            @save-meta="saveTileMeta"
            @move="moveTile"
            @remove="removeTile"
            @save-template="saveTemplate"
            @apply-template="applyTemplateAt"
            @pick-pos="onPickPos"
          />
          <TileEntities
            :entities="primaryEntities"
            @open="openInEntityView"
            @remove="removeEntity"
            @manage="manageTileEntities"
          />
          <ConnectionPanel
            v-if="primaryTile"
            :tile="primaryTile"
            :map-id="mapId"
            :maps="maps"
            :location-keys="locationKeys"
            @save="saveConnection"
            @invalid="error = $event"
          />
        </aside>
      </div>

      <!-- ② 实体：列表 + 详情（按上千实体设计） -->
      <div v-else-if="tab === 'entities'" class="view">
        <EntityManager
          ref="entityManager"
          :entities="entities"
          :kinds="kinds"
          :entity-templates="entityTemplates"
          :tile-filter="entityTileFilter"
          @create="createEntity"
          @update="updateEntity"
          @remove="removeEntity"
          @save-template="saveEntityTemplate"
          @locate="locateEntity"
        />
      </div>

      <!-- ③ 模板 -->
      <div v-else class="view">
        <TemplateManager
          :templates="templates"
          :primary="primary"
          @remove="removeTemplate"
          @apply="applyTemplateFrom"
        />
      </div>

      <!-- 剪贴板 / 多选（只在地图视图出现） -->
      <div v-if="tab === 'map' && selection.length" class="clip">
        <span>已选 {{ selection.length }} 格（{{ selectedWithTile }} 格有地块）</span>
        <button class="btn" :disabled="!selectedWithTile" @click="copySelection">复制</button>
        <button class="btn" :disabled="!clipboard" title="粘贴到当前主选格（已存在的格子跳过）" @click="pasteClipboard">
          粘贴
        </button>
        <span v-if="clipboard" class="dim">剪贴板：{{ clipboard.tiles.length }} 个地块</span>
        <button class="btn btn-ghost" @click="selection = []">取消选择</button>
      </div>

      <!-- 地图信息（默认收起，给可视化面板让位） -->
      <details class="map-meta">
        <summary>地图信息与危险操作</summary>
        <div class="meta-row">
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
      </details>
    </template>
  </section>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import { apiGet, apiPost, apiPatch, apiDelete } from "../../api";
import { askConfirm } from "../../confirm";
import { askDiff, diffFields } from "../../diff";
import MapGrid from "../../components/editor/MapGrid.vue";
import TilePanel from "../../components/editor/TilePanel.vue";
import TileEntities from "../../components/editor/TileEntities.vue";
import ConnectionPanel from "../../components/editor/ConnectionPanel.vue";
import EntityManager from "../../components/editor/EntityManager.vue";
import TemplateManager from "../../components/editor/TemplateManager.vue";

const DIR_KEYS = ["up", "right", "down", "left"];
const TABS = [
  { key: "map", title: "地图编辑", icon: "🗺" },
  { key: "entities", title: "实体", icon: "🧍" },
  { key: "templates", title: "模板", icon: "🧩" },
];

const mapId = ref("");
const tab = ref("map");
const worldId = ref("");
const meta = reactive({ name: "", visible: "public", spawn_row: 0, spawn_col: 0, timezone: "" });
const locations = ref([]);
const entities = ref([]);
const templates = ref([]);
const kinds = ref([]);
const maps = ref([]);
const error = ref("");
const selection = ref([]);
const primary = ref(null);
const clipboard = ref(null);
const grid = ref(null);
const entityManager = ref(null);
// 从地图视图"管理本格实体"跳过来时带的过滤条件
const entityTileFilter = ref(null);

const locationCount = computed(() => locations.value.length);
const locationTemplates = computed(() => templates.value.filter((t) => t.scope === "location"));
const entityTemplates = computed(() => templates.value.filter((t) => t.scope === "entity"));
const primaryTile = computed(() => {
  if (!primary.value) return null;
  return locations.value.find((l) => l.row === primary.value.row && l.col === primary.value.col) || null;
});
const primaryEntities = computed(() => {
  if (!primary.value) return [];
  return entities.value.filter((e) => e.row === primary.value.row && e.col === primary.value.col);
});
const selectedWithTile = computed(
  () => selection.value.filter((key) => Boolean(tileAtKey(key))).length
);
const locationKeys = computed(() => locations.value.map((l) => `${mapId.value}:${l.row}:${l.col}`));

function tileAtKey(key) {
  const [row, col] = key.split(":").map(Number);
  return locations.value.find((l) => l.row === row && l.col === col) || null;
}

function syncFromHash() {
  const parts = location.hash.replace(/^#/, "").split("/").filter(Boolean);
  mapId.value = parts[2] || "";
  const next = parts[3] || "map";
  tab.value = TABS.some((t) => t.key === next) ? next : "map";
}

// ---------- 加载 ----------

async function loadDetail() {
  error.value = "";
  try {
    const [data, kindData, tmpl, mapList] = await Promise.all([
      apiGet(`/admin/maps/${mapId.value}`),
      apiGet("/admin/kinds"),
      apiGet("/admin/templates"),
      apiGet("/admin/maps"),
    ]);
    Object.assign(meta, {
      name: data.map.name,
      visible: data.map.visible,
      spawn_row: data.map.spawn_row,
      spawn_col: data.map.spawn_col,
      timezone: data.map.timezone || "",
    });
    worldId.value = data.map.world_id || "";
    if (worldId.value) {
      window.dispatchEvent(
        new CustomEvent("worlditor:select-world", { detail: { world_id: worldId.value } })
      );
    }
    locations.value = data.locations || [];
    entities.value = data.entities || [];
    kinds.value = kindData.kinds || [];
    templates.value = tmpl.templates || [];
    maps.value = mapList.maps || [];
    if (primary.value) {
      primary.value = locations.value.some(
        (l) => l.row === primary.value.row && l.col === primary.value.col
      )
        ? { ...primary.value }
        : null;
    }
  } catch (e) {
    error.value = e.message;
  }
}

// ---------- 视图切换 ----------

function gotoTab(key) {
  tab.value = key;
  const suffix = key === "map" ? "" : `/${key}`;
  history.replaceState(null, "", `#/admin/maps/${encodeURIComponent(mapId.value)}${suffix}`);
}

function openInEntityView(entity) {
  gotoTab("entities");
  entityManager.value?.focus(entity.id);
}

function manageTileEntities() {
  if (!primary.value) return;
  entityTileFilter.value = { ...primary.value };
  gotoTab("entities");
}

function locateEntity(entity) {
  primary.value = { row: entity.row, col: entity.col };
  selection.value = [`${entity.row}:${entity.col}`];
  entityTileFilter.value = { row: entity.row, col: entity.col };
  gotoTab("map");
}

// ---------- 网格选择 ----------

function onPick(cell, mods) {
  primary.value = { row: cell.row, col: cell.col };
  if (mods.ctrl) {
    const set = new Set(selection.value);
    if (set.has(cell.key)) set.delete(cell.key);
    else set.add(cell.key);
    selection.value = [...set];
  } else if (mods.shift && selection.value.length) {
    const set = new Set(selection.value);
    set.add(cell.key);
    selection.value = [...set];
  } else {
    selection.value = [cell.key];
  }
}

function onRectSelect(keys) {
  selection.value = keys;
  if (keys.length) {
    const [row, col] = keys[0].split(":").map(Number);
    primary.value = { row, col };
  }
}

function onPickPos({ row, col }) {
  if (!Number.isInteger(row) || !Number.isInteger(col)) return;
  primary.value = { row, col };
  selection.value = [`${row}:${col}`];
}

// ---------- 地块 ----------

function descToText(desc) {
  if (!desc) return "";
  if (typeof desc === "string") return desc;
  const periods = desc.periods || [];
  if (periods.length === 1 && periods[0].items?.length === 1) {
    return periods[0].items[0].text || "";
  }
  return JSON.stringify(desc, null, 2);
}

async function saveTileMeta(payload) {
  const before = primaryTile.value
    ? { name: primaryTile.value.name, description: descToText(primaryTile.value.description) }
    : { name: "", description: "" };
  const after = { name: payload.name, description: descToText(payload.description) };
  const ok = await askDiff({
    title: primaryTile.value ? "保存地块" : "新建地块",
    detail: `坐标 (${primary.value.row}, ${primary.value.col})`,
    changes: primaryTile.value
      ? diffFields(before, after, { name: "名称", description: "描述" })
      : [
          { label: "名称", before: "（无地块）", after: after.name },
          { label: "描述", before: "", after: after.description },
        ],
  });
  if (!ok) return;
  try {
    await apiPost("/admin/locations", {
      map_id: mapId.value,
      row: primary.value.row,
      col: primary.value.col,
      name: payload.name,
      description: payload.description,
    });
    await loadDetail();
  } catch (e) {
    error.value = e.message;
  }
}

async function moveTile({ row, col }) {
  const from = primary.value;
  const ok = await askConfirm({
    title: "移动地块",
    text: `把 (${from.row}, ${from.col}) 移到 (${row}, ${col})？`,
    detail: "全图指向它的连接目标与它上面的实体一起搬；目标格已有地块时会被拒绝。",
  });
  if (!ok) return;
  try {
    await apiPost("/admin/locations/move", {
      map_id: mapId.value,
      row: from.row,
      col: from.col,
      to_row: row,
      to_col: col,
    });
    primary.value = { row, col };
    selection.value = [`${row}:${col}`];
    await loadDetail();
  } catch (e) {
    error.value = e.message;
  }
}

async function removeTile() {
  const tile = primaryTile.value;
  const ok = await askConfirm({
    title: "删除地块",
    danger: true,
    text: `删除地块 (${tile.row}, ${tile.col})「${tile.name}」？`,
    detail: "其上实体一并删除，指向它的连接目标会被清理。有玩家在场时会被拒绝。",
  });
  if (!ok) return;
  try {
    await apiDelete("/admin/locations", {
      map_id: mapId.value,
      row: tile.row,
      col: tile.col,
    });
    selection.value = [];
    primary.value = null;
    await loadDetail();
  } catch (e) {
    error.value = e.message;
  }
}

// ---------- 出口（结构化，D23；diff 挡住 G24 那种静默损坏） ----------

function labelText(label) {
  if (!label) return "";
  if (typeof label === "string") return label;
  const periods = label.periods || [];
  if (periods.length === 1 && periods[0].items?.length === 1) return periods[0].items[0].text || "";
  return `（分时段 ${periods.length} 段）`;
}

function slotText(slot) {
  if (!slot) return "（无）";
  const paths = slot.paths || [];
  if (!slot.enabled) return `未启用（已配置 ${paths.length} 条路径）`;
  if (!paths.length) return "已启用但没有路径";
  return paths
    .map((p, i) => {
      const targets = (p.targets || [])
        .map((t) => `${t.map_id || "本图"}(${t.row},${t.col})×${t.weight ?? 1}`)
        .join(" ");
      const label = labelText(p.label);
      return `#${i + 1} ${targets}${label ? ` 「${label}」` : ""}`;
    })
    .join(" ｜ ");
}

async function saveConnection(dir, payload) {
  const before = primaryTile.value?.connections?.[dir] || null;
  const ok = await askDiff({
    title: `保存出口：${dir}`,
    detail: `地块 (${primary.value.row}, ${primary.value.col}) —— 只覆盖这一个方向，其余方向不动`,
    changes: [{ label: dir, before: slotText(before), after: slotText(payload) }],
  });
  if (!ok) return;
  try {
    await apiPost("/admin/connections", {
      map_id: mapId.value,
      row: primary.value.row,
      col: primary.value.col,
      direction: dir,
      enabled: payload.enabled,
      paths: payload.paths,
    });
    await loadDetail();
  } catch (e) {
    error.value = e.message;
  }
}

// ---------- 复制 / 粘贴（E1） ----------

function copySelection() {
  const rows = selection.value.map((k) => Number(k.split(":")[0]));
  const cols = selection.value.map((k) => Number(k.split(":")[1]));
  const anchor = { row: Math.min(...rows), col: Math.min(...cols) };
  const tiles = selection.value
    .map((key) => tileAtKey(key))
    .filter(Boolean)
    .map((l) => ({ dr: l.row - anchor.row, dc: l.col - anchor.col, loc: l }));
  if (!tiles.length) {
    error.value = "选中的格子里没有地块";
    return;
  }
  clipboard.value = { anchor, tiles };
  error.value = "";
}

async function pasteClipboard() {
  const clip = clipboard.value;
  if (!clip || !primary.value) return;
  const anchor = primary.value;
  const plan = [];
  const skipped = [];
  for (const item of clip.tiles) {
    const row = anchor.row + item.dr;
    const col = anchor.col + item.dc;
    if (tileAtKey(`${row}:${col}`)) {
      skipped.push(`(${row}, ${col})`);
      continue;
    }
    plan.push({ row, col, loc: item.loc, dr: row - item.loc.row, dc: col - item.loc.col });
  }
  const ok = await askConfirm({
    title: "粘贴地块",
    text: `将在 (${anchor.row}, ${anchor.col}) 粘贴 ${plan.length} 个地块？`,
    detail: skipped.length
      ? `已存在的 ${skipped.length} 格会跳过：${skipped.join("、")}。同图出口按位移一起搬，跨图出口原样保留。`
      : "同图出口按位移一起搬，跨图出口原样保留。",
    confirmText: "粘贴",
  });
  if (!ok || !plan.length) return;
  try {
    for (const p of plan) {
      await apiPost("/admin/locations", {
        map_id: mapId.value,
        row: p.row,
        col: p.col,
        name: p.loc.name,
        description: p.loc.description,
      });
      for (const dir of DIR_KEYS) {
        const slot = p.loc.connections?.[dir];
        if (!slot || !slot.enabled) continue;
        const paths = (slot.paths || []).map((path) => ({
          label: path.label || null,
          reveal_target: path.reveal_target,
          targets: (path.targets || []).map((t) =>
            t.map_id
              ? { map_id: t.map_id, row: t.row, col: t.col, weight: t.weight }
              : { row: t.row + p.dr, col: t.col + p.dc, weight: t.weight }
          ),
        }));
        await apiPost("/admin/connections", {
          map_id: mapId.value,
          row: p.row,
          col: p.col,
          direction: dir,
          enabled: true,
          paths,
        });
      }
    }
    selection.value = plan.map((p) => `${p.row}:${p.col}`);
    primary.value = { row: plan[0].row, col: plan[0].col };
    await loadDetail();
  } catch (e) {
    error.value = e.message;
    await loadDetail();
  }
}

// ---------- 实体 ----------

async function createEntity(payload) {
  try {
    await apiPost("/admin/entities", { map_id: mapId.value, ...payload });
    await loadDetail();
  } catch (e) {
    error.value = e.message;
    entityManager.value?.setError(e.message);
  }
}

async function updateEntity(entity, patch) {
  const before = {
    name: entity.name,
    desc: entity.desc,
    tags: (entity.tags || []).join("、"),
    attrs: entity.attrs,
    state: entity.state,
  };
  const after = { ...before, ...patch, tags: (patch.tags || []).join("、") };
  if (!("kind" in patch) || patch.kind === entity.kind) delete after.kind;
  const ok = await askDiff({
    title: `保存实体「${entity.name}」`,
    detail: "attrs/state/tags 是整体替换（旧值→新值如下）",
    changes: diffFields(before, after, {
      name: "名称",
      desc: "描述",
      tags: "标签",
      attrs: "attrs（玩法数据）",
      state: "state（动态状态）",
      kind: "类型",
    }),
  });
  if (!ok) return;
  try {
    await apiPatch(`/admin/entities/${entity.id}`, patch);
    await loadDetail();
  } catch (e) {
    error.value = e.message;
  }
}

async function removeEntity(entity) {
  const ok = await askConfirm({
    title: "删除实体",
    danger: true,
    text: `删除实体「${entity.name}」（${entity.kind}）？`,
    detail: (entity.tags || []).length ? `标签：${entity.tags.join("、")}` : "",
  });
  if (!ok) return;
  try {
    await apiDelete(`/admin/entities/${entity.id}`);
    await loadDetail();
  } catch (e) {
    error.value = e.message;
  }
}

// ---------- 模板 ----------

async function saveTemplate(payload) {
  try {
    await apiPost("/admin/templates", {
      id: payload.id,
      name: payload.name,
      scope: payload.scope || (payload.data?.kind ? "entity" : "location"),
      data: payload.data,
    });
    await loadDetail();
  } catch (e) {
    error.value = e.message;
  }
}

function saveEntityTemplate(entity) {
  return saveTemplate({
    id: `entity_${entity.kind}_${Date.now().toString(36)}`,
    name: `${entity.name}（模板）`,
    data: {
      kind: entity.kind,
      tags: [...(entity.tags || [])],
      name: entity.name,
      desc: entity.desc || "",
      attrs: { ...(entity.attrs || {}) },
      state: { ...(entity.state || {}) },
    },
  });
}

async function removeTemplate(t) {
  const ok = await askConfirm({
    title: "删除模板",
    danger: true,
    text: `删除模板「${t.name}」？`,
    detail: "模板是全局的（不跟地图），删除后其他地方也不再能用它。",
  });
  if (!ok) return;
  try {
    await apiDelete(`/admin/templates/${t.id}`);
    await loadDetail();
  } catch (e) {
    error.value = e.message;
  }
}

async function applyTemplateAt(templateId, row, col) {
  const pos = row !== undefined && col !== undefined ? { row, col } : primary.value || { row: 0, col: 0 };
  const ok = await askConfirm({
    title: "套用地块模板",
    text: `把模板套用到 (${pos.row}, ${pos.col})？`,
    detail: "同图出口按放置位置平移，跨图出口原样复制；目标格已有地块时会被拒绝。",
  });
  if (!ok) return;
  try {
    await apiPost("/admin/templates/apply", {
      template_id: templateId,
      map_id: mapId.value,
      row: pos.row,
      col: pos.col,
    });
    await loadDetail();
    if (tab.value !== "map") gotoTab("map");
  } catch (e) {
    error.value = e.message;
  }
}

function applyTemplateFrom({ templateId, row, col }) {
  return applyTemplateAt(templateId, row, col);
}

// ---------- 地图本身 ----------

async function saveMeta() {
  try {
    await apiPatch(`/admin/maps/${mapId.value}`, {
      name: meta.name,
      visible: meta.visible,
      spawn_row: meta.spawn_row,
      spawn_col: meta.spawn_col,
      timezone: meta.timezone || null,
    });
    await loadDetail();
  } catch (e) {
    error.value = e.message;
  }
}

async function removeMap() {
  const ok = await askConfirm({
    title: "删除地图",
    danger: true,
    text: `删除地图「${meta.name}」？`,
    detail: "地块 / 实体 / 世界归属将级联删除，不可恢复。图上有玩家实体时会被拒绝。",
  });
  if (!ok) return;
  try {
    await apiDelete(`/admin/maps/${mapId.value}`);
    goBack();
  } catch (e) {
    error.value = e.message;
  }
}

function goBack() {
  location.hash = worldId.value
    ? `#/admin/world/${encodeURIComponent(worldId.value)}/maps`
    : "#/admin/maps";
}

onMounted(async () => {
  syncFromHash();
  window.addEventListener("hashchange", async () => {
    const prev = mapId.value;
    syncFromHash();
    if (mapId.value !== prev) {
      primary.value = null;
      selection.value = [];
      entityTileFilter.value = null;
      if (mapId.value) await loadDetail();
    }
  });
  if (mapId.value) {
    await loadDetail();
    if (tab.value === "map") {
      // 首次进入把整图放进视野
      setTimeout(() => grid.value?.fit(), 120);
    }
  } else {
    location.hash = "#/admin/maps";
  }
});
</script>

<style scoped>
/* 编辑器壳：视口内布局，地图视图不纵向滚动 */
.editor-shell {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 60px);
  min-height: 520px;
  overflow: hidden;
}
.head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}
.head h2 {
  margin: 0;
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
}
.tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  margin: 8px 0;
  border-bottom: 1px solid var(--bg-3);
  padding-bottom: 4px;
  flex-shrink: 0;
}
.tab {
  display: flex;
  align-items: center;
  gap: 6px;
  border: none;
  background: transparent;
  color: var(--text-dim);
  cursor: pointer;
  font-size: 14px;
  padding: 7px 14px;
  border-radius: 8px 8px 0 0;
}
.tab:hover {
  color: var(--text);
}
.tab.on {
  color: var(--text);
  font-weight: 600;
  background: var(--bg-2);
  box-shadow: inset 0 -2px 0 var(--accent);
}
.tab .icon {
  font-size: 15px;
}
.tab .count {
  font-size: 11px;
  color: var(--text-dim);
  border: 1px solid var(--bg-3);
  border-radius: 999px;
  padding: 0 6px;
}
.grow {
  flex: 1;
}
.view {
  flex: 1;
  min-height: 0;
  display: flex;
}
.map-view {
  gap: 12px;
}
.side {
  width: 380px;
  flex-shrink: 0;
  overflow: auto;
  border-left: 1px solid var(--bg-3);
  padding-left: 12px;
}
.clip {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  margin-top: 8px;
  padding: 6px 10px;
  border: 1px solid var(--accent);
  border-radius: 8px;
  font-size: 13px;
  flex-shrink: 0;
}
.map-meta {
  flex-shrink: 0;
  margin-top: 8px;
  font-size: 13px;
  color: var(--text-dim);
}
.map-meta summary {
  cursor: pointer;
  padding: 4px 0;
}
.meta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: flex-end;
  padding: 8px 0;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
  color: var(--text-dim);
}
.field input,
.field select {
  padding: 6px 9px;
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
.dim {
  color: var(--text-dim);
  font-size: 13px;
}

@media (max-width: 1100px) {
  .editor-shell {
    height: auto;
    min-height: 0;
  }
  .map-view {
    flex-direction: column;
  }
  .side {
    width: 100%;
    border-left: none;
    padding-left: 0;
  }
}
</style>
