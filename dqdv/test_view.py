import pytest
from view import select_cycles, configure_chart, CHART_CONFIG
import plotly.graph_objects as go


def test_cycle_range_selection():
    available=list(map(str,range(1,118)))
    assert select_cycles('1,5,10-50:5',available)==(['1','5',*map(str,range(10,51,5))],[])
    assert select_cycles('5,5,1',available)==(['5','1'],[])
    assert select_cycles('전체',available)==(available,[])
    assert select_cycles('116-120',available)==(['116','117'],['116-120'])
    assert select_cycles('999',available)==([],['999'])
    assert select_cycles('1-9999999999999999:1',['1'])==(['1'],['1-9999999999999999:1'])


@pytest.mark.parametrize('spec',['','1,,3','1-5:0','5-1','abc','1-3:-2'])
def test_invalid_cycle_input(spec):
    with pytest.raises(ValueError):select_cycles(spec,['1','2','3'])


def test_chart_controls():
    fig=go.Figure();configure_chart(fig,'V','mAh/V',True,'pan','test')
    assert fig.layout.hovermode=='x unified'
    assert fig.layout.xaxis.showspikes and fig.layout.yaxis.showspikes
    assert fig.layout.dragmode=='pan'
    assert CHART_CONFIG['scrollZoom'] and CHART_CONFIG['doubleClick']=='reset'
