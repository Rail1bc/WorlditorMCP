<template>
  <!-- 模板清单（D22：地块 / 实体两类，玩法包注册 + 管理端本地） -->
  <div class="templates">
    <h3>
      模板（{{ templates.length }}）
      <span class="dim">地块 {{ locationTemplates.length }} · 实体 {{ entityTemplates.length }}</span>
    </h3>
    <p class="dim">
      玩法包注册的模板随包加载/卸载；「本地」是管理员存在库里的，两者合并成一个列表。
    </p>
    <table class="table">
      <thead>
        <tr>
          <th>名称</th>
          <th>类别</th>
          <th>来源</th>
          <th>负载</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="t in templates" :key="t.id">
          <td>{{ t.name }}</td>
          <td>{{ t.scope === "location" ? "地块" : "实体" }}</td>
          <td>
            <span class="chip" :class="{ play: t.source === 'play' }">
              {{ t.source === "play" ? `玩法包 ${t.play_id}` : "本地（可删）" }}
            </span>
          </td>
          <td class="dim"><code>{{ summary(t) }}</code></td>
          <td class="ops">
            <button v-if="t.source !== 'play'" class="mini-btn danger" @click="emit('remove', t)">
              删除
            </button>
          </td>
        </tr>
        <tr v-if="!templates.length">
          <td colspan="5" class="dim">还没有模板（在下面把当前地块/实体存为模板）。</td>
        </tr>
      </tbody>
    </table>
  </div>
</template>

<script setup>
import { computed } from "vue";

const props = defineProps({
  templates: { type: Array, default: () => [] },
});
const emit = defineEmits(["remove"]);

const locationTemplates = computed(() => props.templates.filter((t) => t.scope === "location"));
const entityTemplates = computed(() => props.templates.filter((t) => t.scope === "entity"));

function summary(t) {
  const data = t.data || {};
  if (t.scope === "location") {
    const paths = Object.values(data.connections || {}).reduce(
      (n, slot) => n + (slot.enabled ? (slot.paths || []).length : 0),
      0
    );
    return `${data.name || "（无名称）"} · 出口 ${paths}`;
  }
  const tags = data.tags?.length ? ` · 标签 ${data.tags.join("/")}` : "";
  return `${data.kind || "?"}${tags}`;
}
</script>

<style scoped>
.templates {
  margin-top: 14px;
  border-top: 1px solid var(--bg-3);
  padding-top: 10px;
}
h3 {
  margin: 4px 0;
  display: flex;
  gap: 10px;
  align-items: baseline;
}
.chip {
  font-size: 11px;
  border: 1px solid var(--bg-3);
  border-radius: 999px;
  padding: 0 6px;
  color: var(--text-dim);
}
.chip.play {
  color: var(--accent);
  border-color: var(--accent);
}
.mini-btn {
  border: none;
  background: transparent;
  color: var(--text-dim);
  font-size: 12px;
  cursor: pointer;
  padding: 2px 4px;
}
.mini-btn.danger:hover {
  color: var(--danger);
}
.dim {
  color: var(--text-dim);
  font-size: 12px;
}
</style>
