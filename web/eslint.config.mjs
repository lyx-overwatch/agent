import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = [
  ...nextVitals,
  ...nextTs,
  // 本项目未启用 React Compiler，但 eslint-config-next@16 默认开启的 React
  // Compiler 专用规则会在回调闭包、数据拉取等合法模式上误报。关掉这三条，
  // 避免对未编译代码产生大量误报（参考 next 官方对非编译器项目的处理）。
  {
    rules: {
      "react-hooks/set-state-in-effect": "off",
      "react-hooks/immutability": "off",
      "react-hooks/refs": "off",
    },
  },
  // Override default ignores of eslint-config-next.
  {
    ignores: [
      ".next/**",
      "out/**",
      "build/**",
      "next-env.d.ts",
    ],
  },
];

export default eslintConfig;
