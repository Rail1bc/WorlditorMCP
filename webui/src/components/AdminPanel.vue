<template>
  <div class="admin-shell">
    <header class="app-header">
      <span class="brand">🛠 worlditor 管理台</span>
      <button class="logout-btn" title="退出登录" @click="doLogout">⎋</button>
    </header>

    <div class="admin-body">
      <nav class="admin-nav">
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

      <main class="admin-main">
        <component :is="current.comp" :key="current.key" />
      </main>
    </div>
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
  maps: MapEditorPage, // 地图编辑器入口（经 worlds 页面进入）
};

const route = ref("");

const current = computed(() => {
  // hash 形如 "#/admin/accounts" 或 "#/admin/maps/default"
  const hash = location.hash.replace(/^#/, "");
  const parts = hash.split("/").filter(Boolean); // ["admin","maps","default"]
  const key = parts[1] || "accounts";
  return { key, comp: PAGES[key] || PAGES.accounts };
});

function goto(key) {
  location.hash = `#/admin/${key}`;
  route.value = key;
}

function syncRoute() {
  const hash = location.hash.replace(/^#/, "");
  const parts = hash.split("/").filter(Boolean);
  route.value = parts[1] || "accounts";
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
  if (!location.hash) goto("accounts");
});
</script>

<style scoped>
.admin-shell {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
  max-width: 960px;
  margin: 0 auto;
}
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
}
.brand {
  font-weight: 700;
}
.admin-body {
  display: flex;
  flex: 1;
  gap: 12px;
  padding: 0 12px 16px;
}
.admin-nav {
  display: flex;
  flex-direction: column;
  gap: 4px;
  width: 132px;
  flex-shrink: 0;
  position: sticky;
  top: 8px;
  align-self: flex-start;
}
.nav-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  border: none;
  border-radius: var(--radius);
  background: transparent;
  color: var(--text-dim);
  font-size: 14px;
  cursor: pointer;
  text-align: left;
}
.nav-item.on {
  background: var(--bg-3);
  color: var(--text);
}
.nav-icon {
  font-size: 17px;
}
.admin-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.logout-btn {
  border: none;
  border-radius: 50%;
  width: 36px;
  height: 36px;
  background: var(--bg-3);
  color: var(--text-dim);
  cursor: pointer;
}
</style>
