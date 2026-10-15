/**
 * 实体读写的统一入口（实体模型 v2 / DESIGN §12.4；D41：**能力 = 组件的存在**）。
 *
 * 实体的**名字 / 描述 / 账户绑定 / 位置 / 能力全都不是顶层字段**，而是组件：
 *
 *   { id, components, last_active_ts, revision, changed_tick }
 *     components: { "core:info": {name, desc}, "core:account": {user_id},
 *                   "core:position": {map_id, row, col}, ... }
 *
 * 投影里**没有 `kind`、没有 `tags`**（D41-b 已从实体上删除）：实体上只有 `components`
 * 里的键，纯标记组件的数据是 `{}`，带数据的组件照样只是组件。
 *
 * 读名规则（内核的缺失语义，前端照做，且只在这一处实现）：
 *   name = components["core:info"].name  ||  id 前 8 位
 *   desc = components["core:info"].desc  ||  ""
 *
 * 读位置规则（D36）：
 *   位置 = components["core:position"]   → 没有就是"不在世界上"，返回 null
 *
 * 写名规则：PATCH /admin/entities/{id} 接受顶层 `name` / `desc`（后端折进 core:info）。
 * ⚠️ `components` 在 PATCH 里是**整体替换** —— 改名字别用 components，改组件别混名字。
 * ⚠️ `kind` / `tags` 只在 POST 上是**输入便利**（裸名由后端解析成组件键）：写完之后
 *   实体上就只剩组件键了，前端别再把它们当成实体的字段读。
 */

export const CORE_INFO = "core:info";
export const CORE_ACCOUNT = "core:account";
export const CORE_POSITION = "core:position";

/**
 * 实体位置（`core:position`）；**不在世界上时返回 null**（D36）。
 *
 * v2 起位置不再是实体 JSON 的顶层 `map_id` / `row` / `col`——别直接读那三个键
 * （读到的是 undefined，网格上会静默画到 (0,0)）。
 */
export function entityPosition(e) {
  const p = e && e.components && e.components[CORE_POSITION];
  if (!p) return null;
  const { map_id, row, col } = p;
  if (typeof map_id !== "string" || !map_id) return null;
  if (typeof row !== "number" || typeof col !== "number") return null;
  return { map_id, row, col };
}

/** 实体是否在世界上（= 有位置）。 */
export function hasPosition(e) {
  return entityPosition(e) !== null;
}

/**
 * 位置的展示串：`"ceshi 0,-1"`；不在世界上时 `"不在世界"`（D36）。
 * 位置缺失不是错误——实体可以先被造出来、之后再放进世界。
 */
export function positionLabel(e) {
  const p = entityPosition(e);
  if (!p) return "不在世界";
  return `${p.map_id} ${p.row},${p.col}`;
}

// 排序哨兵：不在世界上的实体排最后（不能拿 null 去和数字比）
const NO_ROW = 1 << 30;
const NO_COL = 1 << 30;
const NO_MAP = "\uffff";

/** 排序用的位置键；缺失时给哨兵，保证 `byPos` 这类比较器不会崩。 */
export function positionSortKey(e) {
  const p = entityPosition(e);
  if (!p) return [NO_MAP, NO_ROW, NO_COL];
  return [p.map_id, p.row, p.col];
}

/**
 * 去掉位置组件后的**副本**（模板负载 / "不进世界"的创建用）。
 *
 * 位置是"它在哪"，模板描述的是"它是什么"——把位置写进模板，套用时就会
 * **静默把人搬回老地方**；而"不放进世界"勾了之后若组件里还漏进一个
 * `core:position`，实体照样会被放进去（勾选形同虚设）。
 */
export function withoutPosition(components) {
  const out = { ...(components || {}) };
  delete out[CORE_POSITION];
  return out;
}

/** 组件里的原始名字（没有就是空串——**不带兜底**，用于编辑框回填）。 */
export function rawEntityName(e) {
  const info = e && e.components && e.components[CORE_INFO];
  return info && typeof info.name === "string" ? info.name : "";
}

/** 展示用名字：raw → 兜底 `id` 前 8 位（永不返回空串，除非连 id 都没有）。 */
export function entityName(e) {
  const name = rawEntityName(e);
  if (name) return name;
  return e && e.id ? String(e.id).slice(0, 8) : "";
}

/** 组件里的原始描述（没有就是空串）。 */
export function rawEntityDesc(e) {
  const info = e && e.components && e.components[CORE_INFO];
  return info && typeof info.desc === "string" ? info.desc : "";
}

/** 展示用描述：没有就是空串。 */
export function entityDesc(e) {
  return rawEntityDesc(e);
}

/** 账户绑定（core:account.user_id）；未绑定返回 null。 */
export function entityUserId(e) {
  const acc = e && e.components && e.components[CORE_ACCOUNT];
  return acc && typeof acc.user_id === "string" && acc.user_id ? acc.user_id : null;
}

/** 该实体是否带某个组件（组件名 = `source:name` 信封）。 */
export function hasComponent(e, key) {
  return Boolean(e && e.components && Object.prototype.hasOwnProperty.call(e.components, key));
}

/** 实体带的全部组件键（含 `core:`）；**能力清单就是它**（D41）。 */
export function componentKeys(e) {
  return Object.keys((e && e.components) || {});
}

const CORE_PREFIX = "core:";

/** 是否是内核保留组件（协议数据：名字 / 账户 / 位置——**不是能力**）。 */
export function isCoreComponent(key) {
  return String(key).startsWith(CORE_PREFIX);
}

/**
 * 内容组件键（排除 `core:`）——**"这个实体带了哪些非协议组件"**。
 *
 * ⚠️ 名字：v0.7.2 前叫 `abilityComponents`（"能力组件"），但**内核没有"能力"这个数据概念**
 * ——实体上只有组件：带了某个组件就是带了它，组件的数据是 `{}`（纯标记）还是 `{...}`
 * （带数据）都不改变这一点。所以界面上统一说"组件"，判断"能不能做某件事"看**声明**
 * （`capabilities.interactions` 等，后端的裁决，前端不重算）。
 *
 * `core:` 是内核协议数据（名字 / 账户 / 位置 / 感知），不是内容——列表里想显示**全部**
 * 组件就用 `componentKeys()`，这里只排除协议组件。
 *
 * ⚠️ 能力键会随设计演进改名（D44 把 `unknown_components` 拆成 `orphan_components` +
 * `fictional_components`）。**别在模板里直读 `capabilities.<键>`**——后端不再返回旧键时
 * 读到的是 `undefined`，`.length` / `.join` 当场抛错、整块 UI 白屏（v0.7.1 事故）。
 * 统一经归一化读取（`EntityManager.vue` 的 `capsOf()`）：缺键 = 空数组。
 */
export function contentComponents(e) {
  return componentKeys(e).filter((key) => !isCoreComponent(key));
}

/**
 * 单个组件的**数据摘要**（列表预览用，与组件键拼在一起显示）。
 *
 * 位置是组件（`core:position`）而不是实体的字段，所以在同一列里以坐标形式出现：
 *   - `core:position` → `"default 2,5"`
 *   - 其它有数据的组件 → `"3 键"`
 *   - 空组件（纯标记，数据 `{}`）→ `""`（不显示后缀，**空组件不是错误**）
 *
 * 组件数据本身**没有形状约定**（任意 JSON 对象），所以这里只做"有多少数据"的中性摘要，
 * 不假装知道每个键的含义。
 */
export function componentSummary(e, key) {
  const data = e && e.components ? e.components[key] : null;
  if (!data || typeof data !== "object") return "";
  if (key === CORE_POSITION) return positionLabel(e);
  const count = Object.keys(data).length;
  return count ? `${count} 键` : "";
}

/** 组件数据的原始 JSON（详情 / 折叠行的 title 用；空组件给 `{}`）。 */
export function componentJson(e, key) {
  const data = e && e.components ? e.components[key] : null;
  return JSON.stringify(data ?? {}, null, 2);
}
