<template>
  <!-- 组件选择器（D41）：从 `kinds` 里勾选**已声明**的组件，也允许手输组件键。
       组件键 = `source:name` 信封——能力 = 组件的存在，勾上就是给它这个能力；
       已经带上、但没有任何声明的键（虚构组件）照样显示，标红可删。 -->
  <div class="component-picker">
    <span class="label">组件</span>
    <span
      v-for="(key, i) in modelValue"
      :key="`v-${key}`"
      class="chip"
      :class="{ unknown: !specOf(key) }"
      :title="
        specOf(key)
          ? `已声明：${specOf(key).label || key}`
          : '虚构组件：没有声明，不贡献能力（允许存在）'
      "
    >
      {{ labelOf(key) }}
      <span v-if="specOf(key)" class="src">来源 {{ specOf(key).source }}</span>
      <button
        class="x"
        :title="specOf(key) ? '移除组件（它的数据也一起删）' : '虚构组件：没有声明，不贡献任何能力'"
        @click="remove(i)"
      >
        ×
      </button>
    </span>
    <select class="mini" :value="''" @change="add($event.target.value)">
      <option value="">＋ 已声明组件…</option>
      <option v-for="k in available" :key="k.key" :value="k.key">
        {{ k.label }}（{{ k.key }} · 来源 {{ k.source }}）
      </option>
    </select>
    <input
      v-model="freeText"
      class="mini"
      :placeholder="freePlaceholder"
      @keydown.enter.prevent="addFree"
    />
    <span v-if="freeError" class="bad">{{ freeError }}</span>
  </div>
</template>

<script setup>
import { computed, ref } from "vue";

const props = defineProps({
  modelValue: { type: Array, default: () => [] }, // 组件键列表
  kinds: { type: Array, default: () => [] }, // 组件声明清单（{key, source, name, label, …}）
});
const emit = defineEmits(["update:modelValue"]);

// 组件键信封：`source:name`，两段都只允许字母/数字/下划线/点/连字符
// （与内核 split_component_key 同一口径）
const COMPONENT_RE = /^[A-Za-z0-9_.-]+:[A-Za-z0-9_.-]+$/;
const LOCAL = "local";

const freeText = ref("");
const freeError = ref("");

const freePlaceholder = computed(() => `手输组件键（如 stat → ${LOCAL}:stat，回车添加）`);

function specOf(key) {
  return props.kinds.find((k) => k.key === key) || null;
}

function labelOf(key) {
  const spec = specOf(key);
  if (!spec) return key;
  return spec.label && spec.label !== key ? `${spec.label}（${key}）` : key;
}

const available = computed(() => props.kinds.filter((k) => !props.modelValue.includes(k.key)));

function add(key) {
  if (!key || props.modelValue.includes(key)) return;
  freeError.value = "";
  emit("update:modelValue", [...props.modelValue, key]);
}

/** 自由输入归一：不含冒号 → 补 `local:` 前缀；再按信封校验（不合法就不发）。 */
function addFree() {
  freeError.value = "";
  const text = freeText.value.trim();
  if (!text) return;
  const full = text.includes(":") ? text : `${LOCAL}:${text}`;
  if (!COMPONENT_RE.test(full)) {
    freeError.value = `组件键不合法：${full}（只允许字母/数字/下划线/点/连字符，且必须是「来源:名字」）`;
    return;
  }
  freeText.value = "";
  add(full);
}

function remove(index) {
  const next = [...props.modelValue];
  next.splice(index, 1);
  emit("update:modelValue", next);
}
</script>

<style scoped>
.component-picker {
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
.bad {
  color: var(--danger);
  font-size: 12px;
}
</style>
