<template>
  <div class="admin-shell">
    <!-- PC 优先：左侧固定导航；窄屏降级为顶部横向导航 -->
    <aside class="side">
      <div class="side-brand">
        <span class="nav-icon">🛠</span>
        <span>worlditor 管理台</span>
      </div>
      <nav class="nav">
        <!-- ① 通用管理（与世界无关） -->
        <div class="nav-section">通用管理</div>
        <button
          v-for="item in GLOBAL_NAV"
          :key="item.key"
          class="nav-item"
          :class="{ on: navOn(item) }"
          @click="goto(item.key)"
        >
          <span class="nav-icon">{{ item.icon }}</span>
          <span>{{ item.title }}</span>
        </button>

        <!-- ② 世界选择：选中后下面都是"这个世界的" -->
        <div class="nav-section">
          世界
          <span class="section-ops">
            <button class="mini-btn" title="新建世界" @click="creating = true">＋</button>
            <button
              v-if="currentWorld"
              class="mini-btn"
              title="世界设置"
              @click="editing = currentWorld"
            >
              ⚙
            </button>
          </span>
        </div>
        <select
          v-if="worlds.length"
          class="world-select"
          :value="worldId"
          @change="pickWorld($event.target.value)"
        >
          <option v-for="w in worlds" :key="w.id" :value="w.id">
            {{ w.name }}（{{ w.id }}）
          </option>
        </select>
        <button v-else class="nav-item" @click="creating = true">
          <span class="nav-icon">＋</span>
          <span>创建第一个世界</span>
        </button>

        <!-- ③ 该世界的玩法包与地图 -->
        <template v-if="worldId">
          <button
            class="nav-item sub"
            :class="{ on: route === 'plays' }"
            @click="goto('plays')"
          >
            <span class="nav-icon">🧩</span>
            <span class="sub-title">玩法包</span>
            <span class="sub-note">{{ activationNote }}</span>
          </button>
          <button
            class="nav-item sub"
            :class="{ on: route === 'maps' || route === 'map' }"
            @click="goto('maps')"
          >
            <span class="nav-icon">🗺</span>
            <span class="sub-title">地图</span>
            <span class="sub-note">{{ mapCount }}</span>
          </button>
        </template>

        <!-- ④ 玩法包注册的管理页（按当前世界的激活集合过滤；可收起） -->
        <template v-if="visiblePages.length">
          <div class="nav-section">
            玩法包管理页
            <span class="section-ops">
              <button
                class="mini-btn"
                :title="pagesOpen ? '收起' : '展开'"
                @click="togglePages"
              >
                {{ pagesOpen ? "▾" : "▸" }}
              </button>
            </span>
          </div>
          <template v-if="pagesOpen">
            <button
              v-for="pg in visiblePages"
              :key="pg.play_id + '/' + pg.key"
              class="nav-item sub"
              :class="{ on: pageOn(pg) }"
              :title="pg.title + '（' + playLabel(pg.play_id) + '）'"
              @click="gotoPage(pg)"
            >
              <span class="nav-icon">{{ pg.icon || "⚙️" }}</span>
              <span class="sub-title">{{ pg.title }}</span>
            </button>
          </template>
        </template>
      </nav>
      <button class="side-logout" title="退出登录" @click="doLogout">⎋ 退出登录</button>
    </aside>

    <main class="content">
      <component
        :is="current.comp"
        :key="current.key"
        v-bind="current.props"
        @world-changed="refreshMeta"
      />
    </main>

    <WorldEditModal
      v-if="creating || editing"
      :world="editing"
      @close="creating = false; editing = null"
      @saved="onWorldSaved"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { apiGet, setToken } from "../api";
import { store } from "../store";
import AccountsPage from "../pages/admin/AccountsPage.vue";
import InvitesPage from "../pages/admin/InvitesPage.vue";
import WorldPlaysPage from "../pages/admin/WorldPlaysPage.vue";
import WorldMapsPage from "../pages/admin/WorldMapsPage.vue";
import MapEditorPage from "../pages/admin/MapEditorPage.vue";
import PlayPageHost from "../pages/admin/PlayPageHost.vue";
import WorldEditModal from "./WorldEditModal.vue";

const GLOBAL_NAV = [
  { key: "accounts", title: "账户管理", icon: "👤" },
  { key: "invites", title: "邀请码", icon: "🎫" },
];

const PAGES = {
  accounts: AccountsPage,
  invites: InvitesPage,
  plays: WorldPlaysPage, // 世界上下文：该世界的玩法包
  maps: WorldMapsPage, // 世界上下文：该世界的地图
  map: MapEditorPage, // 地图编辑器（从地图页进入）
  pages: PlayPageHost, // 玩法包管理页（#/admin/pages/{play_id}/{key}）
};

const WORLD_KEY = "worlditor_admin_world";
const PAGES_OPEN_KEY = "worlditor_admin_pages_open";

const route = ref("");
const routeInfo = ref({ playId: "", pageKey: "", mapId: "" });
const worlds = ref([]);
const worldId = ref(localStorage.getItem(WORLD_KEY) || "");
const playPages = ref([]); // {play_id,key,title,icon,...}（全部注册项）
const playNames = ref({}); // play_id -> 显示名
const loadedCount = ref(0); // 全局已加载的玩法包数（侧栏提示用）
const pagesOpen = ref(localStorage.getItem(PAGES_OPEN_KEY) !== "0");
const creating = ref(false);
const editing = ref(null);

const currentWorld = computed(
  () => worlds.value.find((w) => w.id === worldId.value) || null
);

const current = computed(() => {
  const key = route.value;
  return {
    key,
    comp: PAGES[key] || PAGES.accounts,
    // 只有世界上下文的页面收 worldId（其余页面不吃这个 prop）
    props: key === "plays" || key === "maps" ? { worldId: worldId.value } : {},
  };
});

// 当前世界的激活集合：空 = 全部启用（D15）
function activeInWorld(playId) {
  const w = currentWorld.value;
  if (!w || !w.play_ids || !w.play_ids.length) return true;
  return w.play_ids.includes(playId);
}

const visiblePages = computed(() =>
  playPages.value.filter((p) => activeInWorld(p.play_id))
);

const activationNote = computed(() => {
  const w = currentWorld.value;
  if (!w) return "";
  if (!w.play_ids || !w.play_ids.length) return "全部";
  return `${w.play_ids.length}/${loadedCount.value}`;
});

const mapCount = computed(() => (currentWorld.value?.maps || []).length);

function togglePages() {
  pagesOpen.value = !pagesOpen.value;
  localStorage.setItem(PAGES_OPEN_KEY, pagesOpen.value ? "1" : "0");
}

function playLabel(playId) {
  return playNames.value[playId] || playId;
}

function navOn(item) {
  return route.value === item.key;
}

function pageOn(pg) {
  return (
    route.value === "pages" &&
    routeInfo.value.playId === pg.play_id &&
    routeInfo.value.pageKey === pg.key
  );
}

function parseRoute(hash) {
  // "#/admin/accounts" | "#/admin/world/{id}/plays" | "#/admin/world/{id}/maps"
  // | "#/admin/maps/{map_id}" | "#/admin/pages/{play_id}/{key}"
  const parts = hash.replace(/^#/, "").split("/").filter(Boolean);
  const key = parts[1] || "";
  if (key === "world") {
    return {
      key: parts[3] || "plays",
      worldId: decodeURIComponent(parts[2] || ""),
      playId: "",
      pageKey: "",
      mapId: "",
    };
  }
  if (key === "maps") {
    return {
      key: parts[2] ? "map" : "maps",
      worldId: "",
      playId: "",
      pageKey: "",
      mapId: decodeURIComponent(parts[2] || ""),
    };
  }
  return {
    key,
    worldId: "",
    playId: decodeURIComponent(parts[2] || ""),
    pageKey: decodeURIComponent(parts[3] || ""),
    mapId: "",
  };
}

function syncRoute() {
  const raw = parseRoute(location.hash);
  // 旧链接（v0.2.x：#/admin/plays、#/admin/worlds）→ 收敛到当前世界的页面
  const legacy = { plays: "plays", worlds: "maps" };
  const info = legacy[raw.key] ? { ...raw, key: legacy[raw.key] } : raw;
  route.value = info.key && PAGES[info.key] ? info.key : (worldId.value ? "plays" : "accounts");
  routeInfo.value = {
    playId: info.playId,
    pageKey: info.pageKey,
    mapId: info.mapId,
  };
  if (route.value === "pages") pagesOpen.value = true; // 当前就在管理页里 → 展开，别把自己藏起来
  if (info.worldId && info.worldId !== worldId.value && worlds.value.some((w) => w.id === info.worldId)) {
    setWorld(info.worldId);
  }
  // 规范化 URL：世界上下文的页面一律写成 #/admin/world/{id}/{page}
  // （replaceState 不触发 hashchange，避免二次解析）
  if (
    worldId.value &&
    (route.value === "plays" || route.value === "maps") &&
    raw.worldId !== worldId.value
  ) {
    history.replaceState(
      null,
      "",
      `#/admin/world/${encodeURIComponent(worldId.value)}/${route.value}`
    );
  }
}

function setWorld(id) {
  worldId.value = id;
  localStorage.setItem(WORLD_KEY, id);
}

function pickWorld(id) {
  setWorld(id);
  goto(route.value === "maps" || route.value === "map" ? "maps" : "plays");
}

function goto(key) {
  if ((key === "plays" || key === "maps") && worldId.value) {
    location.hash = `#/admin/world/${encodeURIComponent(worldId.value)}/${key}`;
    route.value = key;
  } else {
    location.hash = `#/admin/${key}`;
    route.value = key;
  }
  routeInfo.value = { playId: "", pageKey: "", mapId: "" };
}

function gotoPage(pg) {
  location.hash = `#/admin/pages/${encodeURIComponent(pg.play_id)}/${encodeURIComponent(pg.key)}`;
  route.value = "pages";
  routeInfo.value = { playId: pg.play_id, pageKey: pg.key, mapId: "" };
}

async function loadWorlds() {
  try {
    const data = await apiGet("/admin/worlds");
    worlds.value = data.worlds || [];
    if (!worlds.value.some((w) => w.id === worldId.value)) {
      setWorld(worlds.value[0]?.id || "");
    }
  } catch (e) {
    console.warn("世界列表加载失败：", e.message);
  }
}

async function loadPlayPages() {
  try {
    const [pages, plays] = await Promise.all([
      apiGet("/admin/play-pages"),
      apiGet("/admin/plays"),
    ]);
    playPages.value = pages.pages || [];
    playNames.value = Object.fromEntries(
      (plays.plays || []).map((p) => [p.play_id, p.name || p.play_id])
    );
    loadedCount.value = (plays.plays || []).filter(
      (p) => p.status === "loaded"
    ).length;
  } catch (e) {
    console.warn("管理页清单加载失败：", e.message);
  }
}

async function refreshMeta() {
  await Promise.all([loadWorlds(), loadPlayPages()]);
}

async function onWorldSaved(id) {
  creating.value = false;
  editing.value = null;
  await refreshMeta();
  if (id) {
    setWorld(id);
    goto("plays");
  } else if (!worlds.value.some((w) => w.id === worldId.value)) {
    setWorld(worlds.value[0]?.id || "");
    syncRoute();
  }
}

function doLogout() {
  setToken("");
  store.token = "";
  store.error = "";
  location.hash = "#/auth";
}

onMounted(async () => {
  await refreshMeta();
  syncRoute();
  window.addEventListener("hashchange", syncRoute);
  window.addEventListener("worlditor:plays-changed", loadPlayPages);
  window.addEventListener("worlditor:worlds-changed", loadWorlds);
  window.addEventListener("worlditor:select-world", (e) => {
    const id = e.detail?.world_id;
    if (id && worlds.value.some((w) => w.id === id)) setWorld(id);
  });
  // 登录后 hash 可能残留 #/world / #/auth——规范化到当前世界的玩法包页
  if (!parseRoute(location.hash).key) {
    goto(worldId.value ? "plays" : "accounts");
  }
});
</script>

<style scoped>
.admin-shell {
  display: flex;
  min-height: 100vh;
  gap: 20px;
  padding: 20px;
  align-items: stretch;
}
.side {
  width: 250px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  position: sticky;
  top: 20px;
  align-self: flex-start;
  height: calc(100vh - 40px);
  background: var(--bg-2);
  border: 1px solid var(--bg-3);
  border-radius: 12px;
  padding: 14px 10px;
}
.side-brand {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 700;
  font-size: 15px;
  padding: 4px 10px 14px;
  border-bottom: 1px solid var(--bg-3);
  margin-bottom: 8px;
}
.nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
.nav-section {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
  margin: 10px 0 2px;
  padding: 0 10px;
  font-size: 11px;
  letter-spacing: 0.6px;
  color: var(--text-dim);
  text-transform: uppercase;
}
.section-ops {
  display: flex;
  gap: 2px;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border: none;
  border-radius: 8px;
  background: transparent;
  color: var(--text-dim);
  font-size: 14px;
  cursor: pointer;
  text-align: left;
}
.nav-item:hover {
  color: var(--text);
}
.nav-item.on {
  background: var(--bg-3);
  color: var(--text);
  font-weight: 600;
}
.nav-icon {
  font-size: 17px;
  width: 22px;
  text-align: center;
}
.nav-item.sub {
  font-size: 13px;
  padding: 8px 10px 8px 12px;
  gap: 8px;
  margin-left: 8px;
}
.nav-item.sub .nav-icon {
  font-size: 15px;
  width: 18px;
}
.sub-title {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sub-note {
  font-size: 11px;
  color: var(--text-dim);
  flex-shrink: 0;
}
.world-select {
  margin: 0 10px 4px;
  padding: 8px 10px;
  border-radius: 8px;
  border: 1px solid var(--bg-3);
  background: var(--bg);
  color: var(--text);
  font-size: 13px;
}
.mini-btn {
  border: none;
  background: transparent;
  color: var(--text-dim);
  font-size: 13px;
  cursor: pointer;
  padding: 0 3px;
}
.mini-btn:hover {
  color: var(--accent);
}
.side-logout {
  border: none;
  border-radius: 8px;
  padding: 10px 12px;
  background: transparent;
  color: var(--text-dim);
  cursor: pointer;
  font-size: 13px;
  text-align: left;
}
.side-logout:hover {
  color: var(--danger);
}
.content {
  flex: 1;
  min-width: 0;
  max-width: 1200px;
}

/* 窄屏（移动端浏览管理台）：降级为顶部横向导航 */
@media (max-width: 900px) {
  .admin-shell {
    flex-direction: column;
    padding: 10px;
    gap: 10px;
  }
  .side {
    position: static;
    width: 100%;
    height: auto;
    flex-direction: row;
    align-items: center;
    padding: 8px;
    gap: 0;
    flex-wrap: wrap;
  }
  .side-brand {
    border: none;
    padding: 0 8px 0 4px;
    margin: 0;
    font-size: 14px;
  }
  .nav {
    flex-direction: row;
    overflow-x: auto;
    overflow-y: hidden;
    gap: 2px;
    flex: 1;
    align-items: center;
  }
  .nav-section {
    margin: 0;
    padding: 0 4px;
    white-space: nowrap;
  }
  .nav-item {
    flex-direction: column;
    gap: 2px;
    padding: 6px 10px;
    font-size: 11px;
    white-space: nowrap;
  }
  .nav-item .nav-icon {
    font-size: 16px;
  }
  .nav-item.sub {
    margin-left: 0;
    flex-direction: column;
  }
  .sub-note {
    display: none;
  }
  .world-select {
    margin: 0 4px;
    max-width: 160px;
  }
  .side-logout {
    padding: 8px;
    font-size: 12px;
  }
}
</style>
