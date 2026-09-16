<template>
  <section class="card">
    <div class="page-head">
      <h2>
        地图
        <code class="dim">{{ worldId }}</code>
      </h2>
      <div class="ops">
        <input v-model="q" class="search" placeholder="搜索地图 / 文件夹…" />
        <button class="btn" @click="showCreate = !showCreate">＋ 新建地图</button>
        <button class="btn btn-ghost" title="刷新" @click="load">↻</button>
      </div>
    </div>
    <p class="dim">
      组织树是纯管理维度（不影响玩法）。拖到文件夹上 = 放进去；拖到行之间 = 同级排序；
      地图的地块/实体在编辑器里改。
    </p>

    <!-- 新建地图 -->
    <div v-if="showCreate" class="inline-form">
      <input v-model="nm.id" placeholder="地图 id（如 arena）" />
      <input v-model="nm.name" placeholder="名称" />
      <select v-model="nm.folder_id" class="mini">
        <option value="">世界根</option>
        <option v-for="f in flatFolders" :key="f.id" :value="f.id">{{ f.path }}</option>
      </select>
      <button class="btn" @click="createMap">创建</button>
    </div>

    <p v-if="error" class="error-text">{{ error }}</p>

    <!-- 面包屑（聚焦节点路径） -->
    <div class="crumbs">
      <button class="crumb" :class="{ on: !focusId }" @click="focusId = ''">
        🌍 {{ worldName }}
      </button>
      <template v-for="c in crumbs" :key="c.id">
        <span class="sep">›</span>
        <button class="crumb" :class="{ on: c.id === focusId }" @click="focusId = c.id">
          📁 {{ c.name }}
        </button>
      </template>
      <span v-if="q.trim()" class="dim">搜索「{{ q.trim() }}」</span>
      <span v-if="lintTotals.error || lintTotals.warn" class="lint-sum" :class="{ err: lintTotals.error }">
        ⚠ 体检：{{ lintTotals.error }} 错 · {{ lintTotals.warn }} 警
      </span>
      <button class="mini-btn new-folder" title="在聚焦节点下新建文件夹" @click="startFolderDraft(focusId || null)">
        ＋ 文件夹
      </button>
    </div>

    <!-- 世界根的新建文件夹（内联输入，替代原生 prompt） -->
    <div v-if="folderDraft && folderDraft.parent_id === null" class="panel draft root-draft">
      <input
        ref="draftInput"
        v-model="folderDraft.name"
        placeholder="新文件夹名称"
        @keydown.enter="commitFolderDraft"
        @keydown.esc="folderDraft = null"
      />
      <button class="btn" @click="commitFolderDraft">创建</button>
      <button class="btn btn-ghost" @click="folderDraft = null">取消</button>
    </div>

    <!-- 组织树（扁平化渲染：拖拽/排序都比嵌套 DOM 好做） -->
    <div class="tree" @dragover.prevent @drop="onDropRootArea">
      <div
        v-if="!rows.length && !q.trim()"
        class="dim empty"
      >
        （这个世界的组织树是空的——新建文件夹或地图）
      </div>
      <div v-else-if="!rows.length" class="dim empty">（没有匹配「{{ q.trim() }}」的地图或文件夹）</div>

      <template v-for="row in rows" :key="row.type + ':' + row.id">
        <div
          class="row"
          :class="[
            row.type,
            {
              on: focusId === row.id,
              dragging: dragId === row.id,
              'drop-before': dropAt(row) === 'before',
              'drop-after': dropAt(row) === 'after',
              'drop-into': dropAt(row) === 'into',
            },
          ]"
          :style="{ paddingLeft: 6 + row.depth * 18 + 'px' }"
          :data-row="row.type + ':' + row.id"
          :data-depth="row.depth"
          draggable="true"
          @dragstart="onDragStart($event, row)"
          @dragend="onDragEnd"
          @dragover="onDragOver($event, row)"
          @drop.stop="onDrop($event, row)"
          @click="focusId = row.id"
        >
          <!-- 文件夹 -->
          <template v-if="row.type === 'folder'">
            <button
              class="toggler"
              :title="collapsed.has(row.id) ? '展开' : '收起'"
              @click.stop="toggleCollapse(row.id)"
            >
              {{ collapsed.has(row.id) ? "▸" : "▾" }}
            </button>
            <span class="icon">📁</span>
            <InlineEdit :value="row.name" @save="renameFolder(row, $event)" />
            <span class="dim">{{ childrenOf(row.id).length }} 项</span>
            <span class="row-ops">
              <button class="mini-btn" @click.stop="startFolderDraft(row.id)">＋子文件夹</button>
              <button class="mini-btn danger" @click.stop="removeFolder(row)">删除</button>
            </span>
          </template>

          <!-- 地图 -->
          <template v-else>
            <span class="toggler ghost"></span>
            <span class="icon">🗺</span>
            <InlineEdit :value="row.name || row.id" @save="renameMap(row, $event)" />
            <code class="dim">{{ row.id }}</code>
            <span class="dim">{{ row.location_count }} 地块 · {{ row.entity_count }} 实体</span>
            <span v-if="row.visible === 'private'" class="pill">private</span>
            <button
              v-if="lintOf(row.id)"
              class="lint-badge"
              :class="{ err: lintOf(row.id).counts.error }"
              :title="'查看体检结果'"
              @click.stop="lintOpen = lintOpen === row.id ? '' : row.id"
            >
              ⚠ {{ lintOf(row.id).counts.error }} 错 / {{ lintOf(row.id).counts.warn }} 警
            </button>
            <span class="row-ops">
              <button class="mini-btn" @click.stop="openMap(row.id)">编辑</button>
              <button class="mini-btn" @click.stop="startMove(row)">移动</button>
              <button class="mini-btn" @click.stop="startCopy(row)">复制</button>
              <button class="mini-btn danger" @click.stop="removeMap(row)">删除</button>
            </span>
          </template>
        </div>

        <!-- 新建文件夹（内联输入，替代原生 prompt） -->
        <div
          v-if="folderDraft && draftHost(row)"
          class="panel draft"
          :data-panel="'draft:' + row.id"
          :style="{ marginLeft: 6 + (row.depth + 1) * 18 + 'px' }"
        >
          <input
            ref="draftInput"
            v-model="folderDraft.name"
            placeholder="新文件夹名称"
            @keydown.enter="commitFolderDraft"
            @keydown.esc="folderDraft = null"
          />
          <button class="btn" @click="commitFolderDraft">创建</button>
          <button class="btn btn-ghost" @click="folderDraft = null">取消</button>
        </div>

        <!-- 移动（含跨世界） -->
        <div
          v-if="movingId === row.id"
          class="panel"
          :data-panel="'move:' + row.id"
          :style="{ marginLeft: 6 + (row.depth + 1) * 18 + 'px' }"
        >
          <label class="mini-label">
            世界
            <select v-model="mv.world_id" class="mini" @change="mv.folder_id = ''">
              <option v-for="w in worlds" :key="w.id" :value="w.id">{{ w.name }}</option>
              <option value="">（不归属任何世界）</option>
            </select>
          </label>
          <label v-if="mv.world_id" class="mini-label">
            位置
            <select v-model="mv.folder_id" class="mini">
              <option value="">世界根</option>
              <option v-for="f in foldersOfWorld(mv.world_id)" :key="f.id" :value="f.id">
                {{ f.path }}
              </option>
            </select>
          </label>
          <button class="btn" @click="doMove(row)">移动</button>
          <button class="btn btn-ghost" @click="movingId = ''">取消</button>
        </div>

        <!-- 复制另存 -->
        <div
          v-if="copyingId === row.id"
          class="panel"
          :data-panel="'copy:' + row.id"
          :style="{ marginLeft: 6 + (row.depth + 1) * 18 + 'px' }"
        >
          <input v-model="cp.id" placeholder="新地图 id" />
          <input v-model="cp.name" placeholder="新名称（默认 原名（副本））" />
          <label class="mini-label">
            <input v-model="cp.with_entities" type="checkbox" /> 连实体一起复制
          </label>
          <button class="btn" @click="doCopy(row)">复制</button>
          <button class="btn btn-ghost" @click="copyingId = ''">取消</button>
        </div>

        <!-- 体检结果 -->
        <div
          v-if="lintOpen === row.id && lintOf(row.id)"
          class="panel lint"
          :data-panel="'lint:' + row.id"
          :style="{ marginLeft: 6 + (row.depth + 1) * 18 + 'px' }"
        >
          <p v-if="!lintOf(row.id).problems.length" class="dim">没有发现问题。</p>
          <div
            v-for="(p, i) in lintOf(row.id).problems"
            :key="i"
            class="problem"
            :class="p.level"
          >
            <span class="lvl">{{ p.level === "error" ? "错误" : "提示" }}</span>
            <span>{{ p.text }}</span>
          </div>
          <button class="btn btn-ghost" @click="lintOpen = ''">收起</button>
        </div>
      </template>

      <!-- 拖到空白处 = 移到世界根末尾 -->
      <div
        class="root-drop"
        :class="{ active: Boolean(dragId) }"
        @dragover.prevent
        @drop.stop="onDropRootArea"
      >
        {{ dragId ? "放到世界根末尾" : "" }}
      </div>
    </div>

    <!-- 未归属世界的地图：按默认世界的规则跑，容易踩坑 → 给一键归属 -->
    <div v-if="orphans.length" class="block">
      <h3>未归属世界的地图（{{ orphans.length }}）</h3>
      <p class="dim">
        这些地图不属于任何世界——运行时按<b>默认世界</b>的玩法包启停生效。
        归属到本世界后，才由本世界的开关决定。
      </p>
      <div v-for="m in orphans" :key="m.id" class="orphan-row">
        <span class="icon">🗺</span>
        <span>{{ m.name || m.id }}</span>
        <code class="dim">{{ m.id }}</code>
        <span class="dim">{{ m.location_count }} 地块 · {{ m.entity_count }} 实体</span>
        <button class="mini-btn" @click="adopt(m.id)">归属到本世界</button>
        <button class="mini-btn" @click="openMap(m.id)">编辑</button>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { apiGet, apiPost, apiPatch, apiDelete } from "../../api";
import { askConfirm } from "../../confirm";
import InlineEdit from "../../components/InlineEdit.vue";

const props = defineProps({
  worldId: { type: String, default: "" },
});
const emit = defineEmits(["world-changed"]);

const worlds = ref([]);
const globalMaps = ref([]);
const lintByMap = ref({});
const error = ref("");
const q = ref("");
const focusId = ref("");
const collapsed = ref(new Set());
const showCreate = ref(false);
const nm = ref({ id: "", name: "", folder_id: "" });
const movingId = ref("");
const mv = ref({ world_id: "", folder_id: "" });
const copyingId = ref("");
const cp = ref({ id: "", name: "", with_entities: false });
const lintOpen = ref("");
const folderDraft = ref(null);
const draftInput = ref(null);
const dragId = ref("");
const dragType = ref("");
const drop = ref(null);

const world = computed(() => worlds.value.find((w) => w.id === props.worldId) || null);
const worldName = computed(() => world.value?.name || props.worldId);
const folders = computed(() => world.value?.folders || []);
const worldMaps = computed(() => world.value?.maps || []);
const orphans = computed(() => globalMaps.value.filter((m) => !m.world_id));

function mapInfo(id) {
  return globalMaps.value.find((m) => m.id === id) || { id, name: id };
}

function lintOf(id) {
  return lintByMap.value[id] || null;
}

const lintTotals = computed(() => {
  let err = 0;
  let warn = 0;
  for (const m of worldMaps.value) {
    const r = lintByMap.value[m.id];
    if (r) {
      err += r.counts.error;
      warn += r.counts.warn;
    }
  }
  return { error: err, warn };
});

/** 某组织节点下的直接子项（文件夹与地图共用序号空间，序号相同按名称）。 */
function childrenOf(parentId) {
  const pid = parentId || null;
  const fs = folders.value
    .filter((f) => (f.parent_id || null) === pid)
    .map((f) => ({
      type: "folder",
      id: f.id,
      name: f.name,
      sort: f.sort,
      parent_id: pid,
    }));
  const ms = worldMaps.value
    .filter((m) => (m.folder_id || null) === pid)
    .map((m) => ({
      ...mapInfo(m.id),
      type: "map",
      id: m.id,
      sort: m.sort,
      parent_id: pid,
    }));
  return [...fs, ...ms].sort(
    (a, b) => a.sort - b.sort || a.name.localeCompare(b.name) || a.id.localeCompare(b.id)
  );
}

/** 扁平化组织树（带 depth）：渲染与拖拽都按一维列表处理。 */
const rows = computed(() => {
  const needle = q.value.trim().toLowerCase();
  const hit = (n) =>
    !needle ||
    (n.name || "").toLowerCase().includes(needle) ||
    (n.type === "map" && n.id.toLowerCase().includes(needle));
  const subtreeHit = (parentId) =>
    childrenOf(parentId).some((n) => hit(n) || (n.type === "folder" && subtreeHit(n.id)));
  const out = [];
  const walk = (parentId, depth) => {
    for (const node of childrenOf(parentId)) {
      if (needle && !hit(node) && !(node.type === "folder" && subtreeHit(node.id))) continue;
      out.push({ ...node, depth });
      if (node.type === "folder" && (needle || !collapsed.value.has(node.id))) {
        walk(node.id, depth + 1);
      }
    }
  };
  walk(null, 0);
  return out;
});

const flatFolders = computed(() => {
  const out = [];
  const walk = (parentId, prefix) => {
    for (const f of folders.value.filter((x) => (x.parent_id || null) === (parentId || null))) {
      const path = `${prefix}${f.name}`;
      out.push({ id: f.id, path });
      walk(f.id, `${path} / `);
    }
  };
  walk(null, "");
  return out;
});

function foldersOfWorld(worldId) {
  const w = worlds.value.find((x) => x.id === worldId);
  if (!w) return [];
  const list = w.folders || [];
  const out = [];
  const walk = (parentId, prefix) => {
    for (const f of list.filter((x) => (x.parent_id || null) === (parentId || null))) {
      const path = `${prefix}${f.name}`;
      out.push({ id: f.id, path });
      walk(f.id, `${path} / `);
    }
  };
  walk(null, "");
  return out;
}

/** 聚焦节点的祖先链（面包屑）。 */
const crumbs = computed(() => {
  const chain = [];
  let node = folders.value.find((f) => f.id === focusId.value);
  while (node) {
    chain.unshift({ id: node.id, name: node.name });
    node = node.parent_id ? folders.value.find((f) => f.id === node.parent_id) : null;
  }
  return chain;
});

function parentLabel(parentId) {
  if (!parentId) return "世界根";
  const f = folders.value.find((x) => x.id === parentId);
  return f ? `「${f.name}」` : "上级";
}

function toggleCollapse(id) {
  const next = new Set(collapsed.value);
  if (next.has(id)) next.delete(id);
  else next.add(id);
  collapsed.value = next;
}

function draftHost(row) {
  if (!folderDraft.value) return false;
  // 世界根草稿挂在首个根节点之前；其余挂在其父文件夹行之后
  if (folderDraft.value.parent_id === null) return false;
  return row.type === "folder" && row.id === folderDraft.value.parent_id;
}

function startFolderDraft(parentId) {
  folderDraft.value = { parent_id: parentId, name: "" };
  nextTick(() => {
    const el = Array.isArray(draftInput.value) ? draftInput.value[0] : draftInput.value;
    el?.focus();
  });
}

async function commitFolderDraft() {
  const draft = folderDraft.value;
  if (!draft || !draft.name.trim()) {
    folderDraft.value = null;
    return;
  }
  try {
    await apiPost(`/admin/worlds/${encodeURIComponent(props.worldId)}/folders`, {
      name: draft.name.trim(),
      parent_id: draft.parent_id,
    });
    folderDraft.value = null;
    await load();
  } catch (e) {
    error.value = e.message;
  }
}

// ---------- 加载 ----------

async function load() {
  error.value = "";
  try {
    const [w, m, l] = await Promise.all([
      apiGet("/admin/worlds"),
      apiGet("/admin/maps"),
      apiGet("/admin/lint").catch(() => ({ maps: [] })),
    ]);
    worlds.value = w.worlds || [];
    globalMaps.value = m.maps || [];
    lintByMap.value = Object.fromEntries((l.maps || []).map((r) => [r.map_id, r]));
  } catch (e) {
    error.value = e.message;
  }
}

// ---------- 行内操作 ----------

function openMap(id) {
  location.hash = `#/admin/maps/${encodeURIComponent(id)}`;
}

async function createMap() {
  if (!nm.value.id) {
    error.value = "请填写地图 id";
    return;
  }
  try {
    await apiPost("/admin/maps", { id: nm.value.id, name: nm.value.name || nm.value.id });
    // 建完即归属本世界（否则地图会"不属于任何世界"）
    await apiPost(`/admin/worlds/${encodeURIComponent(props.worldId)}/assign-map`, {
      map_id: nm.value.id,
      folder_id: nm.value.folder_id || null,
    });
    nm.value = { id: "", name: "", folder_id: "" };
    showCreate.value = false;
    await load();
    emit("world-changed");
  } catch (e) {
    error.value = e.message;
  }
}

async function adopt(mapId) {
  try {
    await apiPost(`/admin/worlds/${encodeURIComponent(props.worldId)}/assign-map`, {
      map_id: mapId,
      folder_id: null,
    });
    await load();
    emit("world-changed");
  } catch (e) {
    error.value = e.message;
  }
}

async function renameFolder(row, name) {
  try {
    await apiPatch(`/admin/folders/${row.id}`, { name });
    await load();
  } catch (e) {
    error.value = e.message;
  }
}

async function renameMap(row, name) {
  try {
    await apiPatch(`/admin/maps/${row.id}`, { name });
    await load();
  } catch (e) {
    error.value = e.message;
  }
}

async function removeFolder(row) {
  const kids = childrenOf(row.id);
  const ok = await askConfirm({
    title: "删除文件夹",
    danger: true,
    text: `删除文件夹「${row.name}」？`,
    detail: kids.length
      ? `里面有 ${kids.length} 项，会先移到${parentLabel(row.parent_id)}，再删除这个空文件夹。`
      : "这是个空文件夹，直接删除。",
  });
  if (!ok) return;
  try {
    for (const k of kids) {
      if (k.type === "folder") {
        await apiPost(`/admin/folders/${k.id}/move`, { parent_id: row.parent_id });
      } else {
        await apiPost(`/admin/maps/${k.id}/move`, {
          world_id: props.worldId,
          folder_id: row.parent_id,
        });
      }
    }
    await apiDelete(`/admin/folders/${row.id}`);
    await load();
  } catch (e) {
    error.value = e.message;
    await load();
  }
}

async function removeMap(row) {
  const info = mapInfo(row.id);
  const ok = await askConfirm({
    title: "删除地图",
    danger: true,
    text: `删除地图「${info.name || row.id}」？`,
    detail: `${info.location_count || 0} 个地块、${info.entity_count || 0} 个实体与归属关系会一并删除，不可恢复。图上若有玩家实体则会被拒绝。`,
  });
  if (!ok) return;
  try {
    await apiDelete(`/admin/maps/${row.id}`);
    await load();
    emit("world-changed");
  } catch (e) {
    error.value = e.message;
  }
}

function startMove(row) {
  movingId.value = row.id;
  mv.value = { world_id: props.worldId, folder_id: row.parent_id || "" };
}

async function doMove(row) {
  try {
    await apiPost(`/admin/maps/${row.id}/move`, {
      world_id: mv.value.world_id || null,
      folder_id: mv.value.world_id ? mv.value.folder_id || null : null,
    });
    movingId.value = "";
    await load();
    emit("world-changed");
  } catch (e) {
    error.value = e.message;
  }
}

function startCopy(row) {
  copyingId.value = row.id;
  cp.value = { id: suggestCopyId(row.id), name: "", with_entities: false };
}

function suggestCopyId(id) {
  let candidate = `${id}_copy`;
  let n = 2;
  while (globalMaps.value.some((m) => m.id === candidate)) {
    candidate = `${id}_copy${n}`;
    n += 1;
  }
  return candidate;
}

async function doCopy(row) {
  if (!cp.value.id.trim()) {
    error.value = "请填写新地图 id";
    return;
  }
  try {
    await apiPost(`/admin/maps/${row.id}/copy`, {
      new_id: cp.value.id.trim(),
      name: cp.value.name.trim() || null,
      with_entities: cp.value.with_entities,
      folder_id: row.parent_id,
    });
    copyingId.value = "";
    await load();
    emit("world-changed");
  } catch (e) {
    error.value = e.message;
  }
}

// ---------- 拖拽（移动 + 同级排序） ----------

function rowKey(row) {
  return `${row.type}:${row.id}`;
}

function dropAt(row) {
  return drop.value && drop.value.key === rowKey(row) ? drop.value.zone : "";
}

function onDragStart(e, row) {
  dragId.value = row.id;
  dragType.value = row.type;
  if (e.dataTransfer) {
    e.dataTransfer.effectAllowed = "move";
    try {
      e.dataTransfer.setData("text/plain", row.id);
    } catch {
      /* 某些浏览器限制自定义类型，忽略 */
    }
  }
}

function onDragEnd() {
  dragId.value = "";
  dragType.value = "";
  drop.value = null;
}

function onDragOver(e, row) {
  if (!dragId.value || dragId.value === row.id) return;
  e.preventDefault();
  if (e.dataTransfer) e.dataTransfer.dropEffect = "move";
  const rect = e.currentTarget.getBoundingClientRect();
  const y = e.clientY - rect.top;
  let zone = y < rect.height * 0.3 ? "before" : y > rect.height * 0.7 ? "after" : "into";
  if (zone === "into" && row.type !== "folder") {
    zone = y < rect.height / 2 ? "before" : "after";
  }
  drop.value = { key: rowKey(row), zone, row };
}

async function onDrop(e, row) {
  e.preventDefault();
  const zone = dropAt(row) || "before";
  drop.value = null;
  if (!dragId.value || dragId.value === row.id) return;
  if (zone === "into") {
    await placeDragged(row.id, childrenOf(row.id).length);
  } else {
    const siblings = childrenOf(row.parent_id);
    const index = siblings.findIndex((n) => n.id === row.id);
    await placeDragged(row.parent_id, zone === "after" ? index + 1 : index);
  }
}

async function onDropRootArea(e) {
  e.preventDefault();
  drop.value = null;
  if (!dragId.value) return;
  await placeDragged(null, childrenOf(null).length);
}

function isDescendant(candidateId, ancestorId) {
  let node = folders.value.find((f) => f.id === candidateId);
  while (node) {
    if (node.id === ancestorId) return true;
    node = node.parent_id ? folders.value.find((f) => f.id === node.parent_id) : null;
  }
  return false;
}

function nodeOf(type, id) {
  if (type === "folder") {
    const f = folders.value.find((x) => x.id === id);
    return f ? { type, id, parent_id: f.parent_id || null } : null;
  }
  const m = worldMaps.value.find((x) => x.id === id);
  return m ? { type, id, parent_id: m.folder_id || null } : null;
}

/** 把正在拖的条目放到 parentId 的第 index 位（跨容器先搬家，再统一重排序号）。 */
async function placeDragged(parentId, index) {
  const type = dragType.value;
  const id = dragId.value;
  const me = nodeOf(type, id);
  dragId.value = "";
  dragType.value = "";
  if (!me) return;
  if (type === "folder" && parentId && (parentId === id || isDescendant(parentId, id))) {
    error.value = "不能把文件夹放进它自己或它的子文件夹里";
    return;
  }
  const sameParent = me.parent_id === (parentId || null);
  const list = childrenOf(parentId).filter((n) => !(n.id === id && n.type === type));
  let at = index;
  if (sameParent) {
    const oldIndex = childrenOf(parentId).findIndex((n) => n.id === id);
    if (oldIndex >= 0 && oldIndex < index) at = index - 1;
  }
  at = Math.max(0, Math.min(at, list.length));
  list.splice(at, 0, { type, id });
  error.value = "";
  try {
    if (!sameParent) {
      if (type === "folder") {
        await apiPost(`/admin/folders/${id}/move`, { parent_id: parentId });
      } else {
        await apiPost(`/admin/maps/${id}/move`, {
          world_id: props.worldId,
          folder_id: parentId,
        });
      }
    }
    await apiPost(`/admin/worlds/${encodeURIComponent(props.worldId)}/reorder`, {
      parent_id: parentId,
      items: list.map((n) => ({ type: n.type, id: n.id })),
    });
  } catch (e) {
    error.value = e.message;
  }
  await load();
}

watch(
  () => props.worldId,
  () => {
    focusId.value = "";
    folderDraft.value = null;
    movingId.value = "";
    copyingId.value = "";
    load();
  }
);
onMounted(load);
</script>

<style scoped>
.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.page-head h2 {
  margin: 0;
}
.search {
  padding: 7px 10px;
  border-radius: 8px;
  border: 1px solid var(--bg-3);
  background: var(--bg);
  color: var(--text);
  font-size: 13px;
  min-width: 180px;
}
.crumbs {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
  margin: 10px 0 6px;
  font-size: 13px;
}
.crumb {
  border: none;
  background: transparent;
  color: var(--text-dim);
  cursor: pointer;
  padding: 2px 4px;
  border-radius: 6px;
  font-size: 13px;
}
.crumb:hover {
  color: var(--text);
}
.crumb.on {
  color: var(--text);
  font-weight: 600;
  background: var(--bg-3);
}
.sep {
  color: var(--text-dim);
}
.lint-sum {
  margin-left: auto;
  font-size: 12px;
  color: var(--text-dim);
  border: 1px solid var(--bg-3);
  border-radius: 999px;
  padding: 2px 10px;
}
.lint-sum.err {
  color: var(--danger);
  border-color: var(--danger);
}
.new-folder {
  margin-left: 6px;
}
.root-draft {
  margin: 2px 0 6px;
}
.tree {
  border: 1px solid var(--bg-3);
  border-radius: 10px;
  padding: 6px;
  min-height: 60px;
  font-size: 14px;
}
.empty {
  padding: 10px;
}
.row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 8px;
  border-top: 2px solid transparent;
  border-bottom: 2px solid transparent;
  cursor: default;
}
.row:hover {
  background: var(--bg-2);
}
.row.folder {
  cursor: pointer;
}
.row.on {
  background: var(--bg-3);
}
.row.dragging {
  opacity: 0.4;
}
.row.drop-before {
  border-top-color: var(--accent);
}
.row.drop-after {
  border-bottom-color: var(--accent);
}
.row.drop-into {
  outline: 2px dashed var(--accent);
  outline-offset: -2px;
}
.toggler {
  border: none;
  background: transparent;
  color: var(--text-dim);
  cursor: pointer;
  font-size: 11px;
  width: 14px;
  padding: 0;
}
.toggler.ghost {
  cursor: default;
}
.icon {
  font-size: 15px;
}
.pill {
  font-size: 11px;
  border: 1px solid var(--bg-3);
  border-radius: 999px;
  padding: 0 6px;
  color: var(--text-dim);
}
.lint-badge {
  border: 1px solid var(--bg-3);
  background: transparent;
  border-radius: 999px;
  font-size: 11px;
  padding: 1px 8px;
  color: var(--text-dim);
  cursor: pointer;
}
.lint-badge.err {
  color: var(--danger);
  border-color: var(--danger);
}
.row-ops {
  margin-left: auto;
  display: flex;
  gap: 2px;
  flex-shrink: 0;
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
.panel {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 6px 10px;
  margin: 2px 0 4px;
  border-left: 2px solid var(--bg-3);
  font-size: 13px;
}
.panel input,
.panel select {
  padding: 5px 8px;
  border-radius: 6px;
  border: 1px solid var(--bg-3);
  background: var(--bg);
  color: var(--text);
  font-size: 13px;
}
.panel.lint {
  flex-direction: column;
  align-items: stretch;
  gap: 4px;
}
.problem {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  font-size: 13px;
  line-height: 1.45;
}
.problem .lvl {
  flex-shrink: 0;
  font-size: 11px;
  border-radius: 4px;
  padding: 0 5px;
  border: 1px solid currentColor;
}
.problem.error {
  color: var(--danger);
}
.problem.warn {
  color: var(--text-dim);
}
.root-drop {
  min-height: 22px;
  border-radius: 8px;
  margin-top: 2px;
  font-size: 12px;
  color: var(--text-dim);
  display: flex;
  align-items: center;
  justify-content: center;
}
.root-drop.active {
  border: 1px dashed var(--accent);
  color: var(--accent);
}
.mini {
  padding: 3px 6px;
  border-radius: 8px;
  border: 1px solid var(--bg-3);
  background: var(--bg);
  color: var(--text);
  font-size: 12px;
}
.mini-label {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--text-dim);
}
.inline-form {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  align-items: center;
  margin: 8px 0;
}
.inline-form input {
  padding: 7px 10px;
  border-radius: 8px;
  border: 1px solid var(--bg-3);
  background: var(--bg);
  color: var(--text);
  font-size: 13px;
}
.block {
  margin-top: 16px;
  border-top: 1px solid var(--bg-3);
  padding-top: 10px;
}
.orphan-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 0;
  font-size: 14px;
}
.dim {
  color: var(--text-dim);
  font-size: 13px;
}

/* 窄屏：组织树横向可滚，行内操作换行 */
@media (max-width: 900px) {
  .page-head {
    flex-wrap: wrap;
  }
  .tree {
    overflow-x: auto;
  }
  .row {
    flex-wrap: wrap;
  }
  .row-ops {
    margin-left: 0;
  }
}
</style>
