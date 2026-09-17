<template>
  <!-- 地块上的实体（从可视化地图选格后直接管这一格） -->
  <div class="tile-entities">
    <h4>
      本格实体（{{ entities.length }}）
      <button class="mini-btn" @click="emit('manage')">在地块外管理 ›</button>
    </h4>
    <p v-if="!entities.length" class="dim">这一格上还没有实体（用右侧「实体」视图放置）。</p>
    <div v-for="e in entities" :key="e.id" class="row">
      <span class="name">{{ e.name }}</span>
      <code class="dim">{{ e.kind }}</code>
      <span v-for="t in e.tags" :key="t" class="chip">{{ t }}</span>
      <span class="grow" />
      <button class="mini-btn" title="在实体视图里打开详情" @click="emit('open', e)">编辑</button>
      <button class="mini-btn danger" @click="emit('remove', e)">删除</button>
    </div>
  </div>
</template>

<script setup>
defineProps({
  entities: { type: Array, default: () => [] },
});
const emit = defineEmits(["open", "remove", "manage"]);
</script>

<style scoped>
.tile-entities {
  border-top: 1px solid var(--bg-3);
  margin-top: 8px;
  padding-top: 6px;
}
h4 {
  margin: 2px 0 4px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 6px;
}
.row {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 3px 0;
  font-size: 13px;
  flex-wrap: wrap;
}
.name {
  font-weight: 600;
}
.grow {
  flex: 1;
}
.chip {
  font-size: 11px;
  border: 1px solid var(--bg-3);
  border-radius: 999px;
  padding: 0 6px;
  color: var(--text-dim);
}
.mini-btn {
  border: none;
  background: transparent;
  color: var(--text-dim);
  font-size: 12px;
  cursor: pointer;
  padding: 2px 4px;
  border-radius: 6px;
}
.mini-btn:hover {
  color: var(--accent);
  background: var(--bg-3);
}
.mini-btn.danger:hover {
  color: var(--danger);
}
.dim {
  color: var(--text-dim);
  font-size: 12px;
}
</style>
