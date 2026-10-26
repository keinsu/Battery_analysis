import hashlib
from pathlib import Path
import numpy as np
import pandas as pd
import pytest
from core import normalize, calculate_cycle, elapsed
from legacy_backend.dqdv import compute_dqdv, _cc_region_only, _dedup_monotonic


def fixture():
    rows=[]
    for cycle in [1,2]:
        for direction,sign in [('충전',1),('방전',-1)]:
            for t in range(101):
                q=t/100
                v=3+q+.06*np.sin(q*12)
                if sign<0:v=7-v
                rows.append(dict(cycle=cycle,kind=direction,voltage=v,current=sign,capacity=q,row=len(rows)))
    raw=pd.DataFrame(rows)
    mapping=dict(cycle='cycle',type='kind',voltage='voltage',current='current',capacity='capacity')
    df=normalize(raw,mapping,dict(voltage='V',current='A',capacity='Ah'))
    direct=pd.DataFrame(dict(Cycle=raw.cycle.astype(str),TypeStd=raw.kind.map({'충전':'CHARGE','방전':'DISCHARGE'}),
        Voltage_V=raw.voltage,Capacity_mAh=raw.capacity*1000,_row=raw.row))
    return df,direct


@pytest.mark.parametrize('settings',[{},dict(n_points=200,smooth_window=15,smooth_polyorder=2,peak_prominence_pct=.08),
                                    dict(smooth=False),dict(upper_voltage_v=3.7),dict(n_points=1000)])
def test_adapter_matches_direct_source(settings):
    df,direct=fixture()
    for cycle in ['1','2']:
        for direction in ['charge','discharge']:
            actual,_=calculate_cycle(df,cycle,direction,**settings)
            expected=compute_dqdv(direct,cycle,direction,**settings)
            for key in expected:np.testing.assert_array_equal(actual[key],expected[key])


def test_cutoff_boundary_and_duplicates():
    v=np.array([3.,3.2,3.5,3.8,4.198,4.2,4.2]);q=np.arange(7.)
    cv,cq=_cc_region_only(v,q,4.2)
    np.testing.assert_array_equal(cv,v[:5])
    np.testing.assert_array_equal(cq,q[:5])
    # Original early-cutoff exception is deliberately preserved.
    np.testing.assert_array_equal(_cc_region_only(v,q,3.5)[0],v)
    x,y=_dedup_monotonic(np.array([4.,3.,4.]),np.array([1.,0.,3.]))
    np.testing.assert_array_equal(x,[3.,4.]);np.testing.assert_array_equal(y,[0.,2.])


def test_linear_discharge_units():
    raw=pd.DataFrame(dict(v=np.linspace(4000,3000,101),q=np.linspace(0,1000,101),i=-1000,c=1,t='방전'))
    df=normalize(raw,dict(voltage='v',capacity='q',current='i',cycle='c',type='t'),dict(voltage='mV',current='mA',capacity='mAh'))
    r,_=calculate_cycle(df,'1','discharge')
    np.testing.assert_allclose(r['dqdv'],-1000,atol=1e-8)
    assert len(r['dqdv'])==500
    assert elapsed('12d 18:44:38.75')==1104278.75


def test_cycle_aggregation_with_resets_matches_original():
    df,direct=fixture()
    df.loc[20:30,'capacity']=0
    direct.loc[20:30,'Capacity_mAh']=0
    actual,_=calculate_cycle(df,'1','charge')
    expected=compute_dqdv(direct,'1','charge')
    np.testing.assert_array_equal(actual['dqdv'],expected['dqdv'])


def test_insufficient_data():
    df,_=fixture()
    r,report=calculate_cycle(df.iloc[:4],'1','charge')
    assert r is None
    assert '5개 미만' in report['reason']
