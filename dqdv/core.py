"""Cycling import and adapter for the unchanged user-supplied dQ/dV module."""
import io
import re
import numpy as np
import pandas as pd
from scipy.signal import find_peaks
from legacy_backend.dqdv import compute_dqdv, get_qv_curve, _cc_region_only


def read_csv(data):
    for encoding in ('utf-8-sig', 'cp949', 'utf-16'):
        try:
            text = data.decode(encoding)
            frame = pd.read_csv(io.StringIO(text))
            if len(frame.columns) < 2:
                raise ValueError('쉼표로 구분된 CSV가 필요합니다.')
            return frame, encoding
        except UnicodeError:
            continue
    raise ValueError('지원하는 인코딩으로 CSV를 읽을 수 없습니다.')


def elapsed(value):
    match = re.fullmatch(r'\s*(?:(\d+)d\s+)?(\d+):(\d+):(\d+(?:\.\d+)?)', str(value))
    if not match:
        return np.nan
    day, hour, minute, second = match.groups()
    return int(day or 0)*86400 + int(hour)*3600 + int(minute)*60 + float(second)


def normalize(raw, mapping, units, positive_charge=True):
    """Capacity must be positive, increasing within each step; no hidden abs conversion."""
    df = pd.DataFrame(index=raw.index)
    df['row'] = np.arange(len(raw)) + 2
    for key in ('channel', 'cycle', 'step', 'type'):
        df[key] = raw[mapping[key]].fillna('미지정').astype(str) if mapping.get(key) else '미지정'
    for key, scale in [('voltage', {'V':1, 'mV':.001, 'µV':.000001}[units['voltage']]),
                       ('current', {'A':1, 'mA':.001}[units['current']]),
                       ('capacity', {'Ah':1, 'mAh':.001}[units['capacity']])]:
        df[key] = pd.to_numeric(raw[mapping[key]], errors='coerce') * scale
    df['time'] = raw[mapping['time']].map(elapsed) if mapping.get('time') else np.nan
    if mapping.get('time') and units.get('time') == 's':
        df['time'] = pd.to_numeric(raw[mapping['time']], errors='coerce')
    aliases = {'충전':'charge','charge':'charge','chg':'charge','방전':'discharge',
               'discharge':'discharge','dchg':'discharge','휴지':'rest','rest':'rest','loop':'other',
               'cc charge':'charge','cv charge':'charge','cc discharge':'discharge','cv discharge':'discharge'}
    direction = df['type'].str.strip().str.lower().map(aliases)
    signed = df.current * (1 if positive_charge else -1)
    inferred = pd.Series(np.where(signed>1e-9,'charge',np.where(signed< -1e-9,'discharge','rest')),index=df.index)
    df['direction'] = direction.fillna(inferred)
    df['sign_conflict'] = ((direction=='charge') & (signed< -1e-9)) | ((direction=='discharge') & (signed>1e-9))
    boundary = df[['channel','cycle','step','type','direction']].ne(df[['channel','cycle','step','type','direction']].shift()).any(axis=1)
    boundary |= df.capacity.diff() < -1e-9
    df['segment'] = boundary.cumsum()
    df['time_reversal'] = (df.time.diff()<0) & ~boundary
    return df


def segment_table(df):
    return df.groupby('segment',sort=False).agg(channel=('channel','first'),cycle=('cycle','first'),
        step=('step','first'),direction=('direction','first'),rows=('row','size'),
        first_row=('row','first'),last_row=('row','last'),v_min=('voltage','min'),v_max=('voltage','max'),
        q_end_Ah=('capacity','last'),time_reversals=('time_reversal','sum'),sign_conflicts=('sign_conflict','sum')).reset_index()



def legacy_frame(df):
    """Map normalized V/Ah data to the supplied module's V/mAh schema."""
    if df.channel.nunique() > 1:
        raise ValueError('한 채널을 선택한 뒤 계산하세요.')
    return pd.DataFrame({'Cycle':df.cycle, 'TypeStd':df.direction.map(
        {'charge':'CHARGE','discharge':'DISCHARGE','rest':'REST'}).fillna('OTHER'),
        'Voltage_V':df.voltage, 'Capacity_mAh':df.capacity*1000, '_row':df.row})


def detect_extrema(axis, values, prominence_pct=.05, min_distance=5):
    """Return both local maxima and minima on a derivative curve."""
    axis=np.asarray(axis,dtype=float);values=np.asarray(values,dtype=float)
    finite=np.isfinite(axis)&np.isfinite(values)
    axis,values=axis[finite],values[finite]
    if len(values)<5:return (np.array([]),np.array([]),np.array([]),np.array([]))
    edge=max(2,int(len(values)*.01))
    prominence=float(prominence_pct)*(np.nanmax(values)-np.nanmin(values)+1e-9)
    maxima,_=find_peaks(values,prominence=prominence,distance=min_distance)
    minima,_=find_peaks(-values,prominence=prominence,distance=min_distance)
    maxima=maxima[(maxima>=edge)&(maxima<len(values)-edge)]
    minima=minima[(minima>=edge)&(minima<len(values)-edge)]
    return axis[maxima],values[maxima],axis[minima],values[minima]


def calculate_cycle(df, cycle, direction, **settings):
    frame=legacy_frame(df)
    raw=get_qv_curve(frame,cycle,direction)
    report={'cycle':cycle,'direction':direction,'valid_raw_rows':len(raw)}
    # The supplied backend does not handle infinity; report it, never silently alter it.
    if not np.isfinite(raw.to_numpy(float)).all():
        return None, dict(report, reason='무한대 입력값: 계산 제외')
    if len(raw):
        v,q=raw.Voltage_V.to_numpy(),raw.Capacity_mAh.to_numpy()
        if direction=='charge':
            v,q=_cc_region_only(v,q,settings.get('upper_voltage_v'))
        span=float(np.nanmax(v)-np.nanmin(v)) if len(v) else 0.0
        report.update(cv_excluded_rows=len(raw)-len(v), unique_voltages=len(np.unique(v)),voltage_span_V=span)
    result=compute_dqdv(frame,cycle,direction,**settings)
    if result is not None:
        sensitivity=settings.get('peak_prominence_pct') or .05
        dq_peak_x,dq_peak_y,dq_valley_x,dq_valley_y=detect_extrema(result['voltage_grid'],result['dqdv'],sensitivity)
        dv_peak_x,dv_peak_y,dv_valley_x,dv_valley_y=detect_extrema(result['capacity_grid'],result['dvdq'],sensitivity)
        result.update(dqdv_peak_voltage=dq_peak_x,dqdv_peak_value=dq_peak_y,dqdv_valley_voltage=dq_valley_x,dqdv_valley_value=dq_valley_y,
                      dvdq_peak_capacity=dv_peak_x,dvdq_peak_value=dv_peak_y,dvdq_valley_capacity=dv_valley_x,dvdq_valley_value=dv_valley_y)
    report['reason']='계산 완료' if result is not None else '유효 행 또는 고유 전압 5개 미만'
    return result, report


def calculate_step(df, step, direction, **settings):
    """Run the unchanged cycle backend on one selected charge/discharge step."""
    selected=df[(df.step.astype(str)==str(step))&(df.direction==direction)].copy()
    selected['cycle']='__selected_step__'
    result,report=calculate_cycle(selected,'__selected_step__',direction,**settings)
    report['step']=str(step)
    return result,report


def lowest_current_step(df, direction):
    """Return the last step among those with the lowest representative current magnitude."""
    subset=df[df.direction==direction].copy()
    if subset.empty:return ''
    subset['_abs_current']=subset.current.abs()
    summary=subset.groupby('step',sort=False).agg(current_magnitude=('_abs_current','median'),last_row=('row','max')).reset_index()
    summary=summary[np.isfinite(summary.current_magnitude)]
    if summary.empty:return ''
    minimum=summary.current_magnitude.min()
    candidates=summary[np.isclose(summary.current_magnitude,minimum,rtol=1e-9,atol=1e-12)]
    return str(candidates.sort_values('last_row').iloc[-1]['step'])
