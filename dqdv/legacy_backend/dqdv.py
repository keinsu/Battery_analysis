# -*- coding: utf-8 -*-
"""
dqdv.py
사이클별 충/방전 dQ/dV, dV/dQ 분석.

절차
----
1. 해당 사이클/충방전 방향의 raw (Voltage, Capacity) 를 추출한다.
   방전 용량은 부호를 양수로 맞춰 사용한다 (구간 내에서 0 -> 최대로 누적되는 값 그대로 사용).
2. Voltage 축을 기준으로 균일 간격 500 포인트 그리드를 만들고, Capacity를 그 위에
   보간(interp)한다 (전압은 충전시 단조증가, 방전시 단조감소하므로 정렬 후 보간).
3. (옵션) Savitzky-Golay 필터로 스무딩.
4. dQ/dV = dCapacity/dVoltage (np.gradient) 계산.
5. dV/dQ 는 동일한 근거 데이터로 Capacity 축 균일 그리드(500pt)에 Voltage를 보간하여
   별도로 dV/dQ = dVoltage/dCapacity 를 계산한다 (dQ/dV의 단순 역수는 노이즈가 커질 수 있어
   지양하고, 각각을 해당 축 기준으로 독립적으로 스무딩/미분한다).
6. scipy.signal.find_peaks로 피크(전압) 위치를 검출한다.
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from scipy.signal import savgol_filter, find_peaks

from .pne_parser import TYPE_CHARGE, TYPE_DISCHARGE, TYPE_REST


def get_qv_curve(df: pd.DataFrame, cycle: int, direction: str) -> pd.DataFrame:
    """
    direction: 'charge' 또는 'discharge'
    반환: columns ['Voltage_V', 'Capacity_mAh'] (원본 raw, 정렬됨, 중복전압 제거 전)
    """
    type_std = TYPE_CHARGE if direction == "charge" else TYPE_DISCHARGE
    seg = df[(df["Cycle"] == cycle) & (df["TypeStd"] == type_std)].sort_values("_row")
    if seg.empty:
        return pd.DataFrame(columns=["Voltage_V", "Capacity_mAh"])
    out = seg[["Voltage_V", "Capacity_mAh"]].dropna().reset_index(drop=True)
    return out


def _dedup_monotonic(x: np.ndarray, y: np.ndarray):
    """x를 오름차순 정렬하고, 중복 x값은 평균 y로 합쳐 interp1d에 안전하게 만든다."""
    order = np.argsort(x)
    x, y = x[order], y[order]
    x_unique, inv = np.unique(x, return_inverse=True)
    y_mean = np.zeros_like(x_unique, dtype=float)
    counts = np.zeros_like(x_unique, dtype=float)
    np.add.at(y_mean, inv, y)
    np.add.at(counts, inv, 1)
    y_mean = y_mean / counts
    return x_unique, y_mean


def _cc_region_only(v: np.ndarray, q: np.ndarray, upper_voltage_v: float | None, tol_v: float = 0.002):
    """
    충전 곡선에서 CC(정전류) 구간만 잘라 반환한다. CV(정전압) 구간은 전압이 거의 일정한 채
    전류만 줄어들어 dV≈0이 되고, dQ/dV = dQ/dV가 비정상적으로 치솟아(스파이크) 진짜 상변화
    피크를 가려버리므로, dQ/dV/피크 계산에서는 제외한다.

    upper_voltage_v가 주어지면 그 값을, 없으면 곡선의 최대전압을 상한전압으로 보고
    (cycle_metrics._cc_cv_split과 동일 로직) 그 지점까지만 사용한다.
    """
    if len(v) < 5:
        return v, q
    target_v = upper_voltage_v if upper_voltage_v is not None else np.nanmax(v)
    idx_candidates = np.where(v >= (target_v - tol_v))[0]
    if len(idx_candidates) == 0:
        return v, q
    cutoff = idx_candidates[0]
    if cutoff < 4:  # 너무 앞부분이면(비정상 데이터) 자르지 않음
        return v, q
    return v[: cutoff + 1], q[: cutoff + 1]


def compute_dqdv(
    df: pd.DataFrame,
    cycle: int,
    direction: str,
    n_points: int = 500,
    smooth: bool = True,
    smooth_window: int | None = None,
    smooth_polyorder: int = 3,
    peak_prominence: float | None = None,
    peak_min_distance: int = 5,
    peak_prominence_pct: float | None = None,
    upper_voltage_v: float | None = None,
):
    """
    한 사이클의 충전 또는 방전 dQ/dV, dV/dQ를 계산한다.

    upper_voltage_v: 충전 방향일 때, CC/CV 전환점을 이 전압 기준으로 판단해 CV(정전압) 구간을
                      dQ/dV 계산에서 제외한다. None이면 그 사이클 충전곡선의 최대전압을 사용.
                      (cycle_metrics.compute_cycle_summary와 동일 기준을 넘겨주면 일관성 있음)

    반환 dict:
        voltage_grid, capacity_on_vgrid, dqdv,
        capacity_grid, voltage_on_qgrid, dvdq,
        peaks_dqdv (전압, dqdv값 리스트),
        peaks_dvdq (용량, dvdq값 리스트)
    """
    raw = get_qv_curve(df, cycle, direction)
    if raw.empty or len(raw) < 5:
        return None

    v = raw["Voltage_V"].values.astype(float)
    q = raw["Capacity_mAh"].values.astype(float)

    if direction == "charge":
        v, q = _cc_region_only(v, q, upper_voltage_v)
        if len(v) < 5:
            return None

    # ---- 1) Voltage 기준 균일 그리드에 Capacity 보간 ----
    v_u, q_u = _dedup_monotonic(v, q)
    if len(v_u) < 5:
        return None
    v_grid = np.linspace(v_u.min(), v_u.max(), n_points)
    q_on_vgrid = np.interp(v_grid, v_u, q_u)

    # ---- 2) Capacity 기준 균일 그리드에 Voltage 보간 (dV/dQ 용) ----
    q_u2, v_u2 = _dedup_monotonic(q, v)
    q_grid = np.linspace(q_u2.min(), q_u2.max(), n_points)
    v_on_qgrid = np.interp(q_grid, q_u2, v_u2)

    win = smooth_window
    if win is None:
        win = max(11, (n_points // 25) | 1)  # 홀수로 보정
    win = min(win, n_points - (1 - n_points % 2))
    if win % 2 == 0:
        win += 1
    win = max(5, win)

    q_s = q_on_vgrid.copy()
    v_s = v_on_qgrid.copy()
    if smooth and n_points > win:
        try:
            q_s = savgol_filter(q_on_vgrid, window_length=win, polyorder=min(smooth_polyorder, win - 1))
            v_s = savgol_filter(v_on_qgrid, window_length=win, polyorder=min(smooth_polyorder, win - 1))
        except Exception:
            pass  # 스무딩 실패시 원본 유지

    dqdv = np.gradient(q_s, v_grid)
    dvdq = np.gradient(v_s, q_grid)

    if smooth and n_points > win:
        try:
            dqdv = savgol_filter(dqdv, window_length=win, polyorder=min(smooth_polyorder, win - 1))
            dvdq = savgol_filter(dvdq, window_length=win, polyorder=min(smooth_polyorder, win - 1))
        except Exception:
            pass

    # ---- 피크 검출 (충전/방전 모두 |dqdv| 기준 양의 피크로 검출되도록 절대값 사용) ----
    # peak_prominence_pct: 신호 진폭(최대-최소) 대비 몇 %를 "피크"로 볼지 (작을수록 더 많은/약한 피크 검출)
    # 보간/미분의 경계효과로 배열의 맨 앞/뒤 끝에서 인위적인 스파이크가 생길 수 있어, 민감도를
    # 낮게(더 많은 피크 검출) 설정했을 때 그런 가짜 피크가 실제 피크보다 두드러지지 않도록
    # 양 끝 일부(edge_margin)는 피크 후보에서 제외한다.
    edge_margin = max(2, int(n_points * 0.01))
    pct = peak_prominence_pct if peak_prominence_pct is not None else 0.05
    prom = peak_prominence
    dqdv_for_peak = dqdv if direction == "charge" else -dqdv
    if prom is None:
        prom = pct * (np.nanmax(np.abs(dqdv_for_peak)) - np.nanmin(np.abs(dqdv_for_peak)) + 1e-9)
    peak_idx, _ = find_peaks(dqdv_for_peak, prominence=prom, distance=peak_min_distance)
    peak_idx = peak_idx[(peak_idx >= edge_margin) & (peak_idx < len(dqdv_for_peak) - edge_margin)]

    dvdq_for_peak = dvdq if direction == "charge" else -dvdq
    prom_v = pct * (np.nanmax(np.abs(dvdq_for_peak)) - np.nanmin(np.abs(dvdq_for_peak)) + 1e-9)
    peak_idx_v, _ = find_peaks(dvdq_for_peak, prominence=prom_v, distance=peak_min_distance)
    peak_idx_v = peak_idx_v[(peak_idx_v >= edge_margin) & (peak_idx_v < len(dvdq_for_peak) - edge_margin)]

    return dict(
        voltage_grid=v_grid,
        capacity_on_vgrid=q_s,
        dqdv=dqdv,
        capacity_grid=q_grid,
        voltage_on_qgrid=v_s,
        dvdq=dvdq,
        peak_voltage=v_grid[peak_idx],
        peak_dqdv=dqdv[peak_idx],
        peak_capacity=q_grid[peak_idx_v],
        peak_dvdq=dvdq[peak_idx_v],
    )


def compute_all_cycle_peaks(
    df: pd.DataFrame,
    cycles: list,
    n_points: int = 500,
    smooth: bool = True,
    peak_prominence_pct: float | None = None,
    upper_voltage_v: float | None = None,
) -> list:
    """
    전체 사이클에 대해 충/방전 dQ/dV 피크(전압, 크기)를 계산해 리스트로 반환한다.
    (사이클별 피크 변화 추이 차트 및 일괄 내보내기용)

    반환: [{"cycle": int, "phase": "charge"/"discharge", "peak_voltage": float, "peak_dqdv": float}, ...]
    데이터 구조가 예상과 달라 특정 사이클 계산이 실패해도 그 사이클만 건너뛰고 계속 진행한다.
    """
    out = []
    for cyc in cycles:
        for direction in ("charge", "discharge"):
            try:
                r = compute_dqdv(df, cyc, direction, n_points=n_points, smooth=smooth,
                                  peak_prominence_pct=peak_prominence_pct, upper_voltage_v=upper_voltage_v)
            except Exception:  # noqa: BLE001
                r = None
            if r is None:
                continue
            for v, dq in zip(r["peak_voltage"], r["peak_dqdv"]):
                out.append({"cycle": cyc, "phase": direction, "peak_voltage": float(v), "peak_dqdv": float(dq)})
    return out


def compute_multi_cycle_dqdv(
    df: pd.DataFrame,
    cycles: list,
    direction: str,
    n_points: int = 500,
    smooth: bool = True,
    peak_prominence_pct: float | None = None,
    upper_voltage_v: float | None = None,
) -> list:
    """
    선택된 여러 사이클의 dQ/dV 곡선을 한 번에 계산한다 (사이클 간 비교/오버레이용).

    반환: [{"cycle": int, "voltage_grid": ndarray, "dqdv": ndarray}, ...]
    (계산 실패한 사이클은 건너뜀)
    """
    out = []
    for cyc in cycles:
        try:
            r = compute_dqdv(df, cyc, direction, n_points=n_points, smooth=smooth,
                              peak_prominence_pct=peak_prominence_pct, upper_voltage_v=upper_voltage_v)
        except Exception:  # noqa: BLE001
            r = None
        if r is None:
            continue
        out.append({"cycle": cyc, "voltage_grid": r["voltage_grid"], "dqdv": r["dqdv"]})
    return out


def compute_multi_cycle_rest_dvdt(
    df: pd.DataFrame,
    cycles: list,
    after: str = "charge",
    n_points: int = 200,
    smooth: bool = True,
) -> list:
    """
    선택된 여러 사이클의 휴지 구간 dV/dt(전압 이완) 곡선을 한 번에 계산한다 (사이클 간 비교/오버레이용).

    반환: [{"cycle": int, "time_min": ndarray, "dvdt_mV_per_min": ndarray,
            "rest_duration_s": float, "delta_v_v": float}, ...]
    (해당 휴지 구간이 없거나 계산 실패한 사이클은 건너뜀)
    """
    out = []
    for cyc in cycles:
        try:
            r = compute_rest_dvdt(df, cyc, after=after, n_points=n_points, smooth=smooth)
        except Exception:  # noqa: BLE001
            r = None
        if r is None:
            continue
        out.append({
            "cycle": cyc,
            "time_min": r["time_min"],
            "dvdt_mV_per_min": r["dvdt_mV_per_min"],
            "rest_duration_s": r["rest_duration_s"],
            "delta_v_v": r["delta_v_v"],
        })
    return out


def compute_rest_dvdt(
    df: pd.DataFrame,
    cycle: int,
    after: str = "charge",
    n_points: int = 200,
    smooth: bool = True,
):
    """
    충전 직후(after='charge') 또는 방전 직후(after='discharge') 이어지는 휴지(REST) 구간의
    전압 이완(relaxation) 곡선과 dV/dt(mV/min)를 계산한다.

    같은 Cycle 번호 안에 충전-휴지-방전-휴지가 순서대로 들어있다는 전제 하에, 지정한 타입의
    마지막 행 바로 다음부터 이어지는 연속된 REST 구간만 사용한다 (그 사이 다른 타입이 끼면
    거기서 멈춘다).

    반환 dict: time_s, time_min, voltage_v, dvdt_mV_per_min, rest_duration_s, delta_v_v
    또는 (해당 휴지 구간이 없거나 데이터가 부족하면) None
    """
    type_target = TYPE_CHARGE if after == "charge" else TYPE_DISCHARGE
    seg_all = df[df["Cycle"] == cycle].sort_values("_row")
    if seg_all.empty:
        return None

    target_rows = seg_all[seg_all["TypeStd"] == type_target]
    if target_rows.empty:
        return None
    last_target_row = target_rows["_row"].max()

    after_rows = seg_all[seg_all["_row"] > last_target_row]
    if after_rows.empty:
        return None

    types_arr = after_rows["TypeStd"].values
    if len(types_arr) == 0 or types_arr[0] != TYPE_REST:
        return None
    non_rest_idx = np.where(types_arr != TYPE_REST)[0]
    end = int(non_rest_idx[0]) if len(non_rest_idx) else len(types_arr)
    rest_df = after_rows.iloc[:end]
    if len(rest_df) < 2:
        return None

    if "StepTime_s" in rest_df.columns and rest_df["StepTime_s"].notna().any():
        t_raw = rest_df["StepTime_s"].values.astype(float)
    else:
        t_raw = np.arange(len(rest_df), dtype=float)
    v_raw = rest_df["Voltage_V"].values.astype(float)

    # 스텝 경계 아티팩트 제거: 몇몆 장비는 REST 구간의 마지막 행에서 StepTime이 다음 스텝의
    # 시작을 나타내며 0으로 리셋되어 기록되는 경우가 있다. 시간이 더 이상 증가하지 않는
    # 지점부터는 잘라낸다 (첫 값은 항상 유지).
    t_list, v_list = [t_raw[0]], [v_raw[0]]
    for i in range(1, len(t_raw)):
        if np.isnan(t_raw[i]) or np.isnan(v_raw[i]):
            continue
        if t_raw[i] > t_list[-1]:
            t_list.append(t_raw[i])
            v_list.append(v_raw[i])
        else:
            break
    t = np.array(t_list, dtype=float)
    v = np.array(v_list, dtype=float)
    if len(t) < 2:
        return None

    if len(t) < 4:
        # 포인트가 매우 적으면(짧은 휴지 로깅) 스무딩 없이 선형 보간만 사용
        n_pts = max(2, min(n_points, 20))
        t_grid = np.linspace(t.min(), t.max(), n_pts)
        v_grid = np.interp(t_grid, t, v)
        v_s = v_grid
        t_min = t_grid / 60.0
        dvdt = np.gradient(v_s * 1000.0, t_min)
        return dict(
            time_s=t_grid, time_min=t_min, voltage_v=v_s, dvdt_mV_per_min=dvdt,
            rest_duration_s=float(t.max() - t.min()), delta_v_v=float(v[-1] - v[0]),
        )

    t_u, v_u = _dedup_monotonic(t, v)
    if len(t_u) < 2:
        return None

    n_pts = max(10, min(n_points, len(t_u) * 3))
    t_grid = np.linspace(t_u.min(), t_u.max(), n_pts)
    v_grid = np.interp(t_grid, t_u, v_u)

    v_s = v_grid.copy()
    if smooth and n_pts > 7:
        win = max(5, (n_pts // 15) | 1)
        win = min(win, n_pts - (1 - n_pts % 2))
        if win % 2 == 0:
            win += 1
        if win >= 5 and n_pts > win:
            try:
                v_s = savgol_filter(v_grid, window_length=win, polyorder=min(3, win - 1))
            except Exception:  # noqa: BLE001
                pass

    t_min = t_grid / 60.0
    dvdt = np.gradient(v_s * 1000.0, t_min)  # mV / min

    return dict(
        time_s=t_grid,
        time_min=t_min,
        voltage_v=v_s,
        dvdt_mV_per_min=dvdt,
        rest_duration_s=float(t_u.max() - t_u.min()),
        delta_v_v=float(v_u[-1] - v_u[0]),
    )
