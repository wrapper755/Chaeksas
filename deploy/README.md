# 서버 구성 (docker compose)

```bash
cd deploy
cp .env.example .env            # 첫 관리자 비밀번호와 세션 비밀을 채운다
docker compose up -d --build
curl http://localhost:8800/healthz
```

그다음 브라우저로 <http://localhost:8501>에 들어가 `.env`의 첫 관리자 아이디·비밀번호로 로그인한다. 비밀번호를 비워 두었으면 Center가 만든 것이 `docker compose logs center`에 한 번 찍힌다 — 들어가서 바로 바꾼다 (「관리자 계정」).

| 서비스 | 포트 | 데이터 |
| --- | --- | --- |
| Center API | 8800 | 볼륨 `center-data` → `/data` (DB `center.sqlite3`, 패키지 zip) |
| Center 콘솔 (Next.js) | 8501 | 없음 (상태를 들고 있지 않다) |

- 포트·환경변수의 원본은 [`docs/04-setup.md`](../docs/04-setup.md) §6이다.
- 콘솔은 **관리자 계정**으로 들어온다. 승인·배포·외부 확장 등록도 콘솔에서 하고, 봉투는 **Center가 서버의 키로 서명한다**(키는 DB 안, 처음 뜰 때 만든다 — [ADR-0090](../docs/decisions/0090-center-admin-accounts.md)). 콘솔 BFF가 로그인 세션을 들고 부른다 ([ADR-0017](../docs/decisions/0017-web-nextjs-design-system.md)).
- 관리자·읽기 토큰은 **자동화용**이다 — 비우면 그 길이 닫힌다.
- 서명 키 교체는 서버 셸에서: `docker compose exec center uv run --frozen --package chaeksas-center chk-center signing-key rotate` (옛 키는 믿는 목록에 남아 이미 나간 배포가 산다).
- 콘솔은 `http://center:8800`으로 Center를 부른다 — **브라우저가 아니라 콘솔 서버가** 부르기 때문에 `localhost`가 아니다. 위 막대에는 그 주소가 아니라 `.env`의 `CHK_CONSOLE__CENTER_PUBLIC_URL`(Bot UI·Studio에 적을 바깥 주소)이 보인다.
- 그 포트를 이미 쓰는 것이 있으면 `.env`의 `CHK_CENTER__HOST_PORT`·`CHK_CONSOLE__HOST_PORT`로 **호스트 쪽만** 옮긴다 (컨테이너 안의 포트는 그대로다).
- 바깥 노출을 역방향 프록시·터널(예: Cloudflare Tunnel)에 맡길 때는 같은 칸에 `127.0.0.1:8800`처럼 **주소까지** 적어 호스트의 루프백에만 연다. Docker가 연 포트는 ufw를 거치지 않으므로 방화벽으로는 막히지 않는다.
- 콘솔에는 `HOSTNAME: "0.0.0.0"`을 준다 — Next.js standalone은 `HOSTNAME`에 바인드하는데 Docker가 그것을 컨테이너 id로 채워 127.0.0.1을 두드리는 HEALTHCHECK가 늘 실패한다.
- 두 컨테이너 모두 비관리자로 돈다 (Center uid 10001, 콘솔은 node 이미지의 `node`). 볼륨 권한이 안 맞으면 `docker compose down -v`로 지우고 다시 올린다.
- 콘솔 이미지는 **`Dockerfile.console` 하나**로 만든다 — 어느 콘솔인지는 빌드 인자 `APP`이 정한다.
- 아직 없는 것: 서비스 앱과 그 관리 콘솔(`svc-console`, 서비스 앱마다 하나 — M4), Neo4j·LLM 게이트웨이(M4), 역방향 프록시·TLS.
