<template>
  <div class="app">
    <!-- 未登录 → 登录/注册 -->
    <AuthPage v-if="!hasToken" />

    <template v-else>
      <!-- 管理端口：管理面板（D16 界面分离）；玩家端口：视图宿主（D7/G3） -->
      <AdminPanel v-if="store.mode === 'admin'" />

      <template v-else>
        <header class="app-header">
          <span class="brand">worlditor</span>
          <nav class="view-tabs">
            <button
              v-for="v in views"
              :key="v.key"
              class="tab"
              :class="{ on: route === '/view/' + v.key }"
              @click="goto(v.key)"
            >
              <span class="tab-icon">{{ v.icon || "📄" }}</span>
              <span>{{ v.title }}</span>
            </button>
          </nav>
          <button class="logout-btn" title="永久注销账户" @click="doDeleteAccount">🗑</button>
          <button class="logout-btn" title="退出登录" @click="doLogout">⎋</button>
        </header>

        <main class="app-main">
          <component
            v-if="currentView && currentView.comp"
            :is="currentView.comp"
            :view="currentView.meta"
          />
          <div v-else class="empty-hint">
            <p>这个世界还没有任何视图。</p>
            <p class="dim">管理员可在管理端口（默认 6289）安装玩法包。</p>
          </div>
        </main>
      </template>

      <!-- 全局错误提示 -->
      <Transition name="fade">
        <div v-if="store.error" class="toast">{{ store.error }}</div>
      </Transition>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import * as Vue from "vue";
import { getToken, listViews, logout, setToken, deleteAccount, getMeta } from "./api";
import { store } from "./store";
import AuthPage from "./pages/AuthPage.vue";
import AdminPanel from "./components/AdminPanel.vue";
import UiBlockRenderer from "./components/UiBlockRenderer.vue";

const route = ref(location.hash.replace(/^#/, "") || "");
const views = ref([]); // {key,title,icon,play_id,provider}
const loaded = ref({}); // key -> 组件对象（缓存）

const hasToken = computed(() => Boolean(store.token));
const currentView = computed(() => {
  const key = route.value.startsWith("/view/") ? route.value.slice(6) : "";
  const meta = views.value.find((v) => v.key === key);
  if (!meta) return null;
  return { meta, comp: loaded.value[key] || null };
});

async function refreshViews() {
  try {
    views.value = (await listViews()).views || [];
  } catch (e) {
    store.error = e.message;
  }
  // 默认进入第一个视图
  if (!route.value && views.value.length) {
    goto(views.value[0].key);
  }
}

async function goto(key) {
  location.hash = "/view/" + key;
  if (loaded.value[key]) return;
  const meta = views.value.find((v) => v.key === key);
  if (!meta) return;
  try {
    const res = await fetch(meta.provider.url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const code = await res.text();
    // 视图组件协议（G3）：(function(Vue, UiBlock) { return { ...组件选项... } })
    // eslint-disable-next-line no-new-func
    const factory = new Function("Vue", "UiBlock", code);
    loaded.value[key] = factory(Vue, UiBlockRenderer);
  } catch (e) {
    store.error = "视图加载失败：" + e.message;
  }
}

function doLogout() {
  logout().catch(() => {});
  setToken("");
  store.token = "";
  store.entity = null;
  store.scene = null;
  store.world = null;
  store.log = [];
  location.hash = "#/auth";
}

async function doDeleteAccount() {
  if (!confirm("确定永久注销账户？角色与实体将被删除，该操作不可恢复。")) return;
  try {
    await deleteAccount();
    doLogout();
  } catch (e) {
    store.error = e.message;
  }
}

onMounted(async () => {
  store.token = getToken();
  try {
    const meta = await getMeta();
    store.mode = meta.mode === "admin" ? "admin" : "play";
  } catch (e) {
    store.error = e.message;
  }
  window.addEventListener("hashchange", () => {
    route.value = location.hash.replace(/^#/, "") || "";
  });
  // 管理模式不加载玩家视图（/views 仅玩家端口存在，D16 界面分离）
  if (store.mode === "play") {
    refreshViews();
  }
});
</script>
