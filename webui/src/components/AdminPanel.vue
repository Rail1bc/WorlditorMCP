<template>
  <div class="admin-panel">
    <header class="app-header">
      <span class="brand">🛠 worlditor 管理台</span>
      <button class="logout-btn" title="退出登录" @click="doLogout">⎋</button>
    </header>

    <main class="admin-main">
      <!-- 账户管理 -->
      <section class="admin-card">
        <h3>账户管理</h3>
        <table class="admin-table">
          <thead>
            <tr>
              <th>用户名</th>
              <th>角色</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in accounts" :key="a.id">
              <td>{{ a.username }}</td>
              <td>{{ a.role }}</td>
              <td class="admin-actions">
                <button class="btn" @click="toggleRole(a)">{{ a.role === "admin" ? "降级" : "升为管理员" }}</button>
                <button class="btn btn-danger" @click="removeAccount(a)">删除</button>
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <!-- 玩法包 -->
      <section class="admin-card">
        <h3>玩法包</h3>
        <table class="admin-table">
          <tbody>
            <tr v-for="p in plays" :key="p.play_id">
              <td>{{ p.name || p.play_id }}</td>
              <td>{{ p.version }}</td>
              <td>{{ p.status }}</td>
              <td class="admin-actions">
                <button v-if="p.status === 'disabled'" class="btn" @click="enablePlay(p.play_id)">启用</button>
                <button v-else-if="p.status === 'loaded'" class="btn" @click="disablePlay(p.play_id)">停用</button>
              </td>
            </tr>
          </tbody>
        </table>
      </section>

      <!-- 邀请码（邀请模式） -->
      <section class="admin-card">
        <h3>邀请码</h3>
        <div class="admin-actions">
          <button class="btn" @click="makeCodes(1)">生成 1 个</button>
          <button class="btn" @click="makeCodes(5)">生成 5 个</button>
        </div>
        <ul class="admin-codes">
          <li v-for="c in inviteCodes" :key="c.code">
            <code>{{ c.code }}</code>
            <span>{{ c.used ? "已失效" : "未使用" }}</span>
            <button v-if="!c.used" class="btn" @click="revokeCode(c.code)">吊销</button>
          </li>
        </ul>
      </section>

      <p v-if="error" class="error-text">{{ error }}</p>
    </main>
  </div>
</template>

<script setup>
import { onMounted, ref } from "vue";
import { getToken, setToken } from "../api";
import { store } from "../store";

const accounts = ref([]);
const plays = ref([]);
const inviteCodes = ref([]);
const error = ref("");
const busy = ref(false);

async function authFetch(path, opts = {}) {
  const resp = await fetch(path, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${getToken()}`,
      ...(opts.headers || {}),
    },
  });
  if (resp.status === 401) {
    setToken("");
    store.token = "";
    error.value = "凭据已失效，请重新登录";
    throw new Error(error.value);
  }
  if (!resp.ok) {
    let message = `请求失败（${resp.status}）`;
    try {
      const data = await resp.json();
      if (data.error) message = data.error;
    } catch {
      /* ignore */
    }
    error.value = message;
    throw new Error(message);
  }
  return resp.json();
}

async function refresh() {
  if (busy.value) return;
  busy.value = true;
  error.value = "";
  // 各区块独立加载：一个失败不影响其他面板（避免整表空白）
  const [acc, pl] = await Promise.allSettled([
    authFetch("/admin/accounts"),
    authFetch("/admin/plays"),
  ]);
  if (acc.status === "rejected") {
    error.value = acc.reason.message.includes("403")
      ? "当前账号无管理员权限，请用管理员账号登录管理端"
      : acc.reason.message;
  } else {
    accounts.value = acc.value.accounts || [];
    inviteCodes.value = acc.value.invite_codes || [];
  }
  if (pl.status === "rejected") {
    error.value = error.value || pl.reason.message;
  } else {
    plays.value = pl.value.plays || [];
  }
  busy.value = false;
}

async function toggleRole(a) {
  try {
    await authFetch(`/admin/accounts/${a.id}`, {
      method: "PATCH",
      body: JSON.stringify({ role: a.role === "admin" ? "user" : "admin" }),
    });
    await refresh();
  } catch {
    /* ignore */
  }
}

async function removeAccount(a) {
  if (!confirm(`永久删除用户「${a.username}」（不可恢复）？`)) return;
  try {
    await authFetch(`/admin/accounts/${a.id}`, { method: "DELETE" });
    await refresh();
  } catch {
    /* ignore */
  }
}

async function enablePlay(id) {
  try {
    await authFetch(`/admin/plays/${id}/enable`, { method: "POST" });
    await refresh();
  } catch {
    /* ignore */
  }
}

async function disablePlay(id) {
  try {
    await authFetch(`/admin/plays/${id}/disable`, { method: "POST" });
    await refresh();
  } catch {
    /* ignore */
  }
}

async function makeCodes(count) {
  try {
    await authFetch("/admin/invite-codes", {
      method: "POST",
      body: JSON.stringify({ count }),
    });
    await refresh();
  } catch {
    /* ignore */
  }
}

async function revokeCode(code) {
  try {
    await authFetch(`/admin/invite-codes/${code}`, { method: "DELETE" });
    await refresh();
  } catch {
    /* ignore */
  }
}

function doLogout() {
  setToken("");
  store.token = "";
  location.hash = "#/auth";
}

onMounted(refresh);
</script>

<style scoped>
.admin-panel {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}
.admin-main {
  max-width: 760px;
  width: 100%;
  margin: 0 auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.admin-card {
  border: 1px solid #e2e2e2;
  border-radius: 10px;
  padding: 14px 16px;
  background: #fff;
}
.admin-card h3 {
  margin: 0 0 10px;
  font-size: 15px;
}
.admin-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.admin-table th,
.admin-table td {
  text-align: left;
  padding: 6px 8px;
  border-bottom: 1px solid #eee;
}
.admin-actions {
  display: flex;
  gap: 6px;
  justify-content: flex-end;
}
.btn-danger {
  color: #b00020;
}
.admin-codes {
  list-style: none;
  padding: 0;
  margin: 8px 0 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  font-size: 13px;
}
.admin-codes li {
  display: flex;
  align-items: center;
  gap: 8px;
}
.error-text {
  color: #b00020;
  font-size: 13px;
}
</style>
