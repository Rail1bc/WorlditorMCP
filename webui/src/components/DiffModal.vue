<template>
  <!-- 保存前差异预览宿主（App.vue 挂一次；页面用 askDiff() 调用） -->
  <div v-if="diffState.open" class="modal-mask" @click.self="settleDiff(false)">
    <div class="modal diff">
      <h3>{{ diffState.title }}</h3>
      <p v-if="diffState.detail" class="detail">{{ diffState.detail }}</p>
      <div class="changes">
        <div v-for="(c, i) in diffState.changes" :key="i" class="change">
          <div class="label">{{ c.label }}</div>
          <div class="values">
            <del>{{ showValue(c.before) }}</del>
            <span class="arrow">→</span>
            <ins>{{ showValue(c.after) }}</ins>
          </div>
        </div>
      </div>
      <div class="ops">
        <button ref="okBtn" class="btn" @click="settleDiff(true)">
          {{ diffState.confirmText }}
        </button>
        <button class="btn btn-ghost" @click="settleDiff(false)">取消</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { diffState, settleDiff, showValue } from "../diff";

const okBtn = ref(null);
watch(
  () => diffState.open,
  (open) => {
    if (open) nextTick(() => okBtn.value?.focus());
  }
);

function onKey(e) {
  if (!diffState.open) return;
  if (e.key === "Escape") settleDiff(false);
}
onMounted(() => window.addEventListener("keydown", onKey));
onUnmounted(() => window.removeEventListener("keydown", onKey));
</script>

<style scoped>
.diff {
  max-width: 620px;
  max-height: 80vh;
  overflow: auto;
}
.diff h3 {
  margin: 0 0 6px;
}
.detail {
  margin: 0 0 10px;
  font-size: 13px;
  color: var(--text-dim);
  line-height: 1.5;
}
.changes {
  display: flex;
  flex-direction: column;
  gap: 8px;
  border-top: 1px solid var(--bg-3);
  padding-top: 8px;
}
.change {
  font-size: 13px;
}
.change .label {
  color: var(--text-dim);
  font-size: 12px;
  margin-bottom: 2px;
}
.values {
  display: flex;
  gap: 8px;
  align-items: flex-start;
  flex-wrap: wrap;
  line-height: 1.5;
  word-break: break-all;
}
del {
  color: var(--danger);
  text-decoration: line-through;
  opacity: 0.85;
}
ins {
  color: var(--accent);
  text-decoration: none;
  font-weight: 600;
}
.arrow {
  color: var(--text-dim);
}
.ops {
  display: flex;
  gap: 8px;
  margin-top: 14px;
}
</style>
