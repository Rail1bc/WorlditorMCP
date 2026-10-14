<template>
  <!-- 单个声明字段的控件（schema 驱动）。顶层「声明字段」区与每个组件块里都要用，
       所以抽成一个哑组件：值由 FieldForm 统一持有，这里只负责渲染 + 回抛新值。
       （旧版把这段 markup 写在 FieldForm 里，组件化后同一字段在两处出现，
        复制两份必然漂移。） -->
  <input
    v-if="field.type === 'str'"
    :value="modelValue"
    @input="emit('update:modelValue', $event.target.value)"
    @change="emit('commit')"
  />
  <input
    v-else-if="field.type === 'int' || field.type === 'float'"
    :value="modelValue"
    type="number"
    :step="field.type === 'float' ? 'any' : 1"
    @input="emit('update:modelValue', $event.target.value === '' ? '' : Number($event.target.value))"
    @change="emit('commit')"
  />
  <input
    v-else-if="field.type === 'bool'"
    type="checkbox"
    :checked="Boolean(modelValue)"
    @change="
      emit('update:modelValue', $event.target.checked);
      emit('commit');
    "
  />
  <textarea
    v-else
    :value="modelValue"
    rows="2"
    placeholder="JSON"
    @input="emit('update:modelValue', $event.target.value)"
    @change="emit('commit')"
  ></textarea>
</template>

<script setup>
defineProps({
  field: { type: Object, required: true }, // {name,label,type,default?,source,play_id}
  modelValue: { type: [String, Number, Boolean], default: "" }, // json 类型传 JSON 文本
});
const emit = defineEmits(["update:modelValue", "commit"]);
</script>

<style scoped>
/* 控件自带样式：父组件的 scoped 样式到不了子组件内部（原来的规则在 FieldForm 里） */
input:not([type="checkbox"]),
textarea {
  padding: 4px 6px;
  border-radius: 6px;
  border: 1px solid var(--bg-3);
  background: var(--bg);
  color: var(--text);
  font-size: 13px;
  min-width: 120px;
}
textarea {
  font-family: ui-monospace, monospace;
  font-size: 12px;
}
input[type="checkbox"] {
  align-self: flex-start;
}
</style>
