<template>
  <section class="card">
    <h2>账户管理</h2>

    <div class="filters">
      <input
        v-model="q"
        class="search"
        placeholder="搜索用户名…"
        @keyup.enter="load()"
      />
      <select v-model="role" class="filter" @change="load()">
        <option value="">全部角色</option>
        <option value="user">用户</option>
        <option value="admin">管理员</option>
      </select>
      <select v-model="sort" class="filter" @change="load()">
        <option value="created_desc">注册时间 ↓</option>
        <option value="created_asc">注册时间 ↑</option>
        <option value="username">用户名</option>
      </select>
      <button class="btn btn-ghost" @click="load()">查询</button>
      <button class="btn btn-ghost" title="刷新" @click="load(true)">↻</button>
    </div>

    <p v-if="error" class="error-text">{{ error }}</p>

    <table class="table">
      <thead>
        <tr>
          <th>用户名</th>
          <th>角色</th>
          <th>注册时间</th>
          <th>玩家实体</th>
          <th>凭据</th>
          <th></th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="a in rows" :key="a.id" :class="{ on: openId === a.id }">
          <td>
            <button class="link" @click="toggleDetails(a)">{{ a.username }}</button>
          </td>
          <td>
            <span class="tag" :class="a.role === 'admin' ? 'tag-admin' : ''">{{
              a.role === "admin" ? "管理员" : "用户"
            }}</span>
          </td>
          <td>{{ fmtTime(a.created_ts) }}</td>
          <td>
            <template v-if="a.entity">
              {{ a.entity.name }}
              <span class="dim">（{{ a.entity.kind }} · {{ a.entity.map_id }} {{ a.entity.row }},{{ a.entity.col }}）</span>
            </template>
            <span v-else class="dim">—</span>
          </td>
          <td>{{ a.token_count }}</td>
          <td class="ops">
            <button class="btn btn-ghost" @click="toggleRole(a)">
              {{ a.role === "admin" ? "降级" : "升为管理员" }}
            </button>
            <button class="btn btn-danger" @click="removeAccount(a)">删除</button>
          </td>
        </tr>
        <tr v-if="!rows.length && !busy">
          <td colspan="6" class="dim center">没有匹配的账户</td>
        </tr>
      </tbody>
    </table>

    <div class="pager">
      <button class="btn btn-ghost" :disabled="page <= 1" @click="prev">‹ 上一页</button>
      <span class="dim">第 {{ page }} 页 / 共 {{ total }} 个账户</span>
      <button class="btn btn-ghost" :disabled="page * pageSize >= total" @click="next">
        下一页 ›
      </button>
    </div>

    <!-- 详情：凭据明细 -->
    <div v-if="details" class="detail card-inner">
      <h3>
        {{ details.username }} 的凭据
        <button class="btn btn-ghost" @click="openId = null">收起</button>
      </h3>
      <table class="table">
        <thead>
          <tr>
            <th>token</th>
            <th>档位</th>
            <th>类型</th>
            <th>实体</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in detailsTokens" :key="t.token">
            <td><code class="token" :title="t.token">{{ t.token.slice(0, 12) }}…</code></td>
            <td>{{ t.tier }}</td>
            <td>{{ t.kind }}</td>
            <td class="dim">{{ t.entity_id.slice(0, 8) }}…</td>
            <td class="ops">
              <button class="btn btn-danger" @click="revokeToken(t.token)">吊销</button>
            </td>
          </tr>
          <tr v-if="!detailsTokens.length">
            <td colspan="5" class="dim center">无未吊销凭据</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { apiGet, apiPatch, apiDelete } from "../../api";

const PAGE_SIZE = 20;

const q = ref("");
const role = ref("");
const sort = ref("created_desc");
const page = ref(1);
const rows = ref([]);
const total = ref(0);
const busy = ref(false);
const error = ref("");
const openId = ref("");
const detailsTokens = ref([]);

const details = computed(
  () => rows.value.find((a) => a.id === openId.value) || null
);
const pageSize = PAGE_SIZE;

async function load(refresh = false) {
  if (busy.value) return;
  if (refresh) page.value = 1;
  busy.value = true;
  error.value = "";
  try {
    const params = new URLSearchParams({
      q: q.value,
      role: role.value,
      sort: sort.value,
      page: String(page.value),
      page_size: String(PAGE_SIZE),
    });
    const data = await apiGet(`/admin/accounts?${params}`);
    rows.value = data.accounts || [];
    total.value = data.total || 0;
  } catch (e) {
    error.value = e.message.includes("403")
      ? "当前账号无管理员权限"
      : e.message;
  } finally {
    busy.value = false;
  }
}

function fmtTime(ts) {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString();
}

async function toggleDetails(a) {
  if (openId.value === a.id) {
    openId.value = "";
    detailsTokens.value = [];
    return;
  }
  openId.value = a.id;
  try {
    const data = await apiGet(`/admin/accounts/${a.id}/tokens`);
    detailsTokens.value = data.tokens || [];
  } catch (e) {
    error.value = e.message;
  }
}

async function revokeToken(token) {
  if (!confirm("吊销该凭据？对方将立即失效。")) return;
  try {
    await apiDelete(`/admin/tokens/${token}`);
    await toggleDetails(openId.value);
    await load();
  } catch (e) {
    error.value = e.message;
  }
}

async function toggleRole(a) {
  const next = a.role === "admin" ? "user" : "admin";
  if (!confirm(`确认将「${a.username}」${next === "admin" ? "升为管理员" : "降为用户"}？`))
    return;
  try {
    await apiPatch(`/admin/accounts/${a.id}`, { role: next });
    await load();
  } catch (e) {
    error.value = e.message;
  }
}

async function removeAccount(a) {
  if (!confirm(`永久删除用户「${a.username}」？其实体与凭据将一并删除，不可恢复。`))
    return;
  try {
    await apiDelete(`/admin/accounts/${a.id}`);
    await load();
  } catch (e) {
    error.value = e.message;
  }
}

function prev() {
  if (page.value > 1) {
    page.value -= 1;
    load();
  }
}

function next() {
  page.value += 1;
  load();
}

onMounted(load);
</script>

<style scoped>
.filters {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.search {
  flex: 1;
  min-width: 160px;
  padding: 9px 12px;
  border-radius: var(--radius);
  border: 1px solid var(--bg-3);
  background: var(--bg);
  color: var(--text);
}
.filter {
  padding: 9px 10px;
  border-radius: var(--radius);
  border: 1px solid var(--bg-3);
  background: var(--bg);
  color: var(--text);
}
.pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 10px;
}
.detail {
  margin-top: 10px;
}
.card h3 {
  margin: 0 0 10px;
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: space-between;
}
.token {
  font-size: 12px;
}
.dim {
  color: var(--text-dim);
  font-size: 13px;
}
.center {
  text-align: center;
  padding: 14px 0;
}
.link {
  border: none;
  background: transparent;
  color: var(--accent);
  font-size: 14px;
  cursor: pointer;
  padding: 0;
}
.tag {
  border: 1px solid var(--bg-3);
  border-radius: 20px;
  padding: 2px 10px;
  font-size: 12px;
  color: var(--text-dim);
}
.tag-admin {
  color: var(--accent);
  border-color: var(--accent-dim);
}
</style>
