<template>
  <!-- 世界新建 / 设置（侧栏世界下拉的 ＋ 与 ⚙ 共用） -->
  <div class="modal-mask" @click.self="$emit('close')">
    <div class="modal">
      <h3>{{ form.id0 ? "世界设置" : "新建世界" }}</h3>
      <label class="field">
        世界 id（创建后不可改）
        <input v-model="form.id" :disabled="!!form.id0" placeholder="如 pvp" />
      </label>
      <label class="field">
        名称
        <input v-model="form.name" placeholder="如 竞技场" />
      </label>
      <label class="field">
        描述
        <textarea v-model="form.desc" rows="2" placeholder="写给管理员自己看"></textarea>
      </label>
      <p class="dim">
        玩法包启停按世界配置——在「玩法包」页里逐个开关（本弹层只改世界本身）。
      </p>
      <div class="ops">
        <button class="btn" :disabled="busy" @click="save">
          {{ form.id0 ? "保存" : "创建并进入" }}
        </button>
        <button class="btn btn-ghost" @click="$emit('close')">取消</button>
        <button v-if="form.id0" class="btn btn-danger" @click="remove">
          删除世界
        </button>
      </div>
      <p v-if="error" class="error-text">{{ error }}</p>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from "vue";
import { apiPost, apiPatch, apiDelete } from "../api";
import { askConfirm } from "../confirm";

const props = defineProps({
  world: { type: Object, default: null }, // null = 新建
});
const emit = defineEmits(["close", "saved"]);

const form = reactive({
  id: props.world?.id || "",
  id0: props.world?.id || "", // 非空 = 编辑模式
  name: props.world?.name || "",
  desc: props.world?.desc || "",
});
const busy = ref(false);
const error = ref("");

async function save() {
  error.value = "";
  busy.value = true;
  try {
    if (form.id0) {
      await apiPatch(`/admin/worlds/${encodeURIComponent(form.id0)}`, {
        name: form.name,
        desc: form.desc,
      });
      emit("saved", form.id0);
    } else {
      await apiPost("/admin/worlds", {
        id: form.id,
        name: form.name,
        desc: form.desc,
      });
      emit("saved", form.id);
    }
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}

async function remove() {
  const ok = await askConfirm({
    title: "删除世界",
    danger: true,
    text: `删除世界「${form.name || form.id0}」？`,
    detail: "其组织树与地图归属一并删除（地图本身保留，变成未归属）。世界仍有地图归属时会被拒绝。",
  });
  if (!ok) return;
  error.value = "";
  busy.value = true;
  try {
    await apiDelete(`/admin/worlds/${encodeURIComponent(form.id0)}`);
    emit("saved", "");
  } catch (e) {
    error.value = e.message;
  } finally {
    busy.value = false;
  }
}
</script>

<style scoped>
.dim {
  color: var(--text-dim);
  font-size: 13px;
  margin: 0;
}
</style>
