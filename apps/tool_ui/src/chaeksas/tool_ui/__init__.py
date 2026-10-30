"""Tool UI — 확장이 기여한 도구를 띄우는 창 (ADR-0077, 화면 TOL-01·02).

PC 실행기는 BPM 프로세스를 받아 돌리고 Worker 프로세스를 띄운다. Tool UI는 **도구의 창**만 가진다 —
트레이가 없고, Center에 등록하지 않으며, **로컬 런타임을 띄우지 않고** PC 실행기가 띄운 것을
빌린다. 자세히: docs/06-screens/tool-ui.md.
"""
