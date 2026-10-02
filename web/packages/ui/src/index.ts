/**
 * 공용 구성요소 (ADR-0017 §4, 스타일 가이드 §3).
 *
 * 이름은 Qt 위젯(`packages/qt`)과 **같게** 둔다 — 화면 설계서가 둘 다를 가리킬 수 있어야 한다.
 * 색·크기·간격은 토큰(`tokens.css`)만 쓰고 값을 코드에 적지 않는다.
 *
 * 아직 없는 것 (실제 화면과 함께 M2): FilterBar, Toast, KeyReveal, RunTimeline, LogView,
 * Tabs·SideNav, 결재·확인 창.
 */
export { Button, type ButtonProps, type ButtonSize, type ButtonVariant } from "./components/Button";
export { StatusBadge, type StatusBadgeProps } from "./components/StatusBadge";
export { DataTable, type Column, type DataTableProps } from "./components/DataTable";
export { Field, type FieldProps } from "./components/Field";
export { ConfirmDialog, Dialog, type ConfirmDialogProps, type DialogProps } from "./components/Dialog";
export { EmptyState, type EmptyStateProps } from "./components/EmptyState";
export { ErrorBanner, type ErrorBannerProps } from "./components/ErrorBanner";
export { STATUS_MAP, STATUS_TOKENS, statusToken, type StatusGroup, type StatusToken } from "./status-map";
export { cn } from "./cn";
