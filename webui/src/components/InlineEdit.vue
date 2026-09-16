<template>
  <!-- 内联重命名：常态是"文本 + ✎"，点击原地变输入框（替代原生 prompt） -->
  <span class="inline-edit">
    <template v-if="!editing">
      <span class="text" :title="value">{{ value || placeholder }}</span>
      <button class="pencil" :title="'重命名'" @click.stop="start">✎</button>
    </template>
    <template v-else>
      <input
        ref="inputEl"
        v-model="draft"
        :placeholder="placeholder"
        @keydown.enter.prevent="commit"
        @keydown.esc.prevent="cancel"
        @blur="commit"
        @click.stop
      />
      <button class="pencil ok" title="保存" @mousedown.prevent @click.stop="commit">✓</button>
      <button class="pencil" title="取消" @mousedown.prevent @click.stop="cancel">×</button>
    </template>
  </span>
</template>

<script setup>
import { nextTick, ref } from "vue";

const props = defineProps({
  value: { type: String, default: "" },
  placeholder: { type: String, default: "（未命名）" },
});
const emit = defineEmits(["save"]);

const editing = ref(false);
const draft = ref("");
const inputEl = ref(null);

function start() {
  draft.value = props.value;
  editing.value = true;
  nextTick(() => {
    inputEl.value?.focus();
    inputEl.value?.select();
  });
}

function commit() {
  if (!editing.value) return; // blur 与 enter 双触发防抖
  const next = draft.value.trim();
  editing.value = false;
  if (next && next !== props.value) emit("save", next);
}

function cancel() {
  editing.value = false;
}
</script>

<style scoped>
.inline-edit {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  min-width: 0;
}
.text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 260px;
}
.pencil {
  border: none;
  background: transparent;
  color: var(--text-dim);
  cursor: pointer;
  font-size: 12px;
  padding: 0 2px;
  opacity: 0;
}
.inline-edit:hover .pencil {
  opacity: 1;
}
.pencil.ok {
  color: var(--accent);
  opacity: 1;
}
.inline-edit input {
  padding: 3px 6px;
  border-radius: 6px;
  border: 1px solid var(--accent);
  background: var(--bg);
  color: var(--text);
  font-size: 13px;
  min-width: 140px;
}
</style>
