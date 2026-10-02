"""WTS 세션 정보 (잠금 여부, 로그온 시각). 표준 라이브러리 + ctypes."""

import ctypes
import ctypes.wintypes as wt
import datetime as dt


class WTSINFOEX_LEVEL1_W(ctypes.Structure):  # noqa: N801
    _fields_ = [("SessionId", wt.ULONG), ("SessionState", ctypes.c_int), ("SessionFlags", wt.LONG),
                ("WinStationName", wt.WCHAR * 33), ("UserName", wt.WCHAR * 21), ("DomainName", wt.WCHAR * 18),
                ("LogonTime", ctypes.c_longlong), ("ConnectTime", ctypes.c_longlong),
                ("DisconnectTime", ctypes.c_longlong), ("LastInputTime", ctypes.c_longlong),
                ("CurrentTime", ctypes.c_longlong), ("IncomingBytes", wt.DWORD), ("OutgoingBytes", wt.DWORD),
                ("IncomingFrames", wt.DWORD), ("OutgoingFrames", wt.DWORD), ("IncomingCompressedBytes", wt.DWORD),
                ("OutgoingCompressedBytes", wt.DWORD)]


class WTSINFOEXW(ctypes.Structure):  # noqa: N801
    _fields_ = [("Level", wt.DWORD), ("Data", WTSINFOEX_LEVEL1_W)]  # ctypes가 8바이트 정렬을 맞춘다


def session_info() -> WTSINFOEX_LEVEL1_W:
    wtsapi = ctypes.windll.wtsapi32
    buf, n = ctypes.c_void_p(), wt.DWORD()
    sid = ctypes.windll.kernel32.WTSGetActiveConsoleSessionId()
    if not wtsapi.WTSQuerySessionInformationW(None, sid, 25, ctypes.byref(buf), ctypes.byref(n)):  # WTSSessionInfoEx
        raise OSError(ctypes.GetLastError(), "WTSQuerySessionInformation")
    try:
        return WTSINFOEXW.from_buffer_copy(ctypes.string_at(buf, ctypes.sizeof(WTSINFOEXW))).Data
    finally:
        wtsapi.WTSFreeMemory(buf)


def filetime(v: int) -> dt.datetime:
    return dt.datetime(1601, 1, 1) + dt.timedelta(microseconds=v // 10)


def locked() -> bool:
    return session_info().SessionFlags == 0  # WTS_SESSIONSTATE_LOCK


def seconds_since_logon() -> float:
    s = session_info()
    return (filetime(s.CurrentTime) - filetime(s.LogonTime)).total_seconds()
