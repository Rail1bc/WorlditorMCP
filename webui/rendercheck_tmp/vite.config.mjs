// 临时自检用 vite 配置（不入库）：客户端模式打包，好在 Node 里用迷你渲染器跑组件。
import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

export default defineConfig({
  plugins: [vue()],
  build: {
    outDir: "rendercheck_tmp/out3",
    emptyOutDir: true,
    minify: false,
    lib: {
      entry: "rendercheck_tmp/interact.js",
      formats: ["es"],
      fileName: "interact",
    },
    rollupOptions: { external: ["vue"] },
  },
});
