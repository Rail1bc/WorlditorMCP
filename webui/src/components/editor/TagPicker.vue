<template>
  <!-- 标签组合器（D18/D19/R6）：勾选已声明标签，也允许手输未注册标签 -->
  <div class="tag-picker">
    <span class="label">标签</span>
    <span v-for="t in preset" :key="`p-${t}`" class="chip locked" :title="`类型「${kind}」预设的标签（D18），不能在实例上摘除`">
      {{ t }} <span class="src">来自类型</span>
    </span>
    <span v-for="(t, i) in modelValue" :key="`v-${t}`" class="chip" :class="{ unknown: !specOf(t) }">
      {{ labelOf(t) }}
      <button class="x" :title="specOf(t) ? '移除标签' : '未注册的标签：不贡献任何能力'" @click="remove(i)">
        ×
      </button>
    </span>
    <select class="mini" :value="''" @change="add($event.target.value)">
      <option value="">＋ 已声明标签…</option>
      <option v-for="k in available" :key="k.tag" :value="k.tag">
        {{ k.label }}（{{ k.tag }}{{ k.implicit ? " · 类型" : "" }}）
      </option>
    </select>
    <input
      v-model="freeText"
      class="mini"
      placeholder="手输未注册标签（回车添加）"
      @keydown.enter.prevent="addFree"
    />
  </div>
</template>

<script setup>
import { computed, ref } from "vue";

const props = defineProps({
  modelValue: { type: Array, default: () => [] },
  kinds: { type: Array, default: () => [] },
  preset: { type: Array, default: () => [] },
  kind: { type: String, default: "" },
});
const emit = defineEmits(["update:modelValue"]);

const freeText = ref("");

function specOf(tag) {
  return props.kinds.find((k) => k.tag === tag) || null;
}
function labelOf(tag) {
  const spec = specOf(tag);
  if (!spec) return tag;
  return spec.label && spec.label !== tag ? `${spec.label}（${tag}）` : tag;
}

const available = computed(() =>
  props.kinds.filter(
    (k) => !props.modelValue.includes(k.tag) && !props.preset.includes(k.tag) && k.tag !== props.kind
  )
);

function add(tag) {
  if (!tag || props.modelValue.includes(tag)) return;
  emit("update:modelValue", [...props.modelValue, tag]);
}
function addFree() {
  const tag = freeText.value.trim();
  freeText.value = "";
  add(tag);
}
function remove(index) {
  const next = [...props.modelValue];
  next.splice(index, 1);
  emit("update:modelValue", next);
}
</script>

<style scoped>
.tag-picker {
  display: flex;
  align-items: center;
  gap: 5px;
  flex-wrap: wrap;
  margin: 4px 0;
}
.label {
  font-size: 12px;
  color: var(--text-dim);
}
.chip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  font-size: 12px;
  border: 1px solid var(--bg-3);
  border-radius: 999px;
  padding: 0 8px;
  color: var(--text);
}
.chip.unknown {
  border-color: var(--danger);
  color: var(--danger);
}
.chip.locked {
  color: var(--text-dim);
  border-style: dashed;
}
.chip .src {
  font-size: 10px;
  color: var(--text-dim);
}
.x {
  border: none;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font-size: 12px;
  padding: 0;
}
.x:hover {
  color: var(--danger);
}
.mini {
  padding: 4px 6px;
  border-radius: 6px;
  border: 1px solid var(--bg-3);
  background: var(--bg);
  color: var(--text);
  font-size: 12px;
  max-width: 200px;
}
</style>
