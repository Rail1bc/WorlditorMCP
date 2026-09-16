<template>
  <section class="card">
    <div class="page-head">
      <h2>
        玩法包
        <code class="dim">{{ worldId }}</code>
      </h2>
      <div class="ops">
        <button class="btn" :disabled="busy" @click="pickFile">
          安装玩法包（zip）
        </button>
        <button class="btn btn-ghost" :disabled="busy" @click="load">刷新</button>
      </div>
    </div>
    <input
      ref="fileInput"
      type="file"
      accept=".zip,application/zip"
      class="hidden-file"
      @change="onFile"
    />
    <p v-if="note" class="dim">{{ note }}</p>
    <p v-if="error" class="error-text">{{ error }}</p>

    <!-- 激活模式：全部启用（play_ids 空）/ 自定义（显式名单） -->
    <div class="mode-row">
      <div class="seg">
        <button :class="{ on: mode === 'all' }" @click="useAll">全部启用</button>
        <button :class="{ on: mode === 'custom' }" @click="useCustom">
          自定义
        </button>
      </div>
      <span class="dim">{{ summary }}</span>
    </div>
    <p v-if="staleIds.length" class="dim warn">
      名单里有 {{ staleIds.length }} 个已不在的玩法包（{{ staleIds.join("、") }}）——
      卸载/停用后残留的名单项不生效，可在下方任一开关操作时清掉。
    </p>

    <div class="play-body">
      <div class="play-list">
        <div
          v-for="p in plays"
          :key="p.play_id"
          class="play-item"
          :class="{ on: current && current.play_id === p.play_id }"
          @click="select(p.play_id)"
        >
          <span class="play-name">{{ p.name || p.play_id }}</span>
          <span class="badge" :class="'st-' + p.status">{{ statusText(p) }}</span>
          <button
            class="world-pill"
            :class="{ on: isActive(p.play_id) }"
            :disabled="p.status !== 'loaded'"
            :title="pillTitle(p)"
            @click.stop="toggle(p.play_id)"
          >
            {{ isActive(p.play_id) ? "本世界 启用" : "本世界 未启用" }}
          </button>
        </div>
        <p v-if="!plays.length && !busy" class="dim center">没有玩法包</p>
      </div>

      <div v-if="current" class="play-detail">
        <header class="detail-head">
          <div>
            <h3>{{ current.name || current.play_id }}</h3>
            <p class="dim">
              <code>{{ current.play_id }}</code> · v{{ current.version }}
              · {{ current.builtin ? "内置" : "社区" }}
            </p>
          </div>
        </header>

        <p v-if="current.desc" class="desc">{{ current.desc }}</p>
        <p v-if="current.error" class="error-text">
          加载失败：{{ current.error }}
        </p>
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

        <!-- 工具 -->
        <div v-if="tab === 'tools'" class="tab-body">
          <p v-if="!toolsOfPlay.length" class="dim">
            该玩法包没有注册 MCP 工具
          </p>
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
                <td class="dim">
                  {{ Object.keys(t.params || {}).join(", ") || "—" }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 服务 -->
        <div v-if="tab === 'services'" class="tab-body">
          <p v-if="!servicesOfPlay.length" class="dim">
            该玩法包没有注册跨包服务
          </p>
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
                <td class="dim">
                  <code>{{ v.provider?.url }}</code>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <!-- 原语覆盖与过滤器 -->
        <div v-if="tab === 'primitives'" class="tab-body">
          <p v-if="!primsOfPlay.length" class="dim">
            该玩法包未覆盖原语、未挂过滤器
          </p>
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

        <!-- 全局（代码层）操作：影响所有世界 -->
        <details class="global-ops">
          <summary>高级：全局加载状态（影响所有世界）</summary>
          <p class="dim">
            全局停用 = 卸载代码注册（该包在所有世界都消失），play_data 与资源保留；
            这里的主开关只改「本世界是否启用」。
          </p>
          <div class="ops">
            <button
              v-if="current.status === 'disabled'"
              class="btn"
              @click="act('enable', current.play_id)"
            >
              全局启用
            </button>
            <button
              v-else-if="current.status === 'loaded'"
              class="btn btn-ghost"
              @click="act('disable', current.play_id)"
            >
              全局停用
            </button>
            <button
              v-if="!current.builtin"
              class="btn btn-danger"
              @click="uninstall(current.play_id)"
            >
              卸载（删除目录）
            </button>
          </div>
        </details>
      </div>

      <div v-else class="play-detail dim center">
        ← 选择一个玩法包查看详情
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref, watch } from "vue";
import { apiGet, apiPatch, apiPost, installPlay } from "../../api";
import { askConfirm } from "../../confirm";

const props = defineProps({
  worldId: { type: String, default: "" },
});
const emit = defineEmits(["world-changed"]);

const plays = ref([]);
const tools = ref([]);
const services = ref([]);
const views = ref([]);
const overrides = ref([]);
const filters = ref([]);
const world = ref(null);
const selected = ref("");
const tab = ref("tools");
const busy = ref(false);
const error = ref("");
const note = ref("");
const fileInput = ref(null);

const tabs = [
  { key: "tools", title: "工具" },
  { key: "services", title: "服务" },
  { key: "views", title: "视图" },
  { key: "primitives", title: "原语" },
];

const loadedPlays = computed(() =>
  plays.value.filter((p) => p.status === "loaded")
);
const playIds = computed(() => (world.value?.play_ids || []).slice());
const mode = computed(() => (playIds.value.length ? "custom" : "all"));
const summary = computed(() => {
  const total = loadedPlays.value.length;
  if (mode.value === "all") return `本世界：全部启用（共 ${total} 个已加载包）`;
  const live = playIds.value.filter((id) =>
    plays.value.some((p) => p.play_id === id && p.status === "loaded")
  );
  return `本世界：自定义 —— 启用 ${live.length} / 共 ${total} 个已加载包`;
});
const staleIds = computed(() => {
  if (mode.value === "all") return [];
  return playIds.value.filter((id) => !plays.value.some((p) => p.play_id === id));
});

const current = computed(
  () => plays.value.find((p) => p.play_id === selected.value) || null
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
  return (
    {
      loaded: "已启用",
      disabled: "已停用",
      load_failed: "加载失败",
      invalid: "无效",
    }[p.status] || p.status
  );
}

function isActive(playId) {
  if (mode.value === "all") return true;
  return playIds.value.includes(playId);
}

function pillTitle(p) {
  if (p.status !== "loaded") return "该包全局未加载，本世界无法启用（先到高级里全局启用）";
  return isActive(p.play_id)
    ? "点击：在本世界停用（其他世界不受影响）"
    : "点击：在本世界启用";
}

async function load() {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    const [worlds, pl, tl, sv, vw, ov] = await Promise.allSettled([
      apiGet("/admin/worlds"),
      apiGet("/admin/plays"),
      apiGet("/admin/tools"),
      apiGet("/admin/services"),
      apiGet("/admin/views"),
      apiGet("/admin/overrides"),
    ]);
    if (worlds.status === "fulfilled") {
      const list = worlds.value.worlds || [];
      world.value =
        list.find((w) => w.id === props.worldId) || list[0] || null;
    } else error.value = worlds.reason.message;
    if (pl.status === "fulfilled") {
      plays.value = pl.value.plays || [];
      if (!selected.value && plays.value.length)
        selected.value = plays.value[0].play_id;
      else if (
        selected.value &&
        !plays.value.some((p) => p.play_id === selected.value)
      )
        selected.value = plays.value[0]?.play_id || "";
    } else error.value = pl.reason.message;
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

async function savePlayIds(ids, message) {
  if (!world.value) return;
  try {
    await apiPatch(`/admin/worlds/${encodeURIComponent(world.value.id)}`, {
      play_ids: ids,
    });
    note.value = message || "";
    await load();
    emit("world-changed"); // 侧栏刷新（管理页分组随激活集合变化）
  } catch (e) {
    error.value = e.message;
  }
}

async function useAll() {
  if (mode.value === "all" || !world.value) return;
  const ok = await askConfirm({
    title: "全部启用",
    text: `把「${world.value.name}」的玩法包全部启用？`,
    detail: "该世界将跟随全局加载状态（以后新装的包自动生效）。",
    confirmText: "全部启用",
  });
  if (!ok) return;
  await savePlayIds([], "已切换为「全部启用」");
}

async function useCustom() {
  if (mode.value === "custom" || !world.value) return;
  await savePlayIds(
    loadedPlays.value.map((p) => p.play_id),
    "已切换为「自定义」：以当前已加载的包生成名单，可逐个开关"
  );
}

async function toggle(playId) {
  if (!world.value) return;
  const ids = new Set(mode.value === "all" ? loadedPlays.value.map((p) => p.play_id) : playIds.value);
  const next = ids.has(playId);
  if (next) ids.delete(playId);
  else ids.add(playId);
  await savePlayIds(
    [...ids],
    next
      ? `本世界已停用：${playId}`
      : `本世界已启用：${playId}`
  );
}

function select(id) {
  selected.value = id;
}

async function act(kind, playId) {
  try {
    await apiPost(`/admin/plays/${playId}/${kind}`);
    await load();
    emit("world-changed");
  } catch (e) {
    error.value = e.message;
  }
}

async function uninstall(playId) {
  const ok = await askConfirm({
    title: "卸载玩法包",
    danger: true,
    text: `卸载玩法包 ${playId}？`,
    detail: "其目录与数据将被删除，不可恢复。",
    confirmText: "卸载",
  });
  if (!ok) return;
  try {
    await apiPost(`/admin/plays/${playId}/uninstall`);
    await load();
  } catch (e) {
    error.value = e.message;
  }
}

function pickFile() {
  if (fileInput.value) fileInput.value.click();
}

async function onFile(event) {
  const file = event.target.files && event.target.files[0];
  event.target.value = ""; // 允许连续上传同一个文件
  if (!file) return;
  busy.value = true;
  error.value = "";
  note.value = "";
  try {
    const res = await installPlay(file);
    const installed = (res && res.data && res.data.play_id) || "";
    note.value = installed ? `已安装并启用：${installed}` : "安装完成";
    await load();
    emit("world-changed");
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
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
  margin-bottom: 10px;
}
.page-head h2 {
  margin: 0;
}
.hidden-file {
  display: none;
}
.mode-row {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
.warn {
  color: var(--danger);
  opacity: 0.85;
}
.play-body {
  display: flex;
  gap: 12px;
  align-items: stretch;
}
.play-list {
  width: 260px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 620px;
  overflow: auto;
}
.play-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  border-radius: var(--radius);
  background: transparent;
  color: var(--text);
  cursor: pointer;
  text-align: left;
  border: 1px solid transparent;
}
.play-item:hover {
  border-color: var(--bg-3);
}
.play-item.on {
  background: var(--bg-3);
}
.play-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 14px;
}
.badge {
  font-size: 11px;
  border-radius: 10px;
  padding: 1px 7px;
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
.world-pill {
  flex-shrink: 0;
  font-size: 11px;
  border-radius: 10px;
  padding: 2px 8px;
  cursor: pointer;
  border: 1px solid var(--bg-3);
  background: transparent;
  color: var(--text-dim);
}
.world-pill.on {
  color: var(--accent);
  border-color: var(--accent-dim);
  background: rgba(94, 200, 168, 0.12);
}
.world-pill:disabled {
  opacity: 0.4;
  cursor: not-allowed;
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
.global-ops {
  margin-top: 14px;
  border-top: 1px solid var(--bg-3);
  padding-top: 8px;
}
.global-ops summary {
  cursor: pointer;
  color: var(--text-dim);
  font-size: 13px;
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
