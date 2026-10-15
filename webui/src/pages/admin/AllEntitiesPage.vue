<template>
  <section class="card">
    <h2>全部实体</h2>
    <p class="dim lead">
      跨地图的实体治理视角。不在世界上的实体只在这里看得到（v2 / D36：位置是可选的
      <code>core:position</code> 组件——玩家下线、物品在容器里、尚未投放的 NPC 都是合法状态，
      地图视角按坐标裁剪，一个都看不见）。
    </p>

    <div class="filters">
      <div class="seg">
        <button
          v-for="opt in PRESENCE"
          :key="opt.key"
          :class="{ on: presence === opt.key }"
          @click="presence = opt.key"
        >
          {{ opt.title }}
        </button>
      </div>
      <span class="grow" />
      <span class="dim">
        共 {{ rows.length }} 个实体 · 不在世界上 {{ absentCount }} 个
      </span>
      <button class="btn btn-ghost" title="刷新" @click="load()">↻</button>
    </div>

    <p v-if="error" class="error-text">{{ error }}</p>

    <EntityManager
      ref="entityManager"
      :entities="shown"
      :kinds="kinds"
      :entity-templates="templates.filter((t) => t.scope === 'entity')"
      :allow-absent="true"
      @create="createEntity"
      @update="updateEntity"
      @remove="removeEntity"
      @save-template="saveEntityTemplate"
      @locate="locateEntity"
    />
  </section>
</template>

<script setup>
import { computed, onMounted, ref } from "vue";
import { apiDelete, apiGet, apiPatch, apiPost } from "../../api";
import { askConfirm } from "../../confirm";
import { askDiff, diffFields } from "../../diff";
import {
  contentComponents,
  entityDesc,
  entityName,
  entityPosition,
  withoutPosition,
} from "../../entity.js";
import EntityManager from "../../components/editor/EntityManager.vue";

const PRESENCE = [
  { key: "all", title: "全部" },
  { key: "in", title: "在世界" },
  { key: "out", title: "不在世界" },
];

const rows = ref([]);
const kinds = ref([]);
const templates = ref([]);
const presence = ref("all");
const error = ref("");
const entityManager = ref(null);

const absentCount = computed(() => rows.value.filter((e) => !hasPos(e)).length);

const shown = computed(() => {
  if (presence.value === "in") return rows.value.filter(hasPos);
  if (presence.value === "out") return rows.value.filter((e) => !hasPos(e));
  return rows.value;
});

// 位置判定的唯一入口在 entity.js（这里只用它，不自己读 e.row）
function hasPos(e) {
  return entityPosition(e) !== null;
}

async function load() {
  error.value = "";
  try {
    const [data, kindData, tmpl] = await Promise.all([
      apiGet("/admin/entities"),
      apiGet("/admin/kinds"),
      apiGet("/admin/templates"),
    ]);
    rows.value = data.entities || [];
    kinds.value = kindData.kinds || [];
    templates.value = tmpl.templates || [];
  } catch (e) {
    error.value = e.message;
  }
}

async function createEntity(payload) {
  // 不带坐标 = 造一个不在世界上的实体（后端按"全有或全无"判定，半截坐标直接报错）
  try {
    await apiPost("/admin/entities", payload);
    await load();
  } catch (e) {
    error.value = e.message;
    entityManager.value?.setError(e.message);
  }
}

/** 组件字典就地拍平成 `components.<组件名>` 键（差异预览按组件逐个对比）。 */
function componentRows(components) {
  const out = {};
  for (const [name, data] of Object.entries(components || {})) {
    out[`components.${name}`] = data;
  }
  return out;
}

async function updateEntity(entity, patch) {
  const afterComponents = patch.components ?? entity.components ?? {};
  const before = {
    name: entityName(entity),
    desc: entityDesc(entity),
    ...componentRows(entity.components),
  };
  const after = {
    ...before,
    ...patch,
    ...componentRows(afterComponents),
  };
  delete after.components; // 已展开成每个组件一行
  const labels = { name: "名称", desc: "描述" };
  for (const key of Object.keys(before)) {
    if (key.startsWith("components.")) {
      labels[key] = `组件 ${key.slice("components.".length)}`;
    }
  }
  const ok = await askDiff({
    title: `保存实体「${entityName(entity)}」`,
    detail: "components 是整体替换；按组件逐个对比（未列出的组件不变）",
    changes: diffFields(before, after, labels),
  });
  if (!ok) return;
  try {
    await apiPatch(`/admin/entities/${entity.id}`, patch);
    await load();
  } catch (e) {
    error.value = e.message;
  }
}

async function removeEntity(entity) {
  // 实体只有组件：删之前列一下它的内容组件（core: 是协议数据，不必列）
  const comps = contentComponents(entity);
  const ok = await askConfirm({
    title: "删除实体",
    danger: true,
    text: `删除实体「${entityName(entity)}」？`,
    detail: comps.length
      ? `内容组件：${comps.join("、")}（会随实体一起消失）`
      : "它没有任何内容组件。",
  });
  if (!ok) return;
  try {
    await apiDelete(`/admin/entities/${entity.id}`);
    await load();
  } catch (e) {
    error.value = e.message;
  }
}

async function saveEntityTemplate(entity) {
  // 模板 id 里带一个内容组件名做 slug（组件键可能带 `:`，换成 `_` 保证 id 干净）
  const slug = contentComponents(entity)[0]?.replace(/[^A-Za-z0-9_.-]/g, "_") || "bare";
  try {
    await apiPost("/admin/templates", {
      id: `entity_${slug}_${Date.now().toString(36)}`,
      name: `${entityName(entity)}（模板）`,
      scope: "entity",
      data: {
        // 模板负载 = {name, desc, components}（D41：模板是"一组组件的预设"，
        // 没有 kind / tags——要带能力就在 components 里给组件键）
        name: entityName(entity),
        desc: entityDesc(entity),
        // 位置不进模板（模板是"这东西是什么"，不是"它在哪"）
        components: withoutPosition(entity.components),
      },
    });
    await load();
  } catch (e) {
    error.value = e.message;
  }
}

/** 定位：跳到地图编辑器并选中它所在的那一格（`#/admin/maps/{map}/{tab}/{row}/{col}`）。 */
function locateEntity(entity) {
  const p = entityPosition(entity);
  if (!p) return; // 不在世界上就没有格可定位（按钮那边已置灰）
  location.hash = `#/admin/maps/${encodeURIComponent(p.map_id)}/map/${p.row}/${p.col}`;
}

onMounted(load);
</script>

<style scoped>
.filters {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 10px;
}
.lead {
  margin: -4px 0 10px;
  font-size: 12px;
  line-height: 1.6;
}
.grow {
  flex: 1;
}
</style>
