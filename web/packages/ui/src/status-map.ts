// 생성 파일: design/tokens.json에서 만든다. 직접 고치지 말고 원본을 고친 뒤 scripts/gen_tokens.py

/** 상태 색 7가지 (스타일 가이드 §2-2). */
export const STATUS_TOKENS = ["neutral", "active", "done", "failed", "waiting", "warning", "replayed"] as const;

export type StatusToken = (typeof STATUS_TOKENS)[number];

/** 상태 표기 → 상태 색. 열쇠는 화면 설계서(`docs/06-screens`)의 묶음 이름이다. */
export const STATUS_MAP = {
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
} as const satisfies Record<string, Record<string, StatusToken>>;

export type StatusGroup = keyof typeof STATUS_MAP;

/** 그 묶음의 표기에 맞는 상태 색. 모르는 표기는 `undefined` — 화면은 회색으로 보이고,
 *  계약의 상태 값이 열린 문자열이라(계약 원칙 10) 모르는 값 하나로 화면이 깨지지 않는다. */
export function statusToken(group: StatusGroup, label: string): StatusToken | undefined {
  return (STATUS_MAP[group] as Record<string, StatusToken>)[label];
}
