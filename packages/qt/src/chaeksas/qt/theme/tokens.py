"""생성 파일: design/tokens.json에서 만든다. 직접 고치지 말고 원본을 고친 뒤 scripts/gen_tokens.py."""

from typing import Final

LIGHT: Final[dict[str, str]] = {
    "bg.canvas": "#F6F7F9",
    "bg.surface": "#FFFFFF",
    "bg.subtle": "#EEF0F3",
    "bg.inverse": "#1A1D23",
    "border.default": "#DDE1E6",
    "border.strong": "#B9C0CA",
    "text.primary": "#1A1D23",
    "text.secondary": "#4A5361",
    "text.muted": "#5F6875",
    "text.inverse": "#FFFFFF",
    "primary": "#2552C7",
    "primary.hover": "#1D44A8",
    "primary.subtle": "#E8EEFC",
    "primary.fg": "#FFFFFF",
    "focus": "#2552C7",
    "status.neutral.fg": "#4A5361",
    "status.neutral.bg": "#EEF0F3",
    "status.neutral.solid": "#7D8693",
    "status.active.fg": "#1D4ED8",
    "status.active.bg": "#E6EEFF",
    "status.active.solid": "#2563EB",
    "status.done.fg": "#166534",
    "status.done.bg": "#E5F5EA",
    "status.done.solid": "#16A34A",
    "status.failed.fg": "#B42318",
    "status.failed.bg": "#FDECEA",
    "status.failed.solid": "#DC2626",
    "danger.fg": "#FFFFFF",
    "status.waiting.fg": "#6D28D9",
    "status.waiting.bg": "#F1EAFE",
    "status.waiting.solid": "#7C3AED",
    "status.warning.fg": "#92400E",
    "status.warning.bg": "#FEF3E2",
    "status.warning.solid": "#D97706",
    "status.replayed.fg": "#0F6670",
    "status.replayed.bg": "#E3F5F6",
    "status.replayed.solid": "#0E9AA7",
}

DARK: Final[dict[str, str]] = {
    "bg.canvas": "#0F1115",
    "bg.surface": "#171A20",
    "bg.subtle": "#20242C",
    "bg.inverse": "#E8EAEE",
    "border.default": "#2C313A",
    "border.strong": "#3D444F",
    "text.primary": "#E8EAEE",
    "text.secondary": "#B4BBC6",
    "text.muted": "#939CA9",
    "text.inverse": "#0F1115",
    "primary": "#7AA2FF",
    "primary.hover": "#9AB8FF",
    "primary.subtle": "#1B2A4D",
    "primary.fg": "#0F1115",
    "focus": "#7AA2FF",
    "status.neutral.fg": "#B4BBC6",
    "status.neutral.bg": "#232831",
    "status.neutral.solid": "#8A93A1",
    "status.active.fg": "#93B4FF",
    "status.active.bg": "#1A2747",
    "status.active.solid": "#5B8CFF",
    "status.done.fg": "#7FD49A",
    "status.done.bg": "#15301F",
    "status.done.solid": "#34C266",
    "status.failed.fg": "#FF9A8F",
    "status.failed.bg": "#3A1A18",
    "status.failed.solid": "#F2564A",
    "danger.fg": "#0F1115",
    "status.waiting.fg": "#C4A6FF",
    "status.waiting.bg": "#2A1F45",
    "status.waiting.solid": "#9F7AEA",
    "status.warning.fg": "#F5B65C",
    "status.warning.bg": "#36260F",
    "status.warning.solid": "#E09A2B",
    "status.replayed.fg": "#6FD3DB",
    "status.replayed.bg": "#10302F",
    "status.replayed.solid": "#2BB5C0",
}

# 색 상수는 **밝게** 값이다. 테마를 따라야 하면 colors()를 쓴다.
BG_CANVAS: Final = "#F6F7F9"
BG_SURFACE: Final = "#FFFFFF"
BG_SUBTLE: Final = "#EEF0F3"
BG_INVERSE: Final = "#1A1D23"
BORDER_DEFAULT: Final = "#DDE1E6"
BORDER_STRONG: Final = "#B9C0CA"
TEXT_PRIMARY: Final = "#1A1D23"
TEXT_SECONDARY: Final = "#4A5361"
TEXT_MUTED: Final = "#5F6875"
TEXT_INVERSE: Final = "#FFFFFF"
PRIMARY: Final = "#2552C7"
PRIMARY_HOVER: Final = "#1D44A8"
PRIMARY_SUBTLE: Final = "#E8EEFC"
PRIMARY_FG: Final = "#FFFFFF"
FOCUS: Final = "#2552C7"
STATUS_NEUTRAL_FG: Final = "#4A5361"
STATUS_NEUTRAL_BG: Final = "#EEF0F3"
STATUS_NEUTRAL_SOLID: Final = "#7D8693"
STATUS_ACTIVE_FG: Final = "#1D4ED8"
STATUS_ACTIVE_BG: Final = "#E6EEFF"
STATUS_ACTIVE_SOLID: Final = "#2563EB"
STATUS_DONE_FG: Final = "#166534"
STATUS_DONE_BG: Final = "#E5F5EA"
STATUS_DONE_SOLID: Final = "#16A34A"
STATUS_FAILED_FG: Final = "#B42318"
STATUS_FAILED_BG: Final = "#FDECEA"
STATUS_FAILED_SOLID: Final = "#DC2626"
DANGER_FG: Final = "#FFFFFF"
STATUS_WAITING_FG: Final = "#6D28D9"
STATUS_WAITING_BG: Final = "#F1EAFE"
STATUS_WAITING_SOLID: Final = "#7C3AED"
STATUS_WARNING_FG: Final = "#92400E"
STATUS_WARNING_BG: Final = "#FEF3E2"
STATUS_WARNING_SOLID: Final = "#D97706"
STATUS_REPLAYED_FG: Final = "#0F6670"
STATUS_REPLAYED_BG: Final = "#E3F5F6"
STATUS_REPLAYED_SOLID: Final = "#0E9AA7"

SPACE_0: Final = 0
SPACE_0_5: Final = 2
SPACE_1: Final = 4
SPACE_2: Final = 8
SPACE_3: Final = 12
SPACE_4: Final = 16
SPACE_5: Final = 20
SPACE_6: Final = 24
SPACE_8: Final = 32
SPACE_10: Final = 40
SPACE_12: Final = 48
SPACE_16: Final = 64
RADIUS_SM: Final = 4
RADIUS_MD: Final = 6
RADIUS_LG: Final = 8
RADIUS_XL: Final = 12
RADIUS_FULL: Final = 9999
SIZE_CONTROL_SM: Final = 28
SIZE_CONTROL_MD: Final = 32
SIZE_CONTROL_LG: Final = 40
SIZE_ROW_COMPACT: Final = 32
SIZE_ROW_DEFAULT: Final = 36
SIZE_NAV_WIDTH: Final = 232
SIZE_NAV_COLLAPSED: Final = 64
SIZE_TOPBAR_HEIGHT: Final = 56

FONT_FAMILY_SANS: Final = "\"Pretendard Variable\", Pretendard, \"Malgun Gothic\", \"Apple SD Gothic Neo\", \"Noto Sans KR\", system-ui, sans-serif"  # noqa: E501
FONT_FAMILY_MONO: Final = "\"JetBrains Mono\", D2Coding, Consolas, \"Noto Sans Mono\", monospace"
FONT_SIZE_CAPTION: Final = 12
FONT_SIZE_BODY_SM: Final = 13
FONT_SIZE_BODY: Final = 14
FONT_SIZE_BODY_LG: Final = 16
FONT_SIZE_H3: Final = 18
FONT_SIZE_H2: Final = 20
FONT_SIZE_H1: Final = 24
FONT_SIZE_DISPLAY: Final = 30
FONT_WEIGHT_REGULAR: Final = 400
FONT_WEIGHT_MEDIUM: Final = 500
FONT_WEIGHT_SEMIBOLD: Final = 600
FONT_WEIGHT_BOLD: Final = 700
FONT_LINE_BODY: Final = 1.5
FONT_LINE_HEADING: Final = 1.3

SHADOW_SM: Final = "0 1px 2px rgba(16,24,40,0.06)"
SHADOW_MD: Final = "0 4px 12px rgba(16,24,40,0.10)"
SHADOW_LG: Final = "0 12px 32px rgba(16,24,40,0.16)"
MOTION_FAST: Final = 120
MOTION_BASE: Final = 200
MOTION_EASING: Final = "cubic-bezier(0.2, 0, 0, 1)"

#: 상태 표기 → 상태 색 이름 (`docs/07-style-guide.md` §2). 표기는 이 표에 있는 것만 쓴다.
STATUS_MAP: Final[dict[str, dict[str, str]]] = {
    "실행·노드": {
        "대기": "neutral",
        "실행 중": "active",
        "기다리는 중": "waiting",
        "완료": "done",
        "실패": "failed",
        "재생됨": "replayed",
        "취소됨": "neutral",
    },
    "Bot": {
        "대기": "neutral",
        "대기열": "waiting",
        "실행 중": "active",
        "결재 대기": "waiting",
        "확인 대기": "waiting",
        "오류": "failed",
        "실행 불가": "failed",
        "감시 중": "active",
        "수동 실행 전용": "neutral",
        "비활성": "neutral",
    },
    "Bot UI": {
        "연결됨": "done",
        "연결 끊김": "warning",
        "등록 전": "neutral",
        "키 폐기됨": "failed",
        "키 만료": "failed",
        "비활성": "neutral",
    },
    "Worker 프로세스": {
        "실행 중": "done",
        "요청 처리 중": "active",
        "셀렉터 등록 중": "active",
        "다시 띄우는 중": "warning",
        "멈춤": "failed",
        "Bot UI가 꺼져 있음": "warning",
        "꺼 둠": "neutral",
        "예약됨": "active",
    },
    "서버 실행기": {
        "동작": "done",
        "일시 중지": "neutral",
        "정리 중": "active",
        "오류": "failed",
        "오프라인": "warning",
    },
    "API 키": {
        "사용 중": "done",
        "만료": "warning",
        "폐기됨": "neutral",
    },
    "결재": {
        "대기": "waiting",
        "답함": "done",
        "시간 초과": "warning",
        "회수됨": "neutral",
    },
    "작업": {
        "대기": "neutral",
        "전달됨": "active",
        "대기열": "waiting",
        "수락": "done",
        "거절": "failed",
        "만료": "warning",
        "취소됨": "neutral",
    },
    "로케이터": {
        "사용 중": "done",
        "검증 전": "waiting",
        "대체됨": "neutral",
    },
    "서비스 앱": {
        "정상": "done",
        "저하": "warning",
        "응답 없음": "failed",
        "확인 전": "neutral",
    },
    "사전 점검": {
        "정상": "done",
        "경고": "warning",
        "실행 불가": "failed",
    },
    "확장": {
        "켜짐": "done",
        "꺼짐": "neutral",
        "호환 안 됨": "warning",
        "필요하지만 없음": "failed",
    },
    "온라인": {
        "온라인": "done",
        "오프라인": "warning",
    },
    "패키지": {
        "후보": "waiting",
        "승인됨": "done",
        "지원 종료": "warning",
        "철회": "failed",
        "로컬만": "neutral",
    },
    "서명": {
        "확인됨": "done",
        "서명 없음": "warning",
        "서명 불일치": "failed",
        "서명 확인 안 됨": "failed",
    },
    "Bot 준비": {
        "준비됨": "done",
        "서비스 앱 키 없음": "failed",
        "확장 없음": "failed",
        "확장 꺼짐": "neutral",
        "사전 점검 실행 불가": "failed",
    },
    "서비스 앱 키 참조": {
        "정상": "done",
        "없음": "failed",
        "거부됨": "failed",
        "만료": "warning",
        "폐기됨": "failed",
        "확인 전": "neutral",
        "등록 필요": "failed",
    },
    "UI 세션": {
        "성공": "done",
        "전환": "waiting",
        "실패": "failed",
        "진행 중": "active",
        "시험": "neutral",
    },
    "배치 결정": {
        "적용": "done",
        "거부": "failed",
    },
}


def colors(*, dark: bool) -> dict[str, str]:
    """테마에 맞는 색 표."""
    return DARK if dark else LIGHT
