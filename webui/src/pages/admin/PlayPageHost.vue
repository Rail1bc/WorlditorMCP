<template>
  <section class="card page-host">
    <header class="host-head">
      <div>
        <h2>{{ icon }} {{ title }}</h2>
        <p class="dim">
          <code>{{ playId }} · {{ pageKey }}</code>
        </p>
      </div>
      <button class="btn btn-ghost" @click="back">← 返回玩法包</button>
    </header>

    <p v-if="error" class="error-text">{{ error }}</p>
    <component
      v-if="comp"
      :is="comp"
      :page="page"
      :key="playId + '/' + pageKey"
    />
    <p v-else class="dim">加载管理页组件…</p>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import * as Vue from "vue";
import { apiGet, getToken } from "../../api";
import UiBlockRenderer from "../../components/UiBlockRenderer.vue";

// hash: #/admin/pages/{play_id}/{page_key}
const playId = ref("");
const pageKey = ref("");
const pages = ref([]);
const comp = ref(null);
const error = ref("");

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

function back() {
  location.hash = "#/admin/plays";
}

async function load() {
  error.value = "";
  try {
    const data = await apiGet("/admin/play-pages");
    pages.value = data.pages || [];
  } catch (e) {
    error.value = e.message;
    return;
  }
  if (!page.value) {
    error.value = "管理页不存在或玩法包已停用";
    return;
  }
  try {
    const headers = {};
    const token = getToken();
    if (token) headers["Authorization"] = `Bearer ${token}`;
    const res = await fetch(page.value.component_url, { headers });
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
    comp.value = factory(Vue, UiBlockRenderer);
  } catch (e) {
    error.value = "管理页组件加载失败：" + e.message;
  }
}

onMounted(async () => {
  syncFromHash();
  window.addEventListener("hashchange", syncFromHash);
  await load();
});
</script>

<style scoped>
.page-host {
  min-height: 400px;
}
.host-head {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
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
