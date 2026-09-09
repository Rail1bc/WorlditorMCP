<template>
  <section class="card">
    <h2>世界与地图</h2>
    <p class="dim">
      世界 = 玩法包激活集合 + 数据边界；组织树为纯管理维度。地图编辑入口在地图卡片上。
    </p>
    <div class="ops-row">
      <button class="btn" @click="openCreate">＋ 新建世界</button>
      <button class="btn btn-ghost" @click="load">↻</button>
    </div>
    <p v-if="error" class="error-text">{{ error }}</p>

    <div v-for="w in worlds" :key="w.id" class="world-card">
      <header class="world-head">
        <div>
          <strong>{{ w.name }}</strong>
          <code class="dim">{{ w.id }}</code>
        </div>
        <div class="ops">
          <button class="btn btn-ghost" @click="openEdit(w)">编辑</button>
          <button class="btn btn-danger" @click="removeWorld(w)">删除</button>
        </div>
      </header>
      <p v-if="w.desc" class="dim">{{ w.desc }}</p>
      <p class="dim">
        激活玩法包：
        <code v-for="p in w.play_ids" :key="p" class="chip">{{ p }}</code>
        <span v-if="!w.play_ids.length">全部</span>
      </p>

      <!-- 组织树 -->
      <div class="folders">
        <div class="folder-root">
          <div class="folder-title">根目录（{{ mapsOf(w, null).length }} 张地图）</div>
          <div class="folder-body">
            <div v-for="m in mapsOf(w, null)" :key="m.id" class="map-row">
              <button class="link" @click="openMap(m.id)">🗺 {{ m.id }}</button>
              <span class="dim">{{ m.location_count }} 地块 · {{ m.entity_count }} 实体</span>
              <select
                class="mini"
                :value="'root'"
                @change="moveMap(w, m, $event.target.value)"
              >
                <option value="root">根目录</option>
                <option v-for="f in childFolders(w)" :key="f.id" :value="f.id">
                  📁 {{ f.name }}
                </option>
              </select>
            </div>
            <p v-if="!mapsOf(w, null).length" class="dim">
              尚无地图——先在管理端创建，或经玩法包 API 生成
            </p>
          </div>
        </div>

        <div v-for="f in childFolders(w)" :key="f.id" class="folder">
          <details open>
            <summary>
              📁 {{ f.name }}
              <button class="mini-btn" @click.prevent="renameFolder(f)">重命名</button>
              <button class="mini-btn danger" @click.prevent="removeFolder(f)">删除</button>
              <button class="mini-btn" @click.prevent="newFolder(w, f.id)">子文件夹</button>
            </summary>
            <div class="folder-body">
              <div v-for="m in mapsOf(w, f.id)" :key="m.id" class="map-row">
                <button class="link" @click="openMap(m.id)">🗺 {{ m.id }}</button>
                <span class="dim">{{ m.location_count }} 地块 · {{ m.entity_count }} 实体</span>
                <select class="mini" :value="f.id" @change="moveMap(w, m, $event.target.value)">
                  <option value="root">根目录</option>
                  <option v-for="ff in childFolders(w)" :key="ff.id" :value="ff.id">
                    📁 {{ ff.name }}
                  </option>
                </select>
              </div>
              <button v-if="!mapsOf(w, f.id).length" class="btn btn-ghost" @click="newFolder(w, f.id)">
                子文件夹
              </button>
            </div>
          </details>
          <!-- 递归子文件夹（一层展示即可；更深层以树形缩进递归） -->
          <div v-for="sub in childFolders(w, f.id)" :key="sub.id" class="folder sub">
            <details open>
              <summary>
                📁 {{ sub.name }}
                <button class="mini-btn" @click.prevent="renameFolder(sub)">重命名</button>
                <button class="mini-btn danger" @click.prevent="removeFolder(sub)">删除</button>
              </summary>
              <div class="folder-body">
                <div v-for="m in mapsOf(w, sub.id)" :key="m.id" class="map-row">
                  <button class="link" @click="openMap(m.id)">🗺 {{ m.id }}</button>
                  <span class="dim">{{ m.location_count }} 地块 · {{ m.entity_count }} 实体</span>
                </div>
              </div>
            </details>
          </div>
        </div>

        <button v-if="!worlds.length" class="btn btn-ghost" @click="openCreate">创建第一个世界</button>
      </div>
    </div>
  </section>

  <!-- 新建/编辑世界弹层 -->
  <div v-if="editing" class="modal-mask" @click.self="editing = null">
    <div class="modal">
      <h3>{{ editing.id ? "编辑世界" : "新建世界" }}</h3>
      <label class="field">
        世界 id（创建后不可改）
        <input v-model="editing.id" :disabled="!!editing.name0" placeholder="如 pvp" />
      </label>
      <label class="field">
        名称
        <input v-model="editing.name" placeholder="如 竞技场" />
      </label>
      <label class="field">
        描述
        <textarea v-model="editing.desc" rows="2"></textarea>
      </label>
      <label class="field">
        激活玩法包（逗号分隔；空 = 全部激活）
        <input v-model="editing.playIdsText" placeholder="worlditor_play_items, worlditor_play_social" />
      </label>
      <div class="ops">
        <button class="btn" @click="saveWorld">保存</button>
        <button class="btn btn-ghost" @click="editing = null">取消</button>
      </div>
      <p v-if="formError" class="error-text">{{ formError }}</p>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { apiGet, apiPost, apiPatch, apiDelete } from "../../api";

const worlds = ref([]);
const error = ref("");
const editing = ref(null);
const formError = ref("");

async function load() {
  error.value = "";
  try {
    const data = await apiGet("/admin/worlds");
    worlds.value = data.worlds || [];
  } catch (e) {
    error.value = e.message;
  }
}

function childFolders(w, parentId = null) {
  return (w.folders || [])
    .filter((f) => f.parent_id === parentId)
    .sort((a, b) => a.sort - b.sort || a.name.localeCompare(b.name));
}

function mapsOf(w, folderId) {
  // worlds 端点已带归属（{id, folder_id}）；统计从 /admin/maps 合并
  return (w.maps || [])
    .filter((m) => m.folder_id === folderId)
    .map((m) => mapInfo(w, m.id));
}

function mapInfo(w, id) {
  // worlds 端点只返回 map id 列表，无统计——此处借用 /admin/maps 的数据
  return globalMaps.value.find((m) => m.id === id) || { id };
}

const globalMaps = ref([]);

async function loadMaps() {
  try {
    const data = await apiGet("/admin/maps");
    globalMaps.value = data.maps || [];
  } catch (e) {
    /* 地图统计不可用时降级为 id 展示 */
  }
}

function openCreate() {
  editing.value = { id: "", name: "", desc: "", playIdsText: "" };
}

function openEdit(w) {
  editing.value = {
    id: w.id,
    name: w.name,
    desc: w.desc || "",
    playIdsText: (w.play_ids || []).join(", "),
    name0: w.name,
  };
}

async function saveWorld() {
  formError.value = "";
  const playIds = editing.value.playIdsText
    .split(/[,，\s]+/)
    .map((s) => s.trim())
    .filter(Boolean);
  try {
    const body = {
      name: editing.value.name,
      desc: editing.value.desc,
      play_ids: playIds,
    };
    if (editing.value.name0) {
      await apiPatch(`/admin/worlds/${editing.value.id}`, body);
    } else {
      await apiPost("/admin/worlds", { ...body, id: editing.value.id });
    }
    editing.value = null;
    await load();
  } catch (e) {
    formError.value = e.message;
  }
}

async function removeWorld(w) {
  if (!confirm(`删除世界「${w.name}」？其组织树与地图归属将一并删除（地图本身保留）。`))
    return;
  try {
    await apiDelete(`/admin/worlds/${w.id}`);
    await load();
  } catch (e) {
    error.value = e.message;
  }
}

async function newFolder(w, parentId) {
  const name = prompt("文件夹名称：");
  if (!name) return;
  try {
    await apiPost(`/admin/worlds/${w.id}/folders`, { name, parent_id: parentId });
    await load();
  } catch (e) {
    error.value = e.message;
  }
}

async function renameFolder(f) {
  const name = prompt("新名称：", f.name);
  if (!name) return;
  try {
    await apiPatch(`/admin/folders/${f.id}`, { name });
    await load();
  } catch (e) {
    error.value = e.message;
  }
}

async function removeFolder(f) {
  if (!confirm(`删除文件夹「${f.name}」？其子文件夹与地图将回到世界根。`)) return;
  try {
    await apiDelete(`/admin/folders/${f.id}`);
    await load();
  } catch (e) {
    error.value = e.message;
  }
}

async function moveMap(w, m, folderId) {
  try {
    await apiPost(`/admin/worlds/${w.id}/assign-map`, {
      map_id: m.id,
      folder_id: folderId === "root" ? null : folderId,
    });
    await load();
  } catch (e) {
    error.value = e.message;
  }
}

function openMap(id) {
  location.hash = `#/admin/maps/${id}`;
}

onMounted(async () => {
  await loadMaps();
  await load();
});
</script>

<style scoped>
.ops-row {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
}
.world-card {
  border: 1px solid var(--bg-3);
  border-radius: var(--radius);
  padding: 12px 14px;
  margin-bottom: 12px;
  background: var(--bg-2);
}
.world-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}
.folders {
  margin-top: 8px;
  font-size: 14px;
}
.folder-root {
  margin-bottom: 6px;
}
.folder-title {
  color: var(--text-dim);
  font-size: 13px;
  padding: 4px 0;
}
.folder {
  margin-left: 10px;
  border-left: 2px solid var(--bg-3);
  padding-left: 10px;
}
.folder.sub {
  margin-top: 4px;
}
.folder-body {
  padding: 4px 0 6px;
}
.map-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 0;
}
.mini {
  padding: 3px 6px;
  border-radius: 8px;
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
.link {
  border: none;
  background: transparent;
  color: var(--accent);
  cursor: pointer;
  padding: 0;
}
summary {
  cursor: pointer;
  padding: 4px 0;
}
.chip {
  border: 1px solid var(--bg-3);
  border-radius: 20px;
  padding: 1px 8px;
  font-size: 12px;
}
.modal-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  padding: 16px;
}
.modal {
  width: 100%;
  max-width: 460px;
  background: var(--bg-2);
  border-radius: 14px;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
  color: var(--text-dim);
}
.field input,
.field textarea {
  padding: 9px 10px;
  border-radius: 8px;
  border: 1px solid var(--bg-3);
  background: var(--bg);
  color: var(--text);
  font-size: 14px;
}
.dim {
  color: var(--text-dim);
  font-size: 13px;
}
</style>
