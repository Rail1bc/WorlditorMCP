<template>
  <section class="card">
    <div class="page-head">
      <h2>全部地图 <code class="dim">跨世界</code></h2>
      <div class="ops">
        <input v-model="q" class="search" placeholder="搜索地图 id / 名称…" />
        <select v-model="worldFilter" class="mini">
          <option value="">全部世界</option>
          <option value="__orphan__">未归属世界</option>
          <option v-for="w in worlds" :key="w.id" :value="w.id">
            {{ w.name }}（{{ w.id }}）
          </option>
        </select>
        <button class="btn" @click="showCreate = !showCreate">＋ 新建地图</button>
        <button class="btn btn-ghost" title="刷新" @click="load">↻</button>
      </div>
    </div>
    <p class="dim">
      地图治理的总视图：归属、体检、批量搬家、建图。组织树（文件夹）在各自世界的「地图」页里编排。
    </p>
    <p v-if="error" class="error-text">{{ error }}</p>

    <!-- 新建地图（X2：跨世界视角下不必先切世界再建图） -->
    <div v-if="showCreate" class="inline-form">
      <input v-model="nm.id" placeholder="地图 id（如 arena）" />
      <input v-model="nm.name" placeholder="名称" />
      <label class="mini-label">
        归属
        <select v-model="nm.world_id" class="mini" @change="nm.folder_id = ''">
          <option value="">（不归属任何世界）</option>
          <option v-for="w in worlds" :key="w.id" :value="w.id">{{ w.name }}</option>
        </select>
      </label>
      <label v-if="nm.world_id" class="mini-label">
        位置
        <select v-model="nm.folder_id" class="mini">
          <option value="">世界根</option>
          <option v-for="f in foldersOfWorld(nm.world_id)" :key="f.id" :value="f.id">
            {{ f.path }}
          </option>
        </select>
      </label>
      <button class="btn" :disabled="busy" @click="createMap">创建</button>
    </div>

    <!-- 统计条 -->
    <div class="stats">
      <span>共 <b>{{ maps.length }}</b> 张地图</span>
      <span :class="{ bad: totals.error }">⚠ {{ totals.error }} 处错误</span>
      <span>· {{ totals.warn }} 处提示</span>
      <span v-if="orphanCount" class="bad">{{ orphanCount }} 张未归属世界</span>
    </div>

    <!-- 批量操作条 -->
    <div v-if="selected.length" class="batch">
      <span>已选 {{ selected.length }} 张</span>
      <label class="mini-label">
        归属到
        <select v-model="batch.world_id" class="mini" @change="batch.folder_id = ''">
          <option v-for="w in worlds" :key="w.id" :value="w.id">{{ w.name }}</option>
          <option value="__none__">（解除归属）</option>
        </select>
      </label>
      <label v-if="batch.world_id !== '__none__'" class="mini-label">
        位置
        <select v-model="batch.folder_id" class="mini">
          <option value="">世界根</option>
          <option v-for="f in foldersOfWorld(batch.world_id)" :key="f.id" :value="f.id">
            {{ f.path }}
          </option>
        </select>
      </label>
      <button class="btn" :disabled="busy" @click="applyBatch">应用</button>
      <span v-if="batchProgress" class="dim">{{ batchProgress }}</span>
      <button class="btn btn-ghost" @click="selected = []">取消选择</button>
    </div>
    <p v-if="batchResult" class="dim">{{ batchResult }}</p>

    <div class="table-wrap">
      <table class="table">
        <thead>
          <tr>
            <th class="pick">
              <input
                type="checkbox"
                :checked="allSelected"
                :indeterminate.prop="someSelected"
                @change="toggleAll($event.target.checked)"
              />
            </th>
            <th>地图</th>
            <th>世界 / 位置</th>
            <th>地块</th>
            <th>实体</th>
            <th>可见性</th>
            <th>体检</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="m in filtered" :key="m.id" :class="{ orphan: !m.world_id }">
            <td class="pick">
              <input type="checkbox" :value="m.id" v-model="selected" />
            </td>
            <td>
              <button class="link" @click="openMap(m.id)">{{ m.name || m.id }}</button>
              <div><code class="dim">{{ m.id }}</code></div>
            </td>
            <td>
              <template v-if="m.world_id">
                <span>{{ worldName(m.world_id) }}</span>
                <div class="dim">{{ folderPath(m.world_id, m.folder_id) }}</div>
              </template>
              <span v-else class="warn-text">未归属（按默认世界规则运行）</span>
            </td>
            <td>{{ m.location_count }}</td>
            <td>{{ m.entity_count }}</td>
            <td>
              <span class="pill" :class="{ priv: m.visible === 'private' }">
                {{ m.visible }}
              </span>
            </td>
            <td>
              <button
                v-if="lintOf(m.id)"
                class="lint-badge"
                :class="{ err: lintOf(m.id).counts.error, ok: !lintOf(m.id).counts.error && !lintOf(m.id).counts.warn }"
                @click="lintOpen = lintOpen === m.id ? '' : m.id"
              >
                <template v-if="lintOf(m.id).counts.error || lintOf(m.id).counts.warn">
                  ⚠ {{ lintOf(m.id).counts.error }} / {{ lintOf(m.id).counts.warn }}
                </template>
                <template v-else>✓ 正常</template>
              </button>
            </td>
            <td class="ops">
              <button class="mini-btn" @click="openMap(m.id)">编辑</button>
              <button class="mini-btn danger" @click="removeMap(m)">删除</button>
            </td>
          </tr>
          <tr v-if="!filtered.length">
            <td colspan="8" class="dim">没有匹配的地图。</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 体检明细 -->
    <div v-if="lintOpen && lintOf(lintOpen)" class="block">
      <h3>
        体检：{{ lintOf(lintOpen).name }}
        <button class="mini-btn" @click="lintOpen = ''">收起</button>
      </h3>
      <p v-if="!lintOf(lintOpen).problems.length" class="dim">没有发现问题。</p>
      <div v-for="(p, i) in lintOf(lintOpen).problems" :key="i" class="problem" :class="p.level">
        <span class="lvl">{{ p.level === "error" ? "错误" : "提示" }}</span>
        <span>{{ p.text }}</span>
        <button class="mini-btn" @click="openMap(lintOpen)">去编辑</button>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { apiGet, apiPost, apiDelete } from "../../api";
import { askConfirm } from "../../confirm";

const worlds = ref([]);
const maps = ref([]);
const lintByMap = ref({});
const error = ref("");
const q = ref("");
const worldFilter = ref("");
const selected = ref([]);
const batch = ref({ world_id: "", folder_id: "" });
const lintOpen = ref("");
const busy = ref(false);
const showCreate = ref(false);
const nm = ref({ id: "", name: "", world_id: "", folder_id: "" });
const batchProgress = ref("");
const batchResult = ref("");

const orphanCount = computed(() => maps.value.filter((m) => !m.world_id).length);

const totals = computed(() => {
  let err = 0;
  let warn = 0;
  for (const r of Object.values(lintByMap.value)) {
    err += r.counts.error;
    warn += r.counts.warn;
  }
  return { error: err, warn };
});

const filtered = computed(() => {
  const needle = q.value.trim().toLowerCase();
  return maps.value
    .filter((m) => {
      if (worldFilter.value === "__orphan__" && m.world_id) return false;
      if (worldFilter.value && worldFilter.value !== "__orphan__" && m.world_id !== worldFilter.value) {
        return false;
      }
      if (!needle) return true;
      return (
        m.id.toLowerCase().includes(needle) ||
        (m.name || "").toLowerCase().includes(needle)
      );
    })
    .sort(
      (a, b) =>
        (a.world_id || "").localeCompare(b.world_id || "") ||
        (a.folder_id || "").localeCompare(b.folder_id || "") ||
        (a.sort ?? 0) - (b.sort ?? 0) ||
        (a.name || a.id).localeCompare(b.name || b.id)
    );
});

const allSelected = computed(
  () => filtered.value.length > 0 && filtered.value.every((m) => selected.value.includes(m.id))
);
const someSelected = computed(
  () => !allSelected.value && filtered.value.some((m) => selected.value.includes(m.id))
);

function toggleAll(on) {
  selected.value = on ? filtered.value.map((m) => m.id) : [];
}

function lintOf(id) {
  return lintByMap.value[id] || null;
}

function worldName(id) {
  return worlds.value.find((w) => w.id === id)?.name || id;
}

function folderPath(worldId, folderId) {
  if (!folderId) return "世界根";
  const w = worlds.value.find((x) => x.id === worldId);
  if (!w) return "—";
  const list = w.folders || [];
  const parts = [];
  let node = list.find((f) => f.id === folderId);
  while (node) {
    parts.unshift(node.name);
    node = node.parent_id ? list.find((f) => f.id === node.parent_id) : null;
  }
  return parts.length ? `📁 ${parts.join(" / ")}` : "世界根";
}

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

async function load() {
  error.value = "";
  try {
    const [w, m, l] = await Promise.all([
      apiGet("/admin/worlds"),
      apiGet("/admin/maps"),
      apiGet("/admin/lint").catch(() => ({ maps: [] })),
    ]);
    worlds.value = w.worlds || [];
    maps.value = m.maps || [];
    lintByMap.value = Object.fromEntries((l.maps || []).map((r) => [r.map_id, r]));
    // 选中项可能已被删除
    selected.value = selected.value.filter((id) => maps.value.some((m2) => m2.id === id));
  } catch (e) {
    error.value = e.message;
  }
}

async function applyBatch() {
  if (!selected.value.length) return;
  const target = batch.value.world_id;
  if (!target) {
    error.value = "请先选择目标世界";
    return;
  }
  busy.value = true;
  error.value = "";
  batchResult.value = "";
  const ids = [...selected.value];
  const failed = [];
  let done = 0;
  // X1：逐张搬家要报进度——中途失败时前面的已经改完了，不能只弹第一条错误
  for (const id of ids) {
    batchProgress.value = `已完成 ${done}/${ids.length}…`;
    try {
      await apiPost(`/admin/maps/${encodeURIComponent(id)}/move`, {
        world_id: target === "__none__" ? null : target,
        folder_id: target === "__none__" ? null : batch.value.folder_id || null,
      });
      done += 1;
    } catch (e) {
      failed.push(`${id}（${e.message}）`);
    }
  }
  batchProgress.value = "";
  batchResult.value = failed.length
    ? `已移动 ${done}/${ids.length} 张；失败 ${failed.length} 张：${failed.join("；")}`
    : `已移动 ${done} 张地图`;
  selected.value = [];
  await load();
  window.dispatchEvent(new CustomEvent("worlditor:worlds-changed"));
  busy.value = false;
}

async function createMap() {
  if (!nm.value.id.trim()) {
    error.value = "请填写地图 id";
    return;
  }
  busy.value = true;
  error.value = "";
  try {
    await apiPost("/admin/maps", {
      id: nm.value.id.trim(),
      name: nm.value.name.trim() || nm.value.id.trim(),
    });
    await apiPost(`/admin/maps/${encodeURIComponent(nm.value.id.trim())}/move`, {
      world_id: nm.value.world_id || null,
      folder_id: nm.value.world_id ? nm.value.folder_id || null : null,
    });
    batchResult.value = `已创建地图 ${nm.value.id}`;
    nm.value = { id: "", name: "", world_id: nm.value.world_id, folder_id: "" };
    showCreate.value = false;
    await load();
    window.dispatchEvent(new CustomEvent("worlditor:worlds-changed"));
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}

async function removeMap(m) {
  const ok = await askConfirm({
    title: "删除地图",
    danger: true,
    text: `删除地图「${m.name || m.id}」？`,
    detail: `${m.location_count} 个地块、${m.entity_count} 个实体与归属关系会一并删除，不可恢复。图上若有玩家实体则会被拒绝。`,
  });
  if (!ok) return;
  try {
    await apiDelete(`/admin/maps/${encodeURIComponent(m.id)}`);
    await load();
    window.dispatchEvent(new CustomEvent("worlditor:worlds-changed"));
  } catch (e) {
    error.value = e.message;
  }
}

function openMap(id) {
  location.hash = `#/admin/maps/${encodeURIComponent(id)}`;
}

onMounted(load);
</script>

<style scoped>
.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
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
.stats {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  margin: 10px 0;
  font-size: 13px;
  color: var(--text-dim);
}
.stats .bad {
  color: var(--danger);
}
.batch {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
  padding: 8px 10px;
  margin-bottom: 8px;
  border: 1px solid var(--accent);
  border-radius: 8px;
  font-size: 13px;
}
.link {
  border: none;
  background: transparent;
  color: var(--accent);
  cursor: pointer;
  padding: 0;
  font-size: 14px;
  text-align: left;
}
tr.orphan td {
  background: rgba(255, 120, 120, 0.05);
}
.warn-text {
  color: var(--danger);
}
.pill {
  font-size: 11px;
  border: 1px solid var(--bg-3);
  border-radius: 999px;
  padding: 0 6px;
  color: var(--text-dim);
}
.pill.priv {
  color: var(--accent);
  border-color: var(--accent);
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
.lint-badge.ok {
  color: var(--text-dim);
  cursor: default;
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
.pick {
  width: 34px;
}
.block {
  margin-top: 16px;
  border-top: 1px solid var(--bg-3);
  padding-top: 10px;
}
.block h3 {
  display: flex;
  align-items: center;
  gap: 8px;
}
.problem {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  font-size: 13px;
  line-height: 1.45;
  padding: 3px 0;
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
.dim {
  color: var(--text-dim);
  font-size: 13px;
}
</style>
