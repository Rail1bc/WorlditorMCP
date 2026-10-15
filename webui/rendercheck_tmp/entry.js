// 临时自检（不入库）：把改过的编辑器组件真正渲染一遍，抓模板/组合式 API 的运行时错误。
// 用法：webui 下 `npx vite build --ssr rendercheck_tmp/entry.js --outDir rendercheck_tmp/out`
//       然后 `node rendercheck_tmp/out/entry.js`
import { createSSRApp, h } from "vue";
import { renderToString } from "vue/server-renderer";
import EntityManager from "../src/components/editor/EntityManager.vue";
import FieldForm from "../src/components/editor/FieldForm.vue";
import ComponentPicker from "../src/components/editor/ComponentPicker.vue";
import { abilityComponents, componentKeys, isCoreComponent } from "../src/entity.js";

const warnings = [];
const realWarn = console.warn;
console.warn = (...args) => {
  warnings.push(args.join(" "));
  realWarn(...args);
};

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
    components: componentKeys({ components }),
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

const inactive = {
  id: "cccccccc3333",
  components: { "worlditor_play_demo:apple": {} },
  last_active_ts: 3,
  revision: 1,
  changed_tick: 5,
  capabilities: caps(
    { "worlditor_play_demo:apple": {} },
    { inactive_components: ["worlditor_play_demo:apple"] }
  ),
};

const failures = [];
function check(name, ok) {
  if (!ok) failures.push(name);
}

async function main() {
  const html = await renderToString(
    createSSRApp({
      render: () =>
        h(EntityManager, {
          entities: [merchant, fictional, inactive],
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
          tileFilter: null,
          allowAbsent: true,
        }),
    })
  );

  // 列表：组件列只显示非 core: 的键；位置经 positionLabel；能力列有告警
  check("列表显示能力组件 chip", html.includes("local:merchant"));
  // 非 core: 的 chip 标题模板只在"组件"列出现；core: 只应出现在筛选下拉里
  check(
    "列表组件列不显示 core: chip",
    !html.includes("组件 core:info（能力 = 组件的存在）")
  );
  check("筛选下拉仍列 core: 组件", html.includes('value="core:info"'));
  check("列表位置经 positionLabel", html.includes("default 1,2"));
  check("虚构组件标红 chip", html.includes("虚构组件：没有声明，不贡献能力"));
  check("未启用组件计数", html.includes("⏸1"));
  check("虚构组件计数", html.includes("⚠1"));
  check("没有旧类型下拉", !html.includes("全部类型"));
  check("按组件排序项", html.includes("按组件"));
  check("搜索框文案", html.includes("搜索名称 / 组件 / id…"));
  // SSR 会在相邻文本节点间插注释锚点，分两段断言
  if (!(html.includes("商人模板") && html.includes("（worlditor_play_demo）"))) {
    const i = html.indexOf("商人模板");
    console.log("DEBUG 模板选项片段:", JSON.stringify(html.slice(Math.max(0, i - 120), i + 160)));
  }
  check(
    "模板选项",
    html.includes("商人模板") && html.includes("（worlditor_play_demo）")
  );

  // 能力面板：选中一个实体后再渲染一次（走组件实例暴露的 focus）
  const app2 = createSSRApp({
    render: () => h(EntityManager, { entities: [merchant], kinds }),
  });
  const html2 = await renderToString(app2);
  check("未选中实体时给出提示", html2.includes("从左边选一个实体"));
  const inst = app2._instance && app2._instance.subTree && app2._instance.subTree.component;
  const exposed = inst && inst.exposed;
  if (exposed && typeof exposed.focus === "function") {
    exposed.focus("aaaaaaaa1111");
    const html3 = await renderToString(app2);
    check("详情面板：生效组件", html3.includes("生效组件：local:merchant"));
    check("详情面板：动作", html3.includes("动作：trade"));
    check(
      "详情面板：字段按组件分组",
      html3.includes("local:merchant") && html3.includes("金币")
    );
    check("详情面板：组件选择器", html3.includes("＋ 已声明组件…"));
    check("详情面板：没有类型输入", !html3.includes("类型（基底）"));
  } else {
    console.log(
      "（跳过详情面板渲染自检：拿不到组件实例）",
      "app2._instance =",
      app2._instance,
      "subTree =",
      app2._instance && app2._instance.subTree
    );
  }

  // FieldForm：按组件分块 + 声明字段 + 其余键 JSON
  const ff = await renderToString(
    createSSRApp({
      render: () =>
        h(FieldForm, {
          kinds,
          components: {
            "core:info": { name: "老张", desc: "掌柜" },
            "local:merchant": { gold: 7, mood: "happy" },
            "local:thing": { hp: 3 },
          },
        }),
    })
  );
  check("FieldForm 渲染组件块", ff.includes("local:merchant") && ff.includes("local:thing"));
  check("FieldForm 显示声明字段控件", ff.includes("金币"));
  check("FieldForm 其余键兜底", ff.includes("其余键"));
  check("FieldForm 虚构组件标记", ff.includes("虚构组件"));
  check("FieldForm 内核保留标记", ff.includes("内核保留"));
  check("FieldForm 新增组件", ff.includes("＋ 新增组件"));
  check("FieldForm 没有猜落点文案", !ff.includes("还没落进任何组件"));

  // ComponentPicker：已声明 / 虚构 / 自由输入
  const cp = await renderToString(
    createSSRApp({
      render: () => h(ComponentPicker, { modelValue: ["local:merchant", "local:ghost"], kinds }),
    })
  );
  check("选择器显示已声明组件", cp.includes("商人") && cp.includes("local:merchant"));
  check("选择器标虚构组件", cp.includes("虚构组件"));
  check("选择器来源提示", cp.includes("来源 local"));
  check("选择器可手输", cp.includes("手输组件键"));

  // 纯函数：entity.js 的新助手
  check("componentKeys 含 core", componentKeys(merchant).includes("core:info"));
  check(
    "abilityComponents 排除 core",
    JSON.stringify(abilityComponents(merchant)) === JSON.stringify(["local:merchant"])
  );
  check("isCoreComponent", isCoreComponent("core:info") && !isCoreComponent("local:merchant"));

  const vueWarnings = warnings.filter((w) => w.includes("[Vue warn]"));
  if (vueWarnings.length) failures.push(`Vue warn: ${vueWarnings.join(" | ")}`);

  if (failures.length) {
    console.error("FAIL:\n - " + failures.join("\n - "));
    process.exit(1);
  }
  console.log("RENDER CHECK OK");
}

main();
