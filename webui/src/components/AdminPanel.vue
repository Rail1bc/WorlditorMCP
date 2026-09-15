<template>
  <div class="admin-shell">
    <!-- PC 优先：左侧固定导航；窄屏降级为顶部横向导航 -->
    <aside class="side">
      <div class="side-brand">
        <span class="nav-icon">🛠</span>
        <span>worlditor 管理台</span>
      </div>
      <nav class="nav">
        <button
          v-for="item in NAV"
          :key="item.key"
          class="nav-item"
          :class="{ on: navOn(item) }"
          @click="goto(item.key)"
        >
          <span class="nav-icon">{{ item.icon }}</span>
          <span>{{ item.title }}</span>
        </button>

        <!-- 玩法包管理页：独立层级（可收起展开；随管理页注册动态出现） -->
        <div v-if="playPages.length" class="nav-group">
          <button
            class="nav-item group-head"
            :class="{ on: route === 'pages' && !pagesOpen }"
            :title="pagesOpen ? '收起玩法包管理页' : '展开玩法包管理页'"
            @click="togglePages"
          >
            <span class="nav-icon">📑</span>
            <span class="group-title">玩法包管理页</span>
            <span class="caret">{{ pagesOpen ? "▾" : "▸" }}</span>
          </button>
          <div v-show="pagesOpen" class="group-body">
            <button
              v-for="pg in playPages"
              :key="pg.play_id + '/' + pg.key"
              class="nav-item sub"
              :class="{ on: pageOn(pg) }"
              :title="pg.title + '（' + playLabel(pg.play_id) + '）'"
              @click="gotoPage(pg)"
            >
              <span class="nav-icon">{{ pg.icon || "⚙️" }}</span>
              <span class="sub-title">{{ pg.title }}</span>
              <span v-if="multiPlay" class="sub-play">{{ playLabel(pg.play_id) }}</span>
            </button>
          </div>
        </div>
      </nav>
      <button class="side-logout" title="退出登录" @click="doLogout">⎋ 退出登录</button>
    </aside>

    <main class="content">
      <component :is="current.comp" :key="current.key" />
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { apiGet, setToken } from "../api";
import { store } from "../store";
import AccountsPage from "../pages/admin/AccountsPage.vue";
import PlaysPage from "../pages/admin/PlaysPage.vue";
import InvitesPage from "../pages/admin/InvitesPage.vue";
import WorldsPage from "../pages/admin/WorldsPage.vue";
import MapEditorPage from "../pages/admin/MapEditorPage.vue";
import PlayPageHost from "../pages/admin/PlayPageHost.vue";

const NAV = [
  { key: "accounts", title: "账户管理", icon: "👤" },
  { key: "plays", title: "玩法包", icon: "🧩" },
  { key: "invites", title: "邀请码", icon: "🎫" },
  { key: "worlds", title: "世界与地图", icon: "🌍" },
];

const PAGES = {
  accounts: AccountsPage,
  plays: PlaysPage,
  invites: InvitesPage,
  worlds: WorldsPage,
  maps: MapEditorPage, // 地图编辑器（从世界页进入，无一级导航）
  pages: PlayPageHost, // 玩法包管理页（独立路由：#/admin/pages/{play_id}/{key}）
};

// 玩法包管理页在侧栏自成一个可收起层级：展开状态本地记忆
const OPEN_KEY = "worlditor_admin_pages_open";

const route = ref("");
const routeInfo = ref({ playId: "", pageKey: "" });
const playPages = ref([]); // {play_id,key,title,icon,actions,component_url}
const playNames = ref({}); // play_id -> 显示名
const pagesOpen = ref(localStorage.getItem(OPEN_KEY) !== "0");

const current = computed(() => ({
  key: route.value,
  comp: PAGES[route.value] || PAGES.accounts,
}));

// 多个玩法包都注册管理页时，条目上补一个包名（单包时省略，避免噪音）
const multiPlay = computed(
  () => new Set(playPages.value.map((p) => p.play_id)).size > 1
);

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

function togglePages() {
  pagesOpen.value = !pagesOpen.value;
  localStorage.setItem(OPEN_KEY, pagesOpen.value ? "1" : "0");
}

function parseRoute(hash) {
  // "#/admin/accounts" / "#/admin/maps/default" / "#/admin/pages/{play_id}/{key}"
  const parts = hash.replace(/^#/, "").split("/").filter(Boolean);
  return {
    key: parts[1] || "",
    playId: decodeURIComponent(parts[2] || ""),
    pageKey: decodeURIComponent(parts[3] || ""),
  };
}

function syncRoute() {
  const info = parseRoute(location.hash);
  route.value = info.key && PAGES[info.key] ? info.key : "accounts";
  routeInfo.value = { playId: info.playId, pageKey: info.pageKey };
  // 进入管理页时确保分组展开（否则当前条目藏起来看不出在哪）
  if (route.value === "pages") pagesOpen.value = true;
}

function goto(key) {
  location.hash = `#/admin/${key}`; // 同步更新 location.hash
  route.value = key; // 立即更新（不依赖 hashchange 时序）
  routeInfo.value = { playId: "", pageKey: "" };
}

function gotoPage(pg) {
  location.hash = `#/admin/pages/${encodeURIComponent(pg.play_id)}/${encodeURIComponent(pg.key)}`;
  route.value = "pages";
  routeInfo.value = { playId: pg.play_id, pageKey: pg.key };
}

async function loadPages() {
  // 清单随玩法包启停/安装/卸载变化（PlaysPage 变更后广播 plays-changed）
  try {
    const [pages, plays] = await Promise.all([
      apiGet("/admin/play-pages"),
      apiGet("/admin/plays"),
    ]);
    playPages.value = pages.pages || [];
    playNames.value = Object.fromEntries(
      (plays.plays || []).map((p) => [p.play_id, p.name || p.play_id])
    );
  } catch (e) {
    console.warn("管理页清单加载失败：", e.message);
  }
}

function doLogout() {
  setToken("");
  store.token = "";
  store.error = "";
  location.hash = "#/auth";
}

onMounted(() => {
  syncRoute();
  window.addEventListener("hashchange", syncRoute);
  window.addEventListener("worlditor:plays-changed", loadPages);
  loadPages();
  // 登录后 hash 可能残留 #/world / #/auth——规范化到默认管理页
  if (!parseRoute(location.hash).key) {
    goto("accounts");
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
  width: 230px;
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
.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 12px;
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

/* ---------- 玩法包管理页：侧栏二级分组（可收起展开） ---------- */
.nav-group {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-top: 6px;
}
.group-head {
  justify-content: flex-start;
}
.group-title {
  flex: 1;
}
.caret {
  font-size: 11px;
  color: var(--text-dim);
}
.group-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  margin-left: 12px;
  padding-left: 10px;
  border-left: 1px solid var(--bg-3);
}
.nav-item.sub {
  font-size: 13px;
  padding: 8px 10px;
  gap: 8px;
}
.nav-item.sub .nav-icon {
  font-size: 15px;
  width: 18px;
}
.sub-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sub-play {
  margin-left: auto;
  font-size: 11px;
  color: var(--text-dim);
  flex-shrink: 0;
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
  .nav-group {
    flex-direction: row;
    align-items: center;
    gap: 2px;
    margin-top: 0;
  }
  .group-head {
    flex-direction: row;
    gap: 4px;
  }
  .group-body {
    flex-direction: row;
    align-items: center;
    gap: 2px;
    margin-left: 0;
    padding-left: 0;
    border-left: none;
  }
  .sub-play {
    display: none;
  }
  .side-logout {
    padding: 8px;
    font-size: 12px;
  }
}
</style>
