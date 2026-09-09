<template>
  <section class="card play-layout">
    <h2>玩法包</h2>

    <div class="play-body">
      <div class="play-list">
        <button
          v-for="p in plays"
          :key="p.play_id"
          class="play-item"
          :class="{ on: current && current.play_id === p.play_id }"
          @click="select(p.play_id)"
        >
          <span class="play-name">{{ p.name || p.play_id }}</span>
          <span class="badge" :class="'st-' + p.status">{{ statusText(p) }}</span>
        </button>
        <p v-if="!plays.length && !busy" class="dim center">没有玩法包</p>
      </div>

      <div class="play-detail" v-if="current">
        <header class="detail-head">
          <div>
            <h3>{{ current.name || current.play_id }}</h3>
            <p class="dim">
              <code>{{ current.play_id }}</code> · v{{ current.version }}
              · {{ current.builtin ? "内置" : "社区" }}
            </p>
          </div>
          <div class="ops">
            <button
              v-if="current.status === 'disabled'"
              class="btn"
              @click="act('enable', current.play_id)"
            >
              启用
            </button>
            <button
              v-else-if="current.status === 'loaded'"
              class="btn btn-ghost"
              @click="act('disable', current.play_id)"
            >
              停用
            </button>
            <button
              v-if="!current.builtin"
              class="btn btn-danger"
              @click="uninstall(current.play_id)"
            >
              卸载
            </button>
          </div>
        </header>

        <p v-if="current.desc" class="desc">{{ current.desc }}</p>
        <p v-if="current.error" class="error-text">加载失败：{{ current.error }}</p>
        <p v-if="current.requires && current.requires.length" class="deps">
          依赖：
          <code v-for="r in current.requires" :key="r" class="chip">{{ r }}</code>
        </p>

        <div class="tabs">
          <button
            v-for="t in tabs"
            :key="t.key"
            class="tab-btn"
            :class="{ on: tab === t.key }"
            @click="tab = t.key"
          >
            {{ t.title }}
          </button>
        </div>

        <!-- 管理页（玩法包注册的管理入口） -->
        <div v-if="tab === 'pages'" class="tab-body">
          <p v-if="!pagesOfPlay.length" class="dim">
            该玩法包未注册管理页（注册协议见 DESIGN §4.6 / PLAY_DEV §13）
          </p>
          <button
            v-for="pg in pagesOfPlay"
            :key="pg.key"
            class="page-entry"
            @click="openPlayPage(pg)"
          >
            <span>{{ pg.icon || "📄" }}</span>
            <span>{{ pg.title }}</span>
            <span class="dim">actions: {{ pg.actions.join(", ") }}</span>
          </button>
        </div>

        <!-- 工具 -->
        <div v-if="tab === 'tools'" class="tab-body">
          <p v-if="!toolsOfPlay.length" class="dim">该玩法包没有注册 MCP 工具</p>
          <table v-else class="table">
            <thead>
              <tr>
                <th>工具</th>
                <th>参数</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="t in toolsOfPlay" :key="t.name">
                <td><code>{{ t.name }}</code></td>
                <td class="dim">{{ Object.keys(t.params || {}).join(", ") || "—" }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 服务 -->
        <div v-if="tab === 'services'" class="tab-body">
          <p v-if="!servicesOfPlay.length" class="dim">该玩法包没有注册跨包服务</p>
          <table v-else class="table">
            <tbody>
              <tr v-for="s in servicesOfPlay" :key="s.name">
                <td><code>{{ s.name }}</code></td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 视图 -->
        <div v-if="tab === 'views'" class="tab-body">
          <p v-if="!viewsOfPlay.length" class="dim">该玩法包没有注册玩家视图</p>
          <table v-else class="table">
            <thead>
              <tr>
                <th>视图</th>
                <th>入口</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="v in viewsOfPlay" :key="v.key">
                <td>{{ v.title || v.key }}</td>
                <td class="dim"><code>{{ v.provider?.url }}</code></td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 原语覆盖与过滤器 -->
        <div v-if="tab === 'primitives'" class="tab-body">
          <p v-if="!primsOfPlay.length" class="dim">该玩法包未覆盖原语、未挂过滤器</p>
          <table v-else class="table">
            <thead>
              <tr>
                <th>原语</th>
                <th>类型</th>
                <th>说明</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="p in primsOfPlay" :key="p.name + p.kind">
                <td><code>{{ p.name }}</code></td>
                <td>{{ p.kind }}</td>
                <td class="dim">{{ p.label || "" }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <div v-else class="play-detail dim center">← 选择一个玩法包查看详情</div>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { apiGet, apiPost } from "../../api";

const plays = ref([]);
const pages = ref([]);
const tools = ref([]);
const services = ref([]);
const views = ref([]);
const overrides = ref([]);
const filters = ref([]);
const selected = ref("");
const tab = ref("pages");
const busy = ref(false);
const error = ref("");

const tabs = [
  { key: "pages", title: "管理页" },
  { key: "tools", title: "工具" },
  { key: "services", title: "服务" },
  { key: "views", title: "视图" },
  { key: "primitives", title: "原语" },
];

const current = computed(
  () => plays.value.find((p) => p.play_id === selected.value) || null
);
const pagesOfPlay = computed(() =>
  pages.value.filter((p) => p.play_id === selected.value)
);
const toolsOfPlay = computed(() =>
  tools.value.filter((t) => t.play_id === selected.value)
);
const servicesOfPlay = computed(() =>
  services.value.filter((s) => s.play_id === selected.value)
);
const viewsOfPlay = computed(() =>
  views.value.filter((v) => v.play_id === selected.value)
);
const primsOfPlay = computed(() => [
  ...overrides.value
    .filter((o) => o.play_id === selected.value)
    .map((o) => ({
      name: o.name,
      kind: o.mode === "disable" ? "禁用" : "覆盖",
      label: "",
    })),
  ...filters.value
    .filter((f) => f.play_id === selected.value)
    .map((f) => ({ name: f.name, kind: "过滤器", label: f.label })),
]);

function statusText(p) {
  return {
    loaded: "已启用",
    disabled: "已停用",
    load_failed: "加载失败",
    invalid: "无效",
  }[p.status] || p.status;
}

async function load() {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    const [pl, pg, tl, sv, vw, ov, ft] = await Promise.allSettled([
      apiGet("/admin/plays"),
      apiGet("/admin/play-pages"),
      apiGet("/admin/tools"),
      apiGet("/admin/services"),
      apiGet("/admin/views"),
      apiGet("/admin/overrides"),
    ]);
    if (pl.status === "fulfilled") {
      plays.value = pl.value.plays || [];
      if (!selected.value && plays.value.length) selected.value = plays.value[0].play_id;
      else if (selected.value && !plays.value.some((p) => p.play_id === selected.value))
        selected.value = plays.value[0]?.play_id || "";
    } else error.value = pl.reason.message;
    if (pg.status === "fulfilled") pages.value = pg.value.pages || [];
    if (tl.status === "fulfilled") tools.value = tl.value.tools || [];
    if (sv.status === "fulfilled") services.value = sv.value.services || [];
    if (vw.status === "fulfilled") views.value = vw.value.views || [];
    if (ov.status === "fulfilled") {
      overrides.value = ov.value.overrides || [];
      filters.value = ov.value.filters || [];
    }
  } finally {
    busy.value = false;
  }
}

function select(id) {
  selected.value = id;
}

async function act(kind, playId) {
  try {
    await apiPost(`/admin/plays/${playId}/${kind}`);
    await load();
  } catch (e) {
    error.value = e.message;
  }
}

async function uninstall(playId) {
  if (!confirm(`卸载玩法包 ${playId}？其目录与数据将被删除，不可恢复。`)) return;
  try {
    await apiPost(`/admin/plays/${playId}/uninstall`);
    await load();
  } catch (e) {
    error.value = e.message;
  }
}

function openPlayPage(pg) {
  // 管理页为独立路由页面（#/admin/pages/{play_id}/{key}）——复杂配置的
  // 管理页可自建二级面板，避免弹窗套弹窗
  location.hash = `#/admin/pages/${encodeURIComponent(pg.play_id)}/${encodeURIComponent(pg.key)}`;
}

onMounted(load);
</script>

<style scoped>
.play-body {
  display: flex;
  gap: 12px;
  align-items: stretch;
}
.play-list {
  width: 220px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 560px;
  overflow: auto;
}
.play-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 9px 10px;
  border: none;
  border-radius: var(--radius);
  background: transparent;
  color: var(--text);
  cursor: pointer;
  text-align: left;
}
.play-item.on {
  background: var(--bg-3);
}
.play-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.badge {
  font-size: 11px;
  border-radius: 10px;
  padding: 1px 8px;
  flex-shrink: 0;
  color: var(--text-dim);
  border: 1px solid var(--bg-3);
}
.st-loaded {
  color: var(--accent);
  border-color: var(--accent-dim);
}
.st-disabled {
  color: var(--text-dim);
}
.st-load_failed {
  color: var(--danger);
}
.play-detail {
  flex: 1;
  min-width: 0;
}
.detail-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 10px;
}
.detail-head h3 {
  margin: 0;
}
.desc {
  color: var(--text-dim);
  font-size: 14px;
}
.deps {
  font-size: 13px;
  display: flex;
  gap: 6px;
  align-items: center;
  flex-wrap: wrap;
}
.chip {
  border: 1px solid var(--bg-3);
  border-radius: 20px;
  padding: 1px 8px;
  font-size: 12px;
}
.tabs {
  display: flex;
  gap: 4px;
  border-bottom: 1px solid var(--bg-3);
  margin-top: 8px;
}
.tab-btn {
  border: none;
  background: transparent;
  color: var(--text-dim);
  padding: 8px 12px;
  cursor: pointer;
  font-size: 14px;
}
.tab-btn.on {
  color: var(--text);
  border-bottom: 2px solid var(--accent);
}
.tab-body {
  padding-top: 10px;
}
.page-entry {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  padding: 12px 14px;
  border: 1px solid var(--bg-3);
  border-radius: var(--radius);
  background: var(--bg-2);
  color: var(--text);
  cursor: pointer;
  margin-bottom: 6px;
  font-size: 14px;
}
.page-entry:hover {
  border-color: var(--accent-dim);
}
.dim {
  color: var(--text-dim);
  font-size: 13px;
}
.center {
  text-align: center;
  padding: 24px 0;
}

/* 窄屏：列表横排滚动，详情在下 */
@media (max-width: 900px) {
  .play-body {
    flex-direction: column;
  }
  .play-list {
    width: 100%;
    max-height: none;
    flex-direction: row;
    overflow-x: auto;
    padding-bottom: 4px;
  }
  .play-item {
    white-space: nowrap;
    flex-shrink: 0;
  }
}
</style>
