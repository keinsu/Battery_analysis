import json
import hashlib
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from core import read_csv, normalize, segment_table, calculate_cycle
from view import select_cycles, add_curves, configure_chart, CHART_CONFIG

st.set_page_config(page_title='dQ/dV · Cycling', layout='wide')
st.title('dQ/dV · Cycling')
st.caption('충방전 기록으로 cycle별 변화를 비교합니다. 소재와 C-rate 입력은 필요하지 않습니다.')
file=st.file_uploader('Cycling CSV',type=['csv'])
if file is None:
    st.info('CSV 파일을 선택하면 열·단위 설정과 구간 목록이 표시됩니다.')
    st.stop()
@st.cache_data
def load(data):return read_csv(data)
try:raw,encoding=load(file.getvalue())
except Exception as exc:
    st.error(str(exc));st.stop()
st.caption(f'{len(raw):,}행 · {len(raw.columns)}열 · {encoding}')
with st.expander('열·단위 매핑 — 파일마다 확인',expanded=True):
    defaults={'channel':'Channel','cycle':'TotCycle','step':'StepNo','type':'Type','time':'TotTime(H:M:S)',
              'voltage':'Voltage(V)','current':'Current(mA)','capacity':'Capacity(mAh)'}
    labels={'channel':'채널','cycle':'Cycle','step':'Step','type':'동작 종류','time':'전체 시간','voltage':'전압','current':'전류','capacity':'Step 용량'}
    mapping={}
    cols=st.columns(4)
    for n,(key,default) in enumerate(defaults.items()):
        optional=key in ('channel','step','type','time')
        options=(['(없음)'] if optional else [])+list(raw.columns)
        index=options.index(default) if default in options else 0
        selected=cols[n%4].selectbox(labels[key],options,index=index,key=key)
        mapping[key]=None if selected=='(없음)' else selected
    cols=st.columns(4);units={}
    for n,(key,options) in enumerate([('voltage',['V','mV']),('current',['A','mA']),('capacity',['Ah','mAh']),('time',['H:M:S / Nd H:M:S','s'])]):
        selected=mapping.get(key) or ''
        default=1 if key!='time' and f'({options[1]})' in selected else 0
        units[key]=cols[n].selectbox(labels[key]+' 단위',options,index=default)
    positive=st.checkbox('양의 전류가 충전',value=True)
    st.caption('용량은 각 구간에서 증가하는 양의 용량 열을 선택하세요. 부호 있는 합계 용량은 지원하지 않습니다. 알 수 없는 동작명은 전류 부호로 분류합니다.')
    st.dataframe(raw.head(8),hide_index=True)
try:df=normalize(raw,mapping,units,positive)
except Exception as exc:
    st.error(f'열 설정을 확인하세요: {exc}');st.stop()
summary=segment_table(df)
with st.expander('전체 구간 및 품질 확인',expanded=False):
    st.dataframe(summary,hide_index=True)
    st.download_button('구간 목록 CSV',summary.to_csv(index=False).encode('utf-8-sig'),'segments.csv')
    st.write(f'시간 역전 {df.time_reversal.sum()}행 · 동작/전류 부호 불일치 {df.sign_conflict.sum()}행')
channel=st.selectbox('채널',df.channel.unique())
mode=st.radio('분석 방향',['충전 + 방전','충전','방전'],horizontal=True)
directions=['charge','discharge'] if mode=='충전 + 방전' else ['charge' if mode=='충전' else 'discharge']
subset=df[(df.channel==channel)&(df.direction.isin(directions))]
cycles=list(subset.cycle.unique())
if not cycles:st.warning('선택 방향의 데이터가 없습니다.');st.stop()
selection=st.radio('Cycle 선택 방식',['직접 입력','목록 선택'],horizontal=True)
if selection=='직접 입력':
    spec=st.text_input('비교 Cycle',value=cycles[0],help='1,5,10-50:5 → 1, 5, 10, 15, …, 50. 전체 입력도 가능합니다.')
    try:chosen,missing=select_cycles(spec,cycles)
    except ValueError as exc:st.error(str(exc));st.stop()
    if missing:st.warning('데이터가 없거나 일부 cycle이 없는 항목: '+', '.join(missing))
else:
    chosen=st.multiselect('비교 Cycle 목록',cycles,default=[cycles[0]])
st.caption(f'사용 가능 {len(cycles)}개 · 선택 {len(chosen)}개: '+', '.join(chosen[:30])+(' …' if len(chosen)>30 else ''))
if not chosen:st.info('분석할 Cycle을 선택하세요.');st.stop()
with st.expander('그래프 조작',expanded=True):
    cols=st.columns(3)
    hover_compare=cols[0].checkbox('같은 전압의 곡선 값 함께 보기',value=False)
    show_peaks=cols[1].checkbox('피크 표시',value=True)
    drag_choice=cols[2].radio('마우스 드래그',['영역 확대','이동'],horizontal=True)
    st.caption('마우스 올리기: 가장 가까운 계산점 좌표 · 휠: 확대/축소 · 더블클릭: 축 초기화 · 범례 클릭: 곡선 숨김/표시 · 도구막대 카메라: PNG 저장. 함께 보기는 가까운 grid 점을 표시하며 추가 보간하지 않습니다.')
with st.expander('계산 설정 · 기존 프로그램 동일 로직',expanded=True):
    cols=st.columns(3)
    points=cols[0].number_input('보간 포인트 수',50,20000,500,50)
    smooth=cols[1].checkbox('스무딩 사용',value=True)
    auto=cols[2].checkbox('윈도 자동',value=True)
    automatic=max(11,(points//25)|1)
    window=cols[0].number_input('수동 윈도 (포인트)',5,19999,21,2,disabled=auto or not smooth)
    poly=cols[1].number_input('스무딩 다항식 차수',1,10,3,1,disabled=not smooth)
    prominence=cols[2].number_input('피크 민감도 (%)',.01,100.,5.,.1)
    manual_upper=st.checkbox('충전 상한전압 직접 지정',value=False)
    upper=st.number_input('충전 상한전압 (V)',value=4.2,step=.01,disabled=not manual_upper)
    absolute=st.checkbox('방전 dQ/dV를 절댓값으로 표시',value=False)
    st.caption(f'자동 윈도 {automatic}포인트 · 용량과 미분 결과에 각각 스무딩 · 기본 피크 간격 5포인트')
    st.caption('충전은 상한전압 − 2mV에 처음 도달한 행까지 사용합니다. 자동 상한은 해당 cycle의 최대전압입니다. 도달 위치가 5번째 행보다 앞이면 원본 로직에 따라 자르지 않습니다.')
if smooth and not auto and (window%2==0 or window>=points or window<=poly):
    st.error('수동 윈도는 홀수이며, 보간 수보다 작고 다항식 차수보다 커야 합니다.');st.stop()
parameters=dict(n_points=points,smooth=smooth,smooth_window=None if auto else window,
                smooth_polyorder=poly,peak_prominence_pct=prominence/100,upper_voltage_v=upper if manual_upper else None)
fig=go.Figure();qfig=go.Figure();outputs=[];reports=[];peaks=[]
channel_df=df[df.channel==channel]
for color_index,cycle in enumerate(chosen):
  for direction in directions:
    g=subset[(subset.cycle==cycle)&(subset.direction==direction)]
    try:
        result,report=calculate_cycle(channel_df,cycle,direction,**parameters)
    except Exception as exc:
        reports.append(dict(cycle=cycle,direction=direction,reason=f'계산 실패: {exc}'));continue
    reports.append(report)
    add_curves(fig,qfig,g,result,cycle,direction,color_index,absolute,show_peaks)
    if result is None:continue
    curve=pd.DataFrame({'voltage_V':result['voltage_grid'],'capacity_mAh':result['capacity_on_vgrid'],
                        'dqdv_mAh_per_V':result['dqdv'],'cycle':cycle,'direction':direction})
    for key,value in parameters.items():curve[key]=value
    outputs.append(curve)
    for v,dq in zip(result['peak_voltage'],result['peak_dqdv']):
        peaks.append(dict(cycle=cycle,direction=direction,voltage_V=v,dqdv_mAh_per_V=dq,**parameters))
revision=hashlib.sha256(file.getvalue()).hexdigest()+str((channel,chosen,directions,parameters,absolute))
configure_chart(fig,'Voltage (V)','|dQ/dV| (mAh/V)' if absolute else 'dQ/dV (mAh/V)',
                hover_compare,'zoom' if drag_choice=='영역 확대' else 'pan',revision)
configure_chart(qfig,'Capacity (mAh)','Voltage (V)',False,'zoom' if drag_choice=='영역 확대' else 'pan',revision)
st.caption('같은 cycle은 같은 색 · 충전 실선 / 방전 점선')
st.plotly_chart(fig,width='stretch',config=CHART_CONFIG,key='dqdv_chart')
with st.expander('원본 V–Q 곡선 확인',expanded=True):
    st.plotly_chart(qfig,width='stretch',config=CHART_CONFIG,key='vq_chart')
st.caption('기존 로직과 동일하게 cycle·방향별 데이터를 모아 전압순 정렬 후 동일 전압의 용량을 평균합니다. 여러 step에서 용량이 리셋되는 경우에도 합산하지 않습니다. CSV에는 부호가 보존됩니다.')
if reports:
    report_df=pd.DataFrame(reports)
    st.dataframe(report_df,hide_index=True)
    st.download_button('계산/제외 내역 CSV',report_df.to_csv(index=False).encode('utf-8-sig'),'quality.csv')
peak_df=pd.DataFrame(peaks,columns=['cycle','direction','voltage_V','dqdv_mAh_per_V',*parameters])
st.dataframe(peak_df,hide_index=True)
st.download_button('피크 CSV',peak_df.to_csv(index=False).encode('utf-8-sig'),'peaks.csv')
if outputs:
    st.download_button('dQ/dV 곡선 CSV',pd.concat(outputs).to_csv(index=False).encode('utf-8-sig'),'dqdv.csv')
    st.download_button('그래프 HTML',fig.to_html(include_plotlyjs=True,config=CHART_CONFIG),'dqdv.html',mime='text/html')
else:st.info('선택한 cycle에 계산 가능한 구간이 없습니다. 매핑과 구간 목록을 확인하세요.')
settings=dict(file=file.name,sha256=hashlib.sha256(file.getvalue()).hexdigest(),mapping=mapping,units=units,
              positive_charge=positive,channel=channel,directions=directions,cycles=chosen,
              graph=dict(hover_compare=hover_compare,show_peaks=show_peaks,drag=drag_choice),
              parameters=parameters,absolute_display=absolute,algorithm='user-supplied-dqdv-v1')
st.download_button('분석 설정 JSON',json.dumps(settings,ensure_ascii=False,indent=2),'settings.json')
