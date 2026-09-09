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
          :class="{ on: route === item.key }"
          @click="goto(item.key)"
        >
          <span class="nav-icon">{{ item.icon }}</span>
          <span>{{ item.title }}</span>
        </button>
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
import { getToken, setToken } from "../api";
import { store } from "../store";
import AccountsPage from "../pages/admin/AccountsPage.vue";
import PlaysPage from "../pages/admin/PlaysPage.vue";
import InvitesPage from "../pages/admin/InvitesPage.vue";
import WorldsPage from "../pages/admin/WorldsPage.vue";
import MapEditorPage from "../pages/admin/MapEditorPage.vue";

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
};

const route = ref("");

const current = computed(() => ({
  key: route.value,
  comp: PAGES[route.value] || PAGES.accounts,
}));

function parseRoute(hash) {
  // "#/admin/accounts" / "#/admin/maps/default" → "accounts" / "maps"
  const parts = hash.replace(/^#/, "").split("/").filter(Boolean);
  return parts[1] || "";
}

function syncRoute() {
  const key = parseRoute(location.hash);
  route.value = key && PAGES[key] ? key : "accounts";
}

function goto(key) {
  location.hash = `#/admin/${key}`; // 同步更新 location.hash
  route.value = key; // 立即更新（不依赖 hashchange 时序）
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
  // 登录后 hash 可能残留 #/world / #/auth——规范化到默认管理页
  if (!parseRoute(location.hash)) {
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
  .logout-btn {
    padding: 8px;
    font-size: 12px;
  }
}
</style>
