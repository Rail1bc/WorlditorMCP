// 临时交互自检（不入库）：用一个"无 DOM 的迷你渲染器"真跑组件——
// 触发 onClick / onInput / onChange，验证放置区、详情面板、能力面板与
// FieldForm 的"JSON 写坏就不发"语义。
// 用法：webui 下 `npx vite build --config rendercheck_tmp/vite.config.mjs`
//       然后 `node rendercheck_tmp/out3/interact.js`
import { createRenderer, h, nextTick } from "vue";
import EntityManager from "../src/components/editor/EntityManager.vue";
import FieldForm from "../src/components/editor/FieldForm.vue";

const warnings = [];
const realWarn = console.warn;
console.warn = (...args) => {
  warnings.push(args.join(" "));
  realWarn(...args);
};

// ---------- 迷你渲染器（节点 = 普通对象 + 最小 DOM 面：value / options / 事件） ----------

function makeEl(tag) {
  const el = {
    tag,
    children: [],
    props: {},
    parent: null,
    _listeners: {},
    _value: undefined,
    selectedIndex: -1,
    multiple: false,
    addEventListener(type, fn) {
      (el._listeners[type] || (el._listeners[type] = [])).push(fn);
    },
    removeEventListener(type, fn) {
      const list = el._listeners[type] || [];
      const i = list.indexOf(fn);
      if (i !== -1) list.splice(i, 1);
    },
    get options() {
      return el.children.filter((c) => c.tag === "option");
    },
    get value() {
      return el._value === undefined ? "" : el._value;
    },
    set value(v) {
      el._value = v;
    },
  };
  return el;
}

const nodeOps = {
  createElement: (tag) => makeEl(tag),
  createText: (value) => ({ text: value, children: [], props: {}, parent: null }),
  createComment: (value) => ({
    text: value,
    isComment: true,
    children: [],
    props: {},
    parent: null,
  }),
  setText: (node, value) => {
    node.text = value;
  },
  setElementText: (el, value) => {
    el.children = [{ text: value, children: [], props: {}, parent: el }];
  },
  insert: (child, parent, anchor) => {
    child.parent = parent;
    if (!anchor) {
      parent.children.push(child);
      return;
    }
    const i = parent.children.indexOf(anchor);
    if (i === -1) parent.children.push(child);
    else parent.children.splice(i, 0, child);
  },
  remove: (child) => {
    const parent = child.parent;
    if (parent) {
      const i = parent.children.indexOf(child);
      if (i !== -1) parent.children.splice(i, 1);
    }
    child.parent = null;
  },
  parentNode: (node) => node.parent || null,
  nextSibling: (node) => {
    const parent = node.parent;
    if (!parent) return null;
    const i = parent.children.indexOf(node);
    return parent.children[i + 1] || null;
  },
  patchProp: (el, key, prev, next) => {
    el.props[key] = next;
    // option / input 的 value 也要落到"DOM 面"上（v-model 指令读 el.value）
    if (key === "value") el._value = next;
  },
};

const { createApp: createMiniApp } = createRenderer(nodeOps);

function fire(node, type) {
  for (const fn of node._listeners[type] || []) fn({ target: node });
}

function walk(node, fn) {
  if (!node) return;
  fn(node);
  for (const child of node.children || []) walk(child, fn);
}
function nodes(root, pred) {
  const out = [];
  walk(root, (n) => {
    if (pred(n)) out.push(n);
  });
  return out;
}
function text(node) {
  let out = "";
  walk(node, (n) => {
    if (typeof n.text === "string") out += n.text;
  });
  return out;
}
function rootNode() {
  return { tag: "#root", children: [], props: {}, parent: null };
}
function setValue(node, value) {
  // v-model 的实际路径：先写 el.value，再触发指令监听的 input/change
  node.value = value;
  node.props.onInput?.({ target: node });
  fire(node, "input");
}
async function pickSelect(node, value) {
  node.value = value;
  fire(node, "change");
  node.props.onChange?.({ target: node });
  await nextTick();
}
async function click(node) {
  node.props.onClick();
  await nextTick();
}

const kinds = [
  {
    key: "local:merchant",
    source: "local",
    name: "merchant",
    label: "商人",
    interactions: ["trade"],
    fields: [{ name: "gold", label: "金币", type: "int", default: 10 }],
    categories: [],
  },
  {
    key: "worlditor_play_demo:apple",
    source: "worlditor_play_demo",
    name: "apple",
    label: "苹果",
    interactions: ["eat"],
    fields: [],
    categories: [],
  },
];

function caps(components, extra = {}) {
  return {
    components: Object.keys(components),
    active_components: [],
    inactive_components: [],
    unknown_components: [],
    interactions: [],
    fields: {},
    ...extra,
  };
}

const merchant = {
  id: "aaaaaaaa1111",
  components: {
    "core:info": { name: "老张" },
    "core:position": { map_id: "default", row: 1, col: 2 },
    "local:merchant": { gold: 7 },
  },
  last_active_ts: 1,
  revision: 3,
  changed_tick: 9,
  capabilities: caps(
    { "core:info": {}, "core:position": {}, "local:merchant": { gold: 7 } },
    {
      active_components: ["local:merchant"],
      interactions: ["trade"],
      fields: { "local:merchant": [{ name: "gold", label: "金币", type: "int" }] },
    }
  ),
};

const fictional = {
  id: "bbbbbbbb2222",
  components: {
    "local:thing": { hp: 3 },
    "core:position": { map_id: "default", row: 0, col: 0 },
  },
  last_active_ts: 2,
  revision: 1,
  changed_tick: 4,
  capabilities: caps(
    { "local:thing": { hp: 3 }, "core:position": {} },
    { unknown_components: ["local:thing"] }
  ),
};

const failures = [];
function check(name, ok) {
  if (!ok) failures.push(name);
}

// ---------- ① EntityManager：放置区 / 组件筛选 / 详情 + 能力面板 ----------

async function checkEntityManager() {
  const root = rootNode();
  createMiniApp(EntityManager, {
    entities: [merchant, fictional],
    kinds,
    entityTemplates: [
      {
        id: "t1",
        name: "商人模板",
        source: "play",
        play_id: "worlditor_play_demo",
        scope: "entity",
        data: { name: "模板商人", desc: "", components: { "local:merchant": {} } },
      },
    ],
    allowAbsent: true,
  }).mount(root);

  // 组件筛选下拉：选项 = 所有实体组件键（非 core: 在前）
  const options = nodes(root, (n) => n.tag === "option").map((n) => n.props.value);
  const wanted = ["", "local:merchant", "core:info", "core:position", "local:thing"];
  check(
    "筛选下拉 = 全部组件键（非 core: 在前）",
    JSON.stringify(options) === JSON.stringify(wanted)
  );
  check("排序项含按组件", nodes(root, (n) => n.tag === "option" && n.props.value === "comp").length === 1);

  // 放置区：模板 + 能力组件输入 + datalist + 组件选择器 + FieldForm
  const toggle = nodes(root, (n) => n.tag === "button" && text(n).includes("放置实体"))[0];
  check("找到「放置实体」按钮", Boolean(toggle));
  await click(toggle);
  const createText = text(root);
  check("放置区：模板选项", createText.includes("商人模板") && createText.includes("worlditor_play_demo"));
  check(
    "放置区：能力组件输入（裸名由后端解析）",
    nodes(root, (n) =>
      String(n.props && n.props.placeholder).includes("能力组件（可自由输入，裸名由后端解析）")
    ).length === 1
  );
  const datalist = nodes(root, (n) => n.tag === "datalist")[0];
  check("放置区：datalist 用 kinds.key", Boolean(datalist) && datalist.children.some((c) => c.props.value === "local:merchant"));
  check("放置区：组件选择器", createText.includes("＋ 已声明组件…"));
  check("放置区：FieldForm 新增组件", createText.includes("＋ 新增组件"));

  // 选中实体 → 详情 + 能力面板
  const row = nodes(root, (n) => n.tag === "tr" && text(n).includes("老张"))[0];
  check("找到实体行", Boolean(row));
  await click(row);
  const detail = text(root);
  check("详情：生效组件", detail.includes("生效组件：local:merchant"));
  check("详情：动作", detail.includes("动作：trade"));
  check("详情：字段按组件分组", detail.includes("local:merchant: 金币"));
  check("详情：组件选择器", detail.includes("＋ 已声明组件…"));
  check("详情：旧「类型（基底）」已删", !detail.includes("类型（基底）"));
  // 详情里组件块的声明字段控件回填了数据里的值（gold=7）
  const detailPane = nodes(root, (n) => n.props && n.props.class === "detail")[0];
  check(
    "详情：声明字段回填 7",
    nodes(detailPane, (n) => n.tag === "input" && n.props.value === 7).length >= 1
  );
  check("详情：没有 core: 组件 chip（组件列只显示能力组件）", !detail.includes("组件 core:info（能力 = 组件的存在）"));

  // 切换排序到"按组件"
  const sortSelect = nodes(root, (n) => n.tag === "select" && n.children.some((c) => c.props.value === "comp"))[0];
  check("找到排序下拉", Boolean(sortSelect));
  await pickSelect(sortSelect, "comp");
  const rows = nodes(root, (n) => n.tag === "tr" && text(n).includes("老张")).length;
  check("按组件排序后仍能渲染", rows === 1);
}

// ---------- ② FieldForm：分块顺序 / 其余键 / JSON 写坏就不发 ----------

async function checkFieldForm() {
  const emits = [];
  const components = {
    "core:info": { name: "老张", desc: "掌柜" },
    "worlditor_play_demo:apple": {},
    "local:merchant": { gold: 7, mood: "happy" },
    "zzz:ghost": { hp: 3 },
  };
  const Root = {
    render: () =>
      h(FieldForm, { kinds, components, onUpdate: (v) => emits.push(v) }),
  };
  const root = rootNode();
  createMiniApp(Root).mount(root);

  const blocks = nodes(root, (n) => {
    const summary = (n.children || []).find((c) => c.tag === "summary");
    return n.tag === "details" && summary && !text(summary).includes("新增组件");
  });
  check("四个组件块", blocks.length === 4);
  const order = blocks.map((b) => {
    const summary = b.children.find((c) => c.tag === "summary");
    return text(summary).split(" ")[0];
  });
  check(
    "块顺序 core → 玩法包 → local → 其他",
    JSON.stringify(order) ===
      JSON.stringify(["core:info", "worlditor_play_demo:apple", "local:merchant", "zzz:ghost"])
  );

  function blockOf(key) {
    return nodes(root, (n) => {
      const summary = (n.children || []).find((c) => c.tag === "summary");
      return n.tag === "details" && summary && text(summary).startsWith(key);
    })[0];
  }
  function extraArea(key) {
    return nodes(blockOf(key), (n) => n.tag === "textarea")[0];
  }

  const extraJson = (key) => JSON.parse(extraArea(key).value || extraArea(key).props.value || "{}");
  check(
    "其余键不含声明字段（gold 不进 JSON 框）",
    extraJson("local:merchant").mood === "happy" && !("gold" in extraJson("local:merchant"))
  );
  check("未声明组件整块 JSON", JSON.stringify(extraJson("zzz:ghost")) === '{"hp":3}');
  check("core: 块也有 JSON 兜底", extraJson("core:info").name === "老张");
  check(
    "声明字段渲染控件",
    nodes(blockOf("local:merchant"), (n) => n.tag === "input" && n.props.value === 7).length === 1
  );

  // JSON 写坏 → 不发 + 露错误
  setValue(extraArea("local:merchant"), "{");
  extraArea("local:merchant").props.onChange();
  await nextTick();
  check("JSON 写坏时不发（fail closed）", emits.length === 0);
  check("JSON 写坏时错误露在折叠区外", text(root).includes("JSON 解析失败"));
  const errorNode = nodes(root, (n) => n.tag === "p" && String(n.props.class).includes("error-text"))[0];
  check("错误在第一个组件块之前", Boolean(errorNode) && Boolean(errorNode.parent) && root.children.indexOf(errorNode.parent) < root.children.indexOf(root.children.find((c) => text(c).includes("core:info"))));

  // 修好 → 组装 = {...其余键, ...声明字段当前值}
  setValue(extraArea("local:merchant"), '{"mood": "sad"}');
  extraArea("local:merchant").props.onChange();
  await nextTick();
  check("修好后发一次", emits.length === 1);
  const sent = emits.length ? emits[0].components : {};
  check(
    "组装：其余键 + 声明字段当前值",
    JSON.stringify(sent["local:merchant"]) === JSON.stringify({ mood: "sad", gold: 7 })
  );
  check("组装：其它组件原样带回", JSON.stringify(sent["zzz:ghost"]) === '{"hp":3}' && sent["core:info"].name === "老张");
}

async function main() {
  await checkEntityManager();
  await checkFieldForm();

  const vueWarnings = warnings.filter((w) => w.includes("[Vue warn]"));
  if (vueWarnings.length) failures.push(`Vue warn: ${vueWarnings.join(" | ")}`);

  if (failures.length) {
    console.error("FAIL:\n - " + failures.join("\n - "));
    process.exit(1);
  }
  console.log("INTERACT CHECK OK");
}

main();
