import type { NextConfig } from "next";

const config: NextConfig = {
  // 컨테이너 배포 (ADR-0017 §1). 서버 docker compose에 함께 올린다.
  output: "standalone",
  // 워크스페이스 패키지는 소스를 그대로 가져와 Next가 변환한다 (빌드 산출물을 두지 않는다).
  transpilePackages: ["@chaeksas/ui", "@chaeksas/api-types"],
  typedRoutes: true,
};

export default config;
