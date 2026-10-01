# ADR-0003. 서버는 Linux 주, 클라이언트는 Windows 주

| 항목 | 값 |
| --- | --- |
| 상태 | 수락 |
| 날짜 | 2026-10-01 |
| 관련 | `docs/01-architecture.md` §5, `docs/04-setup.md` |

## 배경

자동화 대상 업무 PC는 대부분 Windows다. 프로토타입은 Linux(GNOME Wayland, AT-SPI)에서만 실제 검증했다. Windows 백엔드(pywinauto UIA)는 코드만 있고 실기 검증이 없다.

프로토타입에는 Linux 전용 가정이 곳곳에 있었다.
- `system_python = "/usr/bin/python3"`
- 자동 시작: `~/.config/autostart`, `systemd --user`
- Center 런처의 `os.killpg`
- 프로토타입 Center의 `file:///home/<사용자>/...` 절대경로 의존

## 결정

| 구성요소 | 주 환경 | 선택 환경 |
| --- | --- | --- |
| Center, 서비스 앱 (서버) | Linux | Windows |
| Studio, Bot, Worker (클라이언트) | Windows | Linux |

macOS는 지원하지 않는다.

- 클라이언트 기능은 **Windows에서 먼저** 만들고 확인한다. Linux는 같은 인터페이스의 두 번째 구현이다.
- CI는 Windows·Linux 둘 다 돌린다 (M1).
- OS 전용 기능은 인터페이스 뒤에 둔다 (`01-architecture` §5).

## 결과

- 쉬워지는 것: 실제 현장 환경과 개발 환경이 같아진다.
- 어려워지는 것: 데스크톱 조작·캡처·자동 시작을 Windows 기준으로 다시 확인해야 한다 (M1 스파이크 S1~S4). 서버 개발자와 클라이언트 개발자의 OS가 다를 수 있다.
- 다시 볼 조건: 현장 PC에 Linux 비중이 커지는 경우.
