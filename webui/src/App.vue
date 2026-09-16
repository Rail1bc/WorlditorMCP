<template>
  <!-- 管理端口：管理台全宽布局（PC 优先，脱离玩家端 720px 容器） -->
  <AdminPanel v-if="hasToken && store.mode === 'admin'" />

  <div v-else class="app">
    <!-- 未登录 → 登录/注册 -->
    <AuthPage v-if="!hasToken" />

    <template v-else>
      <!-- 玩家端口：视图宿主（D7/G3） -->
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
        <button class="header-btn" title="永久注销账户" @click="doDeleteAccount">🗑</button>
        <button class="header-btn" title="退出登录" @click="doLogout">⎋</button>
      </header>

      <main class="app-main">
        <div v-if="currentView && currentView.comp" class="view-host">
          <component :is="currentView.comp" :view="currentView.meta" />
        </div>
        <div v-else class="empty-hint">
          <p>这个世界还没有任何视图。</p>
          <p class="dim">
            视图与工具由玩法包提供——去管理端安装/启用玩法包；
            还没有地图就先在地图编辑器里建一张。
          </p>
        </div>
      </main>
    </template>
  </div>

  <!-- 全局错误提示 -->
  <Transition name="fade">
    <div v-if="store.error" class="toast">{{ store.error }}</div>
  </Transition>

  <!-- 全局确认层（替代原生 confirm；原生弹窗在 iframe/沙箱里会被浏览器屏蔽） -->
  <ConfirmHost />
</template>

<script setup>
import { computed, onMounted, ref, watch } from "vue";
import * as Vue from "vue";
import { getToken, listViews, logout, setToken, deleteAccount, getMeta } from "./api";
import { askConfirm } from "./confirm";
import { store } from "./store";
import AuthPage from "./pages/AuthPage.vue";
import AdminPanel from "./components/AdminPanel.vue";
import ConfirmHost from "./components/ConfirmHost.vue";
import UiBlockRenderer from "./components/UiBlockRenderer.vue";

const route = ref(location.hash.replace(/^#/, "") || "");
const views = ref([]); // {key,title,icon,play_id,provider}
const loaded = ref({}); // key -> 组件对象（缓存）
const metaReady = ref(false); // /meta 已确认端口模式（此前 mode 只是默认值）

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
    // 视图列表失败不弹全局错误（登录前 401 属正常流程，静默）
    console.warn("视图列表加载失败：", e.message);
  }
  // 默认进入第一个视图（仅在已登录时：未登录预加载必然 401，会留下误导提示）
  if (!route.value && views.value.length && store.token) {
    goto(views.value[0].key);
  }
}

async function goto(key) {
  location.hash = "/view/" + key;
  if (loaded.value[key]) return;
  const meta = views.value.find((v) => v.key === key);
  if (!meta) return;
  try {
    const headers = {};
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const res = await fetch(meta.provider.url, { headers });
    // 401 = 尚未登录/凭据失效：静默跳过（登录后由 watch(hasToken) 重新加载）
    if (res.status === 401) return;
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const code = await res.text();
    // 视图组件协议（G3）：文件 = IIFE（function(Vue, UiBlock) 形参由加载器注入）
    // ——new Function body = "return (<code>)(Vue, UiBlock);"，执行返回组件选项
    // eslint-disable-next-line no-new-func
    const factory = new Function(
      "Vue",
      "UiBlock",
      "return (" + code.trim().replace(/;+\s*$/, "") + ")(Vue, UiBlock);"
    );
    loaded.value[key] = factory(Vue, UiBlockRenderer);
  } catch (e) {
    store.error = "视图加载失败：" + e.message;
  }
}

function doLogout() {
  logout().catch(() => {});
  setToken("");
  store.token = "";
  store.error = "";
  location.hash = "#/auth";
}

async function doDeleteAccount() {
  const ok = await askConfirm({
    title: "永久注销账户",
    danger: true,
    text: "确定永久注销账户？",
    detail: "角色与实体将被删除，该操作不可恢复。",
    confirmText: "永久注销",
  });
  if (!ok) return;
  try {
    await deleteAccount();
    doLogout();
  } catch (e) {
    store.error = e.message;
  }
}

// 登录后若无路由（AuthPage 登录成功时会清空 hash）→ 按视图列表进默认视图
// （metaReady：/meta 未回来前 store.mode 是默认值 "play"，管理端会误发 /views → 404）
watch(hasToken, (token) => {
  if (token && metaReady.value && store.mode === "play" && !route.value) {
    refreshViews();
  }
});

// 全局错误 toast 自动消失（否则一条旧错误会常驻，例如登录前的 401 预加载）
watch(
  () => store.error,
  (message) => {
    if (!message) return;
    setTimeout(() => {
      if (store.error === message) store.error = "";
    }, 4000);
  }
);

onMounted(async () => {
  store.token = getToken();
  try {
    const meta = await getMeta();
    store.mode = meta.mode === "admin" ? "admin" : "play";
  } catch (e) {
    store.error = e.message;
  }
  metaReady.value = true;
  window.addEventListener("hashchange", () => {
    route.value = location.hash.replace(/^#/, "") || "";
  });
  // 管理模式不加载玩家视图（/views 仅玩家端口存在，D16 界面分离）
  if (store.mode === "play") {
    refreshViews();
  }
});
</script>
