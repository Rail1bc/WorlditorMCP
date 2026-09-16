<template>
  <section class="card">
    <div class="page-head">
      <h2>
        地图
        <code class="dim">{{ worldId }}</code>
      </h2>
      <div class="ops">
        <button class="btn" @click="showCreate = !showCreate">＋ 新建地图</button>
        <button class="btn btn-ghost" @click="load">↻</button>
      </div>
    </div>
    <p class="dim">
      组织树是纯管理维度（不影响玩法）；地图的地块/实体在地图编辑器里改。
    </p>

    <div v-if="showCreate" class="inline-form">
      <input v-model="nm.id" placeholder="地图 id（如 arena）" />
      <input v-model="nm.name" placeholder="名称" />
      <select v-model="nm.folder_id" class="mini">
        <option value="">根目录</option>
        <option v-for="f in allFolders" :key="f.id" :value="f.id">
          📁 {{ f.name }}
        </option>
      </select>
      <button class="btn" @click="createMap">创建</button>
    </div>
    <p v-if="error" class="error-text">{{ error }}</p>

    <!-- 组织树 -->
    <div class="folders">
      <div class="folder-root">
        <div class="folder-title">
          根目录（{{ mapsOf(null).length }} 张地图）
          <button class="mini-btn" @click="newFolder(null)">＋ 文件夹</button>
        </div>
        <div class="folder-body">
          <div v-for="m in mapsOf(null)" :key="m.id" class="map-row">
            <button class="link" @click="openMap(m.id)">🗺 {{ m.id }}</button>
            <span class="dim">
              {{ m.location_count }} 地块 · {{ m.entity_count }} 实体
            </span>
            <select
              class="mini"
              :value="'root'"
              @change="moveMap(m, $event.target.value)"
            >
              <option value="root">根目录</option>
              <option v-for="f in childFolders(null)" :key="f.id" :value="f.id">
                📁 {{ f.name }}
              </option>
            </select>
          </div>
          <p v-if="!mapsOf(null).length" class="dim">（根目录没有地图）</p>
        </div>
      </div>

      <div v-for="f in childFolders(null)" :key="f.id" class="folder">
        <details open>
          <summary>
            📁 {{ f.name }}
            <button class="mini-btn" @click.prevent="renameFolder(f)">重命名</button>
            <button class="mini-btn danger" @click.prevent="removeFolder(f)">
              删除
            </button>
            <button class="mini-btn" @click.prevent="newFolder(f.id)">子文件夹</button>
          </summary>
          <div class="folder-body">
            <div v-for="m in mapsOf(f.id)" :key="m.id" class="map-row">
              <button class="link" @click="openMap(m.id)">🗺 {{ m.id }}</button>
              <span class="dim">
                {{ m.location_count }} 地块 · {{ m.entity_count }} 实体
              </span>
              <select
                class="mini"
                :value="f.id"
                @change="moveMap(m, $event.target.value)"
              >
                <option value="root">根目录</option>
                <option v-for="ff in childFolders(null)" :key="ff.id" :value="ff.id">
                  📁 {{ ff.name }}
                </option>
              </select>
            </div>
            <p v-if="!mapsOf(f.id).length" class="dim">（空文件夹）</p>
          </div>
        </details>
        <div v-for="sub in childFolders(f.id)" :key="sub.id" class="folder sub">
          <details open>
            <summary>
              📁 {{ sub.name }}
              <button class="mini-btn" @click.prevent="renameFolder(sub)">
                重命名
              </button>
              <button class="mini-btn danger" @click.prevent="removeFolder(sub)">
                删除
              </button>
            </summary>
            <div class="folder-body">
              <div v-for="m in mapsOf(sub.id)" :key="m.id" class="map-row">
                <button class="link" @click="openMap(m.id)">🗺 {{ m.id }}</button>
                <span class="dim">
                  {{ m.location_count }} 地块 · {{ m.entity_count }} 实体
                </span>
              </div>
              <p v-if="!mapsOf(sub.id).length" class="dim">（空文件夹）</p>
            </div>
          </details>
        </div>
      </div>
    </div>

    <!-- 未归属世界的地图：按默认世界的规则跑，容易踩坑 → 给一键归属 -->
    <div v-if="orphans.length" class="block">
      <h3>未归属世界的地图（{{ orphans.length }}）</h3>
      <p class="dim">
        这些地图不属于任何世界——运行时按**默认世界**的玩法包启停生效。
        归属到本世界后，才由本世界的开关决定。
      </p>
      <div v-for="m in orphans" :key="m.id" class="map-row">
        <button class="link" @click="openMap(m.id)">🗺 {{ m.id }}</button>
        <span class="dim">
          {{ m.location_count }} 地块 · {{ m.entity_count }} 实体
        </span>
        <button class="mini-btn" @click="adopt(m.id)">归属到本世界</button>
        <button class="mini-btn" @click="openMap(m.id)">编辑</button>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { apiGet, apiPost, apiPatch, apiDelete } from "../../api";

const props = defineProps({
  worldId: { type: String, default: "" },
});
const emit = defineEmits(["world-changed"]);

const worlds = ref([]);
const globalMaps = ref([]);
const error = ref("");
const showCreate = ref(false);
const nm = ref({ id: "", name: "", folder_id: "" });

const world = computed(
  () => worlds.value.find((w) => w.id === props.worldId) || null
);
const allFolders = computed(() => world.value?.folders || []);
const orphans = computed(() =>
  globalMaps.value.filter((m) => !m.world_id) // 未归属任何世界
);

function childFolders(parentId = null) {
  return allFolders.value
    .filter((f) => f.parent_id === parentId)
    .sort((a, b) => a.sort - b.sort || a.name.localeCompare(b.name));
}

function mapsOf(folderId) {
  // worlds 端点带归属（{id, folder_id}）；统计从 /admin/maps 合并
  return (world.value?.maps || [])
    .filter((m) => m.folder_id === folderId)
    .map((m) => mapInfo(m.id));
}

function mapInfo(id) {
  return globalMaps.value.find((m) => m.id === id) || { id };
}

async function load() {
  error.value = "";
  try {
    const [w, m] = await Promise.all([apiGet("/admin/worlds"), apiGet("/admin/maps")]);
    worlds.value = w.worlds || [];
    globalMaps.value = m.maps || [];
  } catch (e) {
    error.value = e.message;
  }
}

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

async function moveMap(m, folderId) {
  try {
    await apiPost(`/admin/worlds/${encodeURIComponent(props.worldId)}/assign-map`, {
      map_id: m.id,
      folder_id: folderId === "root" ? null : folderId,
    });
    await load();
  } catch (e) {
    error.value = e.message;
  }
}

async function newFolder(parentId) {
  const name = prompt("文件夹名称：");
  if (!name) return;
  try {
    await apiPost(`/admin/worlds/${encodeURIComponent(props.worldId)}/folders`, {
      name,
      parent_id: parentId,
    });
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

watch(
  () => props.worldId,
  () => load()
);
onMounted(load);
</script>

<style scoped>
.page-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}
.page-head h2 {
  margin: 0;
}
.folders {
  margin-top: 10px;
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
.block {
  margin-top: 16px;
  border-top: 1px solid var(--bg-3);
  padding-top: 10px;
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
.dim {
  color: var(--text-dim);
  font-size: 13px;
}
</style>
