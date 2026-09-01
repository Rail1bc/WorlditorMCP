// 全局状态（响应式）：token / 端口模式 / 全局错误提示。

import { reactive } from "vue";

export const store = reactive({
  token: "",
  mode: "play", // play（玩家端口）/ admin（管理端口），运行时来自 /meta
  error: "", // 全局错误提示
});
