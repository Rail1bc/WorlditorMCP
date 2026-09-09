<template>
  <section class="card">
    <h2>邀请码</h2>
    <p class="dim">邀请模式下新用户注册需要邀请码；本页生成 / 吊销（管理面暂不扩展）</p>

    <div class="ops-row">
      <button class="btn" @click="makeCodes(1)">生成 1 个</button>
      <button class="btn" @click="makeCodes(5)">生成 5 个</button>
      <button class="btn" @click="makeCodes(10)">生成 10 个</button>
      <button class="btn btn-ghost" @click="load">↻</button>
    </div>

    <div v-if="fresh.length" class="fresh">
      <span class="dim">新生成（请复制分发）：</span>
      <code v-for="c in fresh" :key="c" class="fresh-code">{{ c }}</code>
    </div>

    <p v-if="error" class="error-text">{{ error }}</p>

    <table class="table">
      <thead>
        <tr>
          <th>邀请码</th>
          <th>状态</th>
          <th>生成时间</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="c in codes" :key="c.code">
          <td><code>{{ c.code }}</code></td>
          <td>
            <span class="tag" :class="{ 'tag-off': c.used }">{{
              c.used ? "已使用/吊销" : "未使用"
            }}</span>
          </td>
          <td class="dim">{{ fmtTime(c.created_ts) }}</td>
          <td class="ops">
            <button v-if="!c.used" class="btn btn-danger" @click="revoke(c.code)">
              吊销
            </button>
          </td>
        </tr>
        <tr v-if="!codes.length">
          <td colspan="4" class="dim center">暂无邀请码</td>
        </tr>
      </tbody>
    </table>
  </section>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { apiGet, apiPost, apiDelete } from "../../api";

const codes = ref([]);
const fresh = ref([]);
const error = ref("");

async function load() {
  error.value = "";
  try {
    const data = await apiGet("/admin/accounts");
    codes.value = data.invite_codes || [];
  } catch (e) {
    error.value = e.message;
  }
}

async function makeCodes(count) {
  try {
    const data = await apiPost("/admin/invite-codes", { count });
    fresh.value = data.data?.codes || [];
    await load();
  } catch (e) {
    error.value = e.message;
  }
}

async function revoke(code) {
  if (!confirm(`吊销邀请码 ${code}？`)) return;
  try {
    await apiDelete(`/admin/invite-codes/${code}`);
    await load();
  } catch (e) {
    error.value = e.message;
  }
}

function fmtTime(ts) {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString();
}

onMounted(load);
</script>

<style scoped>
.ops-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.fresh {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  padding: 10px 12px;
  border-radius: var(--radius);
  background: var(--bg-3);
  margin-bottom: 10px;
  font-size: 13px;
}
.fresh-code {
  border: 1px dashed var(--accent-dim);
  border-radius: 6px;
  padding: 2px 8px;
}
.tag {
  border: 1px solid var(--bg-3);
  border-radius: 20px;
  padding: 2px 10px;
  font-size: 12px;
  color: var(--accent);
}
.tag-off {
  color: var(--text-dim);
}
.dim {
  color: var(--text-dim);
  font-size: 13px;
}
.center {
  text-align: center;
  padding: 14px 0;
}
</style>
