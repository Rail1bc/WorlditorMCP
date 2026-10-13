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
  <!-- 保存前差异预览（G24 防线：整对象替换的写操作必须先看见旧→新） -->
  <DiffModal />
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import * as Vue from "vue";
import {
  WORLD_API,
  getToken,
  listViews,
  logout,
  setToken,
  deleteAccount,
  getMeta,
} from "./api";
import { askConfirm } from "./confirm";
import { store } from "./store";
import AuthPage from "./pages/AuthPage.vue";
import AdminPanel from "./components/AdminPanel.vue";
import ConfirmHost from "./components/ConfirmHost.vue";
import DiffModal from "./components/DiffModal.vue";
import UiBlockRenderer from "./components/UiBlockRenderer.vue";

const route = ref(location.hash.replace(/^#/, "") || "");
const views = ref([]); // {key,title,icon,play_id,provider}
const loaded = ref({}); // key -> 组件对象（缓存）
const metaReady = ref(false); // /meta 已确认端口模式（此前 mode 只是默认值）
let viewsSeq = 0; // 视图清单竞态序号（SSE 与登录可能同时触发刷新）
let events = null; // EventSource（null = 未连接）
let eventsDead = false; // 事件流不可用（403/404/网络失败）→ 本次凭据不再重试
let eventsWarned = false; // 降级只在控制台提示一次，不打扰玩家

const hasToken = computed(() => Boolean(store.token));
const currentView = computed(() => {
  const key = route.value.startsWith("/view/") ? route.value.slice(6) : "";
  const meta = views.value.find((v) => v.key === key);
  if (!meta) return null;
  return { meta, comp: loaded.value[key] || null };
});

async function refreshViews() {
  const seq = ++viewsSeq;
  let list;
  try {
    list = (await listViews()).views || [];
  } catch (e) {
    // 视图列表失败不弹全局错误（登录前 401 属正常流程，静默）
    console.warn("视图列表加载失败：", e.message);
    return;
  }
  if (seq !== viewsSeq) return; // 并发刷新：只用最新一次的结果
  views.value = list;
  // 组件缓存随注册表收敛：已消失的视图（包被停用/卸载）丢掉缓存，
  // 重新出现时按新组件重新加载（否则可能拿到旧版本的组件代码）
  for (const key of Object.keys(loaded.value)) {
    if (!list.some((v) => v.key === key)) delete loaded.value[key];
  }
  const selected = route.value.startsWith("/view/") ? route.value.slice(6) : "";
  if (!selected) {
    // 默认进入第一个视图（仅在已登录时：未登录预加载必然 401，会留下误导提示）
    if (list.length && store.token) goto(list[0].key);
    return;
  }
  // 选中的视图还在 → 保持不动（组件不重挂，页面状态不丢）
  if (list.some((v) => v.key === selected)) return;
  // 选中的视图随玩法包消失 → 优雅回退：还有视图就切第一个，全没了就回空态
  if (list.length) {
    goto(list[0].key);
  } else {
    location.hash = "";
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  }
}

// ---------- SSE：玩法包注册表变化 → 视图 tab 自动跟随（不再要手动整页刷新） ----------
// 玩家端口 GET /events（内核信号出口）。EventSource 不能带请求头，凭据只能走
// ?token=（服务端支持 query token）；档位要求 play/admin，read 围观档会被 403。
// 管理端口**没有** /events（已知边界）→ mode==="play" 才连。

function closeEvents() {
  if (!events) return;
  events.close();
  events = null;
}

function openEvents() {
  if (events || eventsDead) return;
  const token = getToken();
  if (!token || !metaReady.value || store.mode !== "play") return;
  if (typeof EventSource !== "function") return; // 老浏览器：静默降级
  try {
    events = new EventSource(
      `${WORLD_API}/events?token=${encodeURIComponent(token)}`
    );
  } catch (e) {
    eventsDead = true;
    console.warn("事件流不可用，视图 tab 退回整页刷新：", e.message);
    return;
  }
  events.onmessage = (ev) => {
    let payload = null;
    try {
      payload = JSON.parse(ev.data);
    } catch {
      return; // 非 JSON 帧（异常生产端）直接忽略
    }
    // 事件名恒在 data 的 "event" 键里（服务端只发 data: 行、没有 event: 行），
    // 所以必须用 onmessage + 自己判断，不能 addEventListener("plays_changed")。
    // 载荷形状（内核 engine._event_payload 自定义事件分支）：
    //   {event, ts, entity, revision, tick, data:{reason, plays:[play_id...]}}
    // ——reason 在 data 下；这里不需要区分 load_all/enable/disable/install/uninstall，
    // 收到 plays_changed 就重拉 /views（本轮不刷新 /state 与实体数据）。
    if (!payload || payload.event !== "plays_changed") return;
    refreshViews();
  };
  events.onerror = () => {
    // 403/404 等非 200：EventSource 规范会直接置 CLOSED（不再自动重连）；
    // 网络层失败则是 CONNECTING + 浏览器按 retry 自动重连。
    // 两种都只 console.warn 一次并静默降级，绝不弹 toast 打扰玩家。
    if (events && events.readyState === EventSource.CLOSED) {
      eventsDead = true;
      closeEvents();
      if (!eventsWarned) {
        eventsWarned = true;
        console.warn("事件流不可用，视图 tab 退回整页刷新");
      }
    } else if (!eventsWarned) {
      eventsWarned = true;
      console.warn("事件流连接失败，视图 tab 退回整页刷新");
    }
  };
}

function syncEvents() {
  // 未登录 / 管理端口 / 模式未确认 → 一律不连（避免泄漏与失效 token 的 401 重连风暴）
  if (!getToken() || !metaReady.value || store.mode !== "play") {
    closeEvents();
    return;
  }
  openEvents();
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
  closeEvents(); // 立即断开：失效凭据的 SSE 重连只会白刷服务器
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
  if (!token) {
    closeEvents(); // 退出登录 / 凭据失效：关掉事件流
    return;
  }
  eventsDead = false; // 新凭据给事件流一次机会（此前 403 可能是 read 档）
  syncEvents();
  if (metaReady.value && store.mode === "play" && !route.value) {
    refreshViews();
  }
});

// 端口模式确认：管理端口没有 /events（已知边界）→ 模式不是 play 时确保断开
watch(
  () => store.mode,
  () => syncEvents()
);

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
    syncEvents(); // 已登录才真的连（openEvents 内部再校验 token）
  }
});

// 根组件基本不会卸载；显式收尾，别把连接留给下一次挂载（防御）
onUnmounted(closeEvents);
</script>
