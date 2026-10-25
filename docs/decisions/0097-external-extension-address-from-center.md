# ADR-0097. 외부 확장의 주소도 Center가 덮어쓴다 — 정의의 허용 호스트 안에서만

| 항목 | 값 |
| --- | --- |
| 상태 | 수락 |
| 날짜 | 2026-10-25 |
| 관련 | 계약 C13·C7, [ADR-0060](0060-pinning-external-definitions.md)·[ADR-0091](0091-external-apps-without-auth-take-no-key.md)·[ADR-0094](0094-service-app-keys-ride-the-deployment.md), 바깥 요청 NowView R4 |

## 배경

C13은 「주소의 출처는 하나다 — Center 리소스 등록(C7)의 `base_url`이 있으면 그것을, 없으면 정의의 값을」이라고 적고(`contracts.extension.Service`),
`allowed_hosts`에는 「`base_url`·**Center의 `base_url`**·`catalog_url`·`health`의 호스트가 모두 이 안에 있어야 한다」고 적었다.
**읽는 쪽은 그대로 돈다** — `AdapterCaller`가 명부의 주소(`AppDirectory.base_url(app_id)`)를 먼저 보고, 없을 때만 정의의 `base_url`을 쓴다.
**그런데 Center에는 외부 확장의 주소를 넣을 입구가 없다.** 명부의 주소는 C7 서비스 앱 등록에서만 오고, 그 등록(`POST /resources/service-apps`)은 C11 `/manifest`를 읽어야 행을 만든다. 외부 앱에는 C11 `/manifest`가 없다.
그래서 지금은 **정의의 `base_url`이 유일한 주소다.** 환경마다 주소가 다르면 같은 id로 정의를 두 벌(다른 판·다른 해시) 두어야 하고, 고정(ADR-0060)한 Bot은 다른 Center에서 「고정한 정의가 아니다」로 멈춘다.

## 선택지

| 선택지 | 장점 | 단점 |
| --- | --- | --- |
| A. 지금처럼 정의 두 벌 | 바꿀 것이 없다 | 해시가 둘이라 같은 Bot 패키지를 두 환경에 못 쓴다(고정했으면). 잘못 올리기 쉽다 |
| B. **Center에 외부 확장 주소 칸** — 관리자가 넣고, 정의의 `allowed_hosts`·`allow_private_network` 안에서만 받는다 | 계약이 이미 약속한 것을 채운다. 정의 하나(해시 하나)로 환경을 넘는다. 키가 갈 수 있는 호스트는 여전히 **서명된 정의**가 정한다 | 칸·저장소 판·CON-07 칸이 는다 |
| C. B + Studio 로컬 덮어쓰기 | 설계자가 Center 없이 다른 주소로 시험한다 | 주소의 출처가 둘이 된다 — 요청서가 겪은 「개발 PC에서 운영계를 부른다」의 반대쪽 실수를 새로 만든다 |

## 결정

**B를 고른다. Studio 로컬 덮어쓰기(C)는 두지 않는다.**

- 관리자가 외부 확장의 주소를 Center에 넣는다(C7 `PUT /resources/extensions/{id}/address {base_url}`, CON-07 상세 「서버 주소」의 「주소 바꾸기...」). **정의를 넓히지 않는다** — 그 주소는 계약의 호스트 관문(`contracts.extension.resolve_host`)을 정의의 `allowed_hosts`·`allow_private_network`로 지나야 받는다. 정의 밖 호스트는 422다.
- 주소는 서비스 앱 주소와 **같은 명부**로 내려간다(C7 목록 → `DirectoryCache` → `AppDirectory.addresses`). 그래서 실행하는 쪽(Bot UI·서버 실행기·Studio)의 코드는 바뀌지 않는다 — 이미 명부를 먼저 본다.
- **환경은 연결한 Center가 정한다.** Studio는 연결한 Center의 명부를 따른다. 로컬 NowView로 시험하려면 로컬 Center(compose)에 붙는다.
- 덮어쓰지 않으면 지금처럼 정의의 `base_url`이다.

- CON-07에서는 상세의 「서버 주소」 칸이 맡는다(사람에게 물어 정했다) — 「기본값」/「Center에서 바꿈」 표시, 「주소 바꾸기...」 창은 정의의 허용 호스트를 한 줄로 보이고, 덮어썼으면 「기본값으로 되돌리기」. 목록·등록 흐름은 그대로다.
- 새 판을 등록해 허용 호스트가 바뀌어 덮어쓴 주소가 밖이 되면 **내려 주지 않고**(기본값) 사유를 남긴다. 지우지는 않는다.
- Center에서 이름이 풀리지 않는 주소(DNS)는 막지 않는다 — 부르는 곳에서는 풀릴 수 있고, 부를 때 같은 관문이 다시 본다.

## 결과

- 이 결정으로 쉬워지는 것: 정의를 한 벌로 둔다 — 예를 들어 `allowed_hosts: ["www.nowview.work", "localhost"]`, `allow_private_network: true`, `base_url: "https://www.nowview.work"`이고 로컬 Center만 주소를 `http://localhost:3000`으로 덮는다. 고정한 Bot이 두 환경에서 같은 해시를 본다.
- 어려워지거나 포기하는 것: 로컬 주소를 허용하려면 운영에도 쓰이는 정의에 `allow_private_network`를 켜야 한다(허용 호스트는 이름으로 정확히 맞으므로 넓어지는 것은 「그 이름이 사설 IP로 풀리는 경우」뿐이다). 싫으면 지금처럼 정의를 둘로 둔다 — 그 길은 막지 않는다.
- 다시 볼 조건: 한 Center가 두 환경을 함께 맡아야 하는 일이 생기면(배포 대상마다 다른 주소) — 그때는 주소를 배포 대상 쪽에 둘지 본다.
