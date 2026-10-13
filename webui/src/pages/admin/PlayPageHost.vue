<template>
  <section class="card page-host">
    <header class="host-head">
      <h2>{{ icon }} {{ title }}</h2>
      <p class="dim">
        <code>{{ playId }} · {{ pageKey }}</code>
      </p>
    </header>

    <!-- error 优先于组件：失败时就只显示错误行（原先 v-if 挂在 comp 上，
         error 与"加载中…"会同时出现） -->
    <p v-if="error" class="error-text">{{ error }}</p>
    <component
      v-else-if="comp"
      :is="comp"
      :page="page"
      :key="playId + '/' + pageKey"
    />
    <p v-else class="dim">加载管理页组件…</p>
  </section>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import * as Vue from "vue";
import { apiGet, getToken } from "../../api";
import UiBlockRenderer from "../../components/UiBlockRenderer.vue";

// hash: #/admin/pages/{play_id}/{page_key}
const playId = ref("");
const pageKey = ref("");
const pages = ref([]);
const comp = ref(null);
const error = ref("");
// 竞态序号：切换 (play_id, page_key) 后，旧请求的迟到结果必须丢弃，
// 否则会出现"B 的地址 + A 的组件"（本文件要修的原始缺陷）。
let loadSeq = 0;

const page = computed(
  () =>
    pages.value.find(
      (p) => p.play_id === playId.value && p.key === pageKey.value
    ) || null
);

const title = computed(() => page.value?.title || pageKey.value || "管理页");
const icon = computed(() => page.value?.icon || "⚙️");

function syncFromHash() {
  const parts = location.hash.replace(/^#/, "").split("/").filter(Boolean);
  // ["admin", "pages", play_id, page_key]
  playId.value = decodeURIComponent(parts[2] || "");
  pageKey.value = decodeURIComponent(parts[3] || "");
}

async function load() {
  const seq = ++loadSeq;
  // ① 先清掉上一页的组件与错误：加载期间只显示"加载中…"，
  //    绝不把 A 页的界面留在 B 页的标题下面（错组件渲染的来源）。
  comp.value = null;
  error.value = "";
  let entry = null;
  try {
    const data = await apiGet("/admin/play-pages");
    if (seq !== loadSeq) return; // 期间又切走了 → 本次结果作废
    pages.value = data.pages || [];
    entry = page.value; // 清单 + 当前 (play_id, page_key) → 本页条目
  } catch (e) {
    if (seq === loadSeq) error.value = e.message;
    return;
  }
  if (!entry) {
    // 页面已消失（包被停用/卸载）→ 让侧栏分组同步刷新
    window.dispatchEvent(new Event("worlditor:plays-changed"));
    error.value = "管理页不存在或玩法包已停用";
    return;
  }
  try {
    const headers = {};
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const res = await fetch(entry.component_url, { headers });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const code = await res.text();
    // 管理页组件协议（DESIGN §4.6）：文件 = IIFE，(function(Vue, UiBlock)
    // 形参由加载器注入并执行，返回组件选项（与视图组件一致）
    // eslint-disable-next-line no-new-func
    const factory = new Function(
      "Vue",
      "UiBlock",
      "return (" + code.trim().replace(/;+\s*$/, "") + ")(Vue, UiBlock);"
    );
    const built = factory(Vue, UiBlockRenderer);
    if (seq !== loadSeq) return; // 期间又切走了 → 丢弃旧页面的组件
    comp.value = built;
  } catch (e) {
    if (seq === loadSeq) error.value = "管理页组件加载失败：" + e.message;
  }
}

// 本宿主的身份就是 (play_id, page_key)：两者任一变化都必须重新拉清单条目 +
// 重新加载组件（原先只在 onMounted 里 load()，hashchange 只同步 ref →
// 从管理页 A 切到 B 时 page 变成 B 而 comp 仍是 A 的组件）。
// 首次解析放在 setup 同步执行，immediate 才拿得到真实身份（挂载时只跑一次）。
syncFromHash();
watch([playId, pageKey], load, { immediate: true });

onMounted(() => {
  window.addEventListener("hashchange", syncFromHash);
});
// 切页会重建宿主（AdminPanel 的 key 带 (play_id, page_key)）→ 必须摘监听，
// 否则每次切页都漏一个 hashchange 监听器。
onUnmounted(() => {
  window.removeEventListener("hashchange", syncFromHash);
});
</script>

<style scoped>
.page-host {
  min-height: 400px;
}
.host-head {
  margin-bottom: 12px;
}
.host-head h2 {
  margin: 0 0 4px;
}
.dim {
  color: var(--text-dim);
  font-size: 13px;
}
</style>
