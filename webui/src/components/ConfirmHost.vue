<template>
  <!-- 全局确认层宿主：App.vue 挂一次，页面用 askConfirm() 调用 -->
  <div v-if="confirmState.open" class="modal-mask" @click.self="settleConfirm(false)">
    <div class="modal confirm" @keydown.esc="settleConfirm(false)">
      <h3 :class="{ danger: confirmState.danger }">{{ confirmState.title }}</h3>
      <p v-if="confirmState.text" class="text">{{ confirmState.text }}</p>
      <p v-if="confirmState.detail" class="detail">{{ confirmState.detail }}</p>
      <div class="ops">
        <button
          ref="okBtn"
          class="btn"
          :class="{ 'btn-danger': confirmState.danger }"
          @click="settleConfirm(true)"
        >
          {{ confirmState.confirmText }}
        </button>
        <button class="btn btn-ghost" @click="settleConfirm(false)">
          {{ confirmState.cancelText }}
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { confirmState, settleConfirm } from "../confirm";

const okBtn = ref(null);

// 打开即聚焦确认按钮：Enter 确认、Esc 取消都是键盘默认行为
watch(
  () => confirmState.open,
  (open) => {
    if (open) nextTick(() => okBtn.value?.focus());
  }
);

function onKey(e) {
  if (!confirmState.open) return;
  if (e.key === "Escape") settleConfirm(false);
}
onMounted(() => window.addEventListener("keydown", onKey));
onUnmounted(() => window.removeEventListener("keydown", onKey));
</script>

<style scoped>
.confirm {
  max-width: 420px;
}
.confirm h3 {
  margin: 0 0 8px;
}
.confirm h3.danger {
  color: var(--danger);
}
.text {
  margin: 0 0 6px;
  font-size: 14px;
  line-height: 1.5;
}
.detail {
  margin: 0 0 10px;
  font-size: 13px;
  color: var(--text-dim);
  line-height: 1.5;
}
.ops {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}
</style>
