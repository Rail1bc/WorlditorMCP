<template>
  <!-- 出口编辑（结构化，D23 / 修 G24）：目标带地图与权重、文案支持分时段、不丢任何字段 -->
  <div class="conns">
    <h4>四向出口</h4>
    <p class="dim">
      每条路径 = 文案 + 若干目标（首个是主目标，其余按权重随机）；
      跨图目标请在地图下拉里选别的图。保存前会先给你看旧值→新值。
    </p>
    <div v-for="dir in DIR_KEYS" :key="dir" class="conn-card" :class="{ off: !form[dir].enabled }">
      <label class="conn-head">
        <input type="checkbox" v-model="form[dir].enabled" />
        <b>{{ dirLabel[dir] }}</b>
        <span class="dim">{{ form[dir].paths.length }} 条路径</span>
        <button class="mini-btn" @click.prevent="addPath(dir)">＋ 路径</button>
      </label>

      <div v-for="(p, i) in form[dir].paths" :key="i" class="path">
        <div class="path-head">
          <span class="dim">路径 {{ i + 1 }}{{ i === 0 ? "（主）" : "（意外）" }}</span>
          <button class="mini-btn" @click.prevent="p.complex = !p.complex">
            {{ p.complex ? "改用纯文本" : "分时段 JSON" }}
          </button>
          <button class="mini-btn danger" @click.prevent="form[dir].paths.splice(i, 1)">
            删除路径
          </button>
        </div>
        <textarea
          v-if="p.complex"
          v-model="p.labelJson"
          rows="3"
          placeholder='分时段文案 JSON：{"periods":[{"start":"08:00","end":"18:00","items":[{"text":"白天","weight":1}]}]}'
        ></textarea>
        <input v-else v-model="p.labelText" placeholder="路径文案（可选，如「往北走」）" />

        <label class="mini-label">
          <input type="checkbox" v-model="p.reveal_target" /> 移动前揭示目标名
        </label>

        <div class="targets">
          <div v-for="(t, ti) in p.targets" :key="ti" class="target">
            <span class="tag" :class="{ main: ti === 0 }">{{ ti === 0 ? "主" : "意外" }}</span>
            <select v-model="t.map_id" class="mini">
              <option value="">本图</option>
              <option v-for="m in otherMaps" :key="m.id" :value="m.id">{{ m.name }}</option>
            </select>
            <input v-model.number="t.row" type="number" class="num" placeholder="行" />
            <input v-model.number="t.col" type="number" class="num" placeholder="列" />
            <label class="mini-label">
              权重
              <input v-model.number="t.weight" type="number" step="0.1" min="0.1" class="num" />
            </label>
            <span v-if="!targetExists(t)" class="bad" title="该坐标没有地块，运行时会跳过">目标不存在</span>
            <button class="mini-btn danger" @click.prevent="p.targets.splice(ti, 1)">×</button>
          </div>
          <button class="mini-btn" @click.prevent="addTarget(p)">＋ 目标</button>
        </div>
      </div>
      <button class="btn" @click="save(dir)">保存 {{ dirLabel[dir] }}</button>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, watch } from "vue";

const props = defineProps({
  tile: { type: Object, required: true },
  mapId: { type: String, default: "" },
  maps: { type: Array, default: () => [] }, // 全部地图 [{id,name}]（跨图目标用）
  locationKeys: { type: Array, default: () => [] }, // "map_id:row:col"
});
const emit = defineEmits(["save"]);

const DIR_KEYS = ["up", "right", "down", "left"];
const dirLabel = { up: "北↑", right: "东→", down: "南↓", left: "西←" };
const form = reactive({});

const otherMaps = computed(() => props.maps.filter((m) => m.id !== props.mapId));

function buildForm() {
  for (const dir of DIR_KEYS) {
    const slot = props.tile.connections?.[dir] || { enabled: false, paths: [] };
    form[dir] = {
      enabled: Boolean(slot.enabled),
      paths: (slot.paths || []).map((p) => pathToForm(p)),
    };
  }
}

function pathToForm(p) {
  const label = p.label || null;
  const simple = simpleLabel(label);
  return {
    complex: label != null && simple === null,
    labelText: simple === null ? "" : simple,
    labelJson: label ? JSON.stringify(label, null, 2) : "",
    reveal_target: p.reveal_target !== false,
    targets: (p.targets || []).map((t) => ({
      map_id: t.map_id || "",
      row: t.row,
      col: t.col,
      weight: t.weight ?? 1,
    })),
  };
}

/** 单时段单条文案 → 纯文本；分时段结构 → null（改用 JSON 编辑）。 */
function simpleLabel(label) {
  if (!label) return "";
  const periods = label.periods || [];
  if (periods.length === 1 && (periods[0].items || []).length === 1) {
    return periods[0].items[0].text || "";
  }
  return null;
}

function addPath(dir) {
  form[dir].paths.push({
    complex: false,
    labelText: "",
    labelJson: "",
    reveal_target: true,
    targets: [{ map_id: "", row: props.tile.row, col: props.tile.col, weight: 1 }],
  });
}

function addTarget(p) {
  p.targets.push({ map_id: "", row: props.tile.row, col: props.tile.col, weight: 1 });
}

function targetExists(t) {
  const key = `${t.map_id || props.mapId}:${t.row}:${t.col}`;
  return props.locationKeys.includes(key);
}

function labelPayload(p) {
  if (p.complex) {
    const text = (p.labelJson || "").trim();
    return text ? JSON.parse(text) : null; // 非法 JSON 由调用方兜住
  }
  const text = (p.labelText || "").trim();
  return text || null;
}

function save(dir) {
  const slot = form[dir];
  const paths = [];
  for (const p of slot.paths) {
    const targets = p.targets
      .filter((t) => Number.isInteger(t.row) && Number.isInteger(t.col))
      .map((t) => {
        const item = { row: t.row, col: t.col, weight: Number(t.weight) > 0 ? Number(t.weight) : 1 };
        if (t.map_id) item.map_id = t.map_id;
        return item;
      });
    if (!targets.length) continue; // 空路径没有意义（运行时会当死引用剔除）
    let label = null;
    try {
      label = labelPayload(p);
    } catch {
      emit("invalid", `路径文案不是合法 JSON：${p.labelJson.slice(0, 40)}…`);
      return;
    }
    paths.push({ label, reveal_target: p.reveal_target, targets });
  }
  emit("save", dir, { direction: dir, enabled: slot.enabled, paths });
}

watch(() => props.tile, buildForm, { immediate: true, deep: false });
</script>

<style scoped>
.conns {
  margin-top: 8px;
}
.conn-card {
  border: 1px solid var(--bg-3);
  border-radius: 8px;
  padding: 6px 8px;
  margin-bottom: 6px;
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.conn-card.off {
  opacity: 0.65;
}
.conn-head {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}
.path {
  display: flex;
  flex-direction: column;
  gap: 4px;
  border-left: 2px solid var(--bg-3);
  padding-left: 8px;
}
.path-head {
  display: flex;
  align-items: center;
  gap: 6px;
}
.targets {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.target {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-wrap: wrap;
  font-size: 12px;
}
.tag {
  font-size: 10px;
  border: 1px solid var(--bg-3);
  border-radius: 4px;
  padding: 0 4px;
  color: var(--text-dim);
}
.tag.main {
  color: var(--accent);
  border-color: var(--accent);
}
.bad {
  color: var(--danger);
  font-size: 11px;
}
.num {
  width: 56px;
}
input,
textarea,
select {
  padding: 5px 8px;
  border-radius: 6px;
  border: 1px solid var(--bg-3);
  background: var(--bg);
  color: var(--text);
  font-size: 13px;
}
textarea {
  width: 100%;
  font-family: ui-monospace, monospace;
  font-size: 12px;
}
.mini {
  font-size: 12px;
  padding: 4px 6px;
}
.mini-btn {
  border: none;
  background: transparent;
  color: var(--text-dim);
  font-size: 12px;
  cursor: pointer;
  padding: 0 4px;
}
.mini-btn:hover {
  color: var(--accent);
}
.mini-btn.danger:hover {
  color: var(--danger);
}
.mini-label {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--text-dim);
}
.dim {
  color: var(--text-dim);
  font-size: 13px;
}
h4 {
  margin: 6px 0 4px;
}
</style>
