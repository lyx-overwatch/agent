import { redirect } from "next/navigation";

/** 根路径 → 跳转到 SkillHub 工作台 */
export default function Home() {
  redirect("/agc-agent");
}
