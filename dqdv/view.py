"""Cycle selection and shared interactive chart presentation."""
import re
import plotly.graph_objects as go
from plotly.colors import qualitative

CHART_CONFIG = dict(scrollZoom=True, displayModeBar=True, displaylogo=False,
                    doubleClick='reset', toImageButtonOptions=dict(format='png',scale=2))


def select_cycles(spec, available):
    """Resolve ranges against existing IDs, without expanding arbitrary-size ranges."""
    available=list(available)
    if not spec.strip():raise ValueError('Cycle을 입력하세요. 예: 1,5,10-50:5')
    if spec.strip().lower() in ('전체','all'):return available,[]
    selected=[];missing=[]
    for token in spec.split(','):
        token=token.strip()
        if not token:raise ValueError('쉼표 사이에 빈 항목이 있습니다.')
        if token in available:
            selected.append(token);continue
        match=re.fullmatch(r'(\d+)\s*-\s*(\d+)(?:\s*:\s*(\d+))?',token)
        if match:
            start,end,step=map(int,(match[1],match[2],match[3] or '1'))
            if step<1 or start>end:raise ValueError('범위는 시작 ≤ 끝, 간격은 1 이상이어야 합니다.')
            found=[c for c in available if c.isdigit() and start<=int(c)<=end and (int(c)-start)%step==0]
            selected.extend(found)
            if len(found)<(end-start)//step+1:missing.append(token)
        elif re.fullmatch(r'\d+',token):missing.append(token)
        else:raise ValueError(f'잘못된 Cycle 입력: {token}. 예: 1,5,10-50:5 또는 전체')
    return list(dict.fromkeys(selected)),missing


def add_curves(fig,qfig,raw,result,cycle,direction,color_index,absolute=False,show_peaks=True):
    phase='충전' if direction=='charge' else '방전'
    label=f'Cycle {cycle} · {phase}'
    color=qualitative.Plotly[color_index%len(qualitative.Plotly)]
    style=dict(color=color,dash='solid' if direction=='charge' else 'dash')
    group=f'{cycle}:{direction}'
    qfig.add_trace(go.Scatter(x=raw.capacity*1000,y=raw.voltage,mode='lines',name=label,
        legendgroup=group,line=style,hovertemplate='용량 %{x:.4f} mAh<br>전압 %{y:.5f} V<extra>'+label+'</extra>'))
    if result is None:return
    y=abs(result['dqdv']) if absolute else result['dqdv']
    caption='|dQ/dV|' if absolute else 'dQ/dV'
    hover='전압 %{x:.5f} V<br>'+caption+' %{y:.4f} mAh/V<extra>'+label+'</extra>'
    fig.add_trace(go.Scatter(x=result['voltage_grid'],y=y,mode='lines',name=label,
                            legendgroup=group,line=style,hovertemplate=hover))
    if show_peaks:
        fig.add_trace(go.Scatter(x=result['peak_voltage'],y=abs(result['peak_dqdv']) if absolute else result['peak_dqdv'],
            mode='markers',marker=dict(color=color,size=8,symbol='circle-open'),name=label+' 피크',
            legendgroup=group,showlegend=False,hovertemplate=hover))


def configure_chart(fig,x_title,y_title,hover_compare=False,drag='zoom',revision=None):
    fig.update_layout(xaxis_title=x_title,yaxis_title=y_title,height=530,template='plotly_white',
        hovermode='x unified' if hover_compare else 'closest',dragmode=drag,uirevision=revision,
        legend=dict(groupclick='togglegroup',title_text='클릭: 표시/숨김 · 더블클릭: 단독 표시'),
        margin=dict(l=70,r=30,t=35,b=60))
    fig.update_xaxes(showspikes=True,spikemode='across',spikesnap='cursor',spikedash='dot',showgrid=True)
    fig.update_yaxes(showspikes=True,spikemode='across',spikesnap='cursor',spikedash='dot',showgrid=True)
