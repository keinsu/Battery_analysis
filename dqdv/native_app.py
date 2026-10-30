"""Native Qt desktop UI. No browser, web server, or web rendering engine."""
import json
import sys
import traceback
from pathlib import Path
import numpy as np
import pandas as pd
import pyqtgraph as pg
import pyqtgraph.exporters
from PySide6 import QtCore, QtWidgets, QtGui
from core import read_csv, normalize, segment_table, calculate_cycle
from cycle_selection import select_cycles

pg.setConfigOptions(background='w',foreground='#172033',antialias=True)


class SuiteWindow(QtWidgets.QMainWindow):
    """Entry screen for the battery-analysis tools bundled in this EXE."""
    def __init__(self):
        super().__init__()
        self.setWindowTitle('Battery Analysis Suite')
        self.resize(920,600)
        self.active_window=None
        central=QtWidgets.QWidget();self.setCentralWidget(central)
        layout=QtWidgets.QVBoxLayout(central);layout.setContentsMargins(54,46,54,46);layout.setSpacing(18)
        title=QtWidgets.QLabel('Battery Analysis Suite');title.setStyleSheet('font-size:30px;font-weight:700;color:#172033;')
        subtitle=QtWidgets.QLabel('시작할 분석 프로그램을 선택하세요. 각 프로그램은 같은 충방전 원본 데이터를 사용할 수 있습니다.')
        subtitle.setStyleSheet('font-size:14px;color:#475569;')
        layout.addWidget(title);layout.addWidget(subtitle);layout.addSpacing(16)
        cards=QtWidgets.QHBoxLayout();cards.setSpacing(20);layout.addLayout(cards)
        cards.addWidget(self.tool_card('dQ/dV Analyzer','Cycle 변화에 따른 dQ/dV 곡선, 단일 cycle 상세, peak voltage 추이를 분석합니다.','분석 시작',self.open_dqdv,True))
        cards.addWidget(self.tool_card('사이클분석','Cycle별 충방전 용량과 효율, 전압 거동을 분석하는 다음 프로그램입니다.','프로그램 열기',self.open_cycle_analysis,False))
        layout.addStretch()
        note=QtWidgets.QLabel('현재 제공 기능: dQ/dV Analyzer   ·   다음 확장: 사이클분석')
        note.setStyleSheet('color:#64748b;');layout.addWidget(note)

    @staticmethod
    def tool_card(name,description,button_text,action,ready):
        card=QtWidgets.QFrame();card.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        card.setStyleSheet('QFrame { background:#f8fafc; border:1px solid #dbe4f0; border-radius:12px; }')
        layout=QtWidgets.QVBoxLayout(card);layout.setContentsMargins(25,25,25,25);layout.setSpacing(12)
        heading=QtWidgets.QLabel(name);heading.setStyleSheet('font-size:21px;font-weight:650;color:#172033;border:0;')
        state=QtWidgets.QLabel('사용 가능' if ready else '준비 중');state.setStyleSheet('color:#2563eb;font-weight:600;border:0;' if ready else 'color:#64748b;font-weight:600;border:0;')
        detail=QtWidgets.QLabel(description);detail.setWordWrap(True);detail.setStyleSheet('color:#475569;font-size:14px;border:0;')
        button=QtWidgets.QPushButton(button_text);button.clicked.connect(action);button.setMinimumHeight(42)
        button.setStyleSheet('QPushButton { background:#2563eb;color:white;border:0;border-radius:7px;font-weight:600;padding:8px 16px; } QPushButton:hover { background:#1d4ed8; }')
        layout.addWidget(heading);layout.addWidget(state);layout.addWidget(detail);layout.addStretch();layout.addWidget(button)
        return card

    def open_dqdv(self):
        self.active_window=MainWindow(home=self);self.hide();self.active_window.show()

    def open_cycle_analysis(self):
        self.active_window=CycleAnalysisWindow(home=self);self.hide();self.active_window.show()


class CycleAnalysisWindow(QtWidgets.QMainWindow):
    """Reserved independent workspace for the next analysis program."""
    def __init__(self,home):
        super().__init__()
        self.home=home;self.setWindowTitle('사이클분석 — Battery Analysis Suite');self.resize(920,600)
        central=QtWidgets.QWidget();self.setCentralWidget(central);layout=QtWidgets.QVBoxLayout(central)
        back=QtWidgets.QPushButton('← 프로그램 목록');back.clicked.connect(self.return_home);layout.addWidget(back,alignment=QtCore.Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()
        title=QtWidgets.QLabel('사이클분석');title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter);title.setStyleSheet('font-size:30px;font-weight:700;')
        detail=QtWidgets.QLabel('이 프로그램은 다음 기능으로 추가할 작업 공간입니다.\n현재는 dQ/dV Analyzer를 선택해 분석을 시작할 수 있습니다.')
        detail.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter);detail.setStyleSheet('font-size:15px;color:#475569;')
        layout.addWidget(title);layout.addWidget(detail);layout.addStretch()

    def return_home(self):
        self.home.show();self.close()


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self,home=None):
        super().__init__()
        self.home=home;self.setWindowTitle('dQ/dV Analyzer — Battery Analysis Suite')
        self.resize(1440,940)
        self.raw=None;self.df=None;self.results=[];self.peak_rows=[];self.settings={}
        self.traces=[[],[]];self.proxies=[];self.filename=''
        central=QtWidgets.QWidget();self.setCentralWidget(central)
        outer=QtWidgets.QVBoxLayout(central)
        header=QtWidgets.QHBoxLayout()
        title=QtWidgets.QLabel('dQ/dV · Cycling');title.setStyleSheet('font-size:24px;font-weight:600;')
        header.addWidget(title);header.addStretch()
        if self.home is not None:
            home_btn=QtWidgets.QPushButton('프로그램 목록');home_btn.clicked.connect(self.return_home);header.addWidget(home_btn)
        self.file_label=QtWidgets.QLabel('CSV 파일을 선택하세요');header.addWidget(self.file_label)
        open_btn=QtWidgets.QPushButton('CSV 열기');open_btn.clicked.connect(self.open_file);header.addWidget(open_btn)
        outer.addLayout(header)
        split=QtWidgets.QSplitter();outer.addWidget(split)
        scroll=QtWidgets.QScrollArea();scroll.setWidgetResizable(True);scroll.setMinimumWidth(310)
        panel=QtWidgets.QWidget();form=QtWidgets.QFormLayout(panel);scroll.setWidget(panel);split.addWidget(scroll)
        self.mapping={};self.units={};self.no_wheel_widgets=[]
        defaults={'channel':'Channel','cycle':'TotCycle','step':'StepNo','type':'Type','time':'TotTime(H:M:S)',
                  'voltage':'Voltage(V)','current':'Current(mA)','capacity':'Capacity(mAh)'}
        self.defaults=defaults
        self.mapping_toggle=QtWidgets.QToolButton();self.mapping_toggle.setCheckable(True);self.mapping_toggle.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.mapping_toggle.toggled.connect(self.toggle_mapping);form.addRow(self.mapping_toggle)
        self.mapping_panel=QtWidgets.QWidget();mapping_form=QtWidgets.QFormLayout(self.mapping_panel);mapping_form.setContentsMargins(0,0,0,6)
        for key,label in [('channel','채널 열'),('cycle','Cycle 열'),('step','Step 열'),('type','충방전 종류 열'),
                          ('time','시간 열'),('voltage','전압 열'),('current','전류 열'),('capacity','용량 열')]:
            combo=QtWidgets.QComboBox();self.mapping[key]=combo;mapping_form.addRow(label,combo);self.lock_wheel(combo)
            combo.currentIndexChanged.connect(self.invalidate)
        for key,label,options in [('voltage','전압 단위',['V','mV','µV']),('current','전류 단위',['A','mA']),
                                  ('capacity','용량 단위',['Ah','mAh']),('time','시간 형식',['H:M:S / Nd H:M:S','s'])]:
            combo=QtWidgets.QComboBox();combo.addItems(options);self.units[key]=combo;mapping_form.addRow(label,combo);self.lock_wheel(combo)
            combo.currentIndexChanged.connect(self.invalidate)
        self.positive=QtWidgets.QCheckBox('양의 전류 = 충전');self.positive.setChecked(True);mapping_form.addRow(self.positive)
        self.positive.toggled.connect(self.invalidate)
        remap=QtWidgets.QPushButton('열·단위 적용 / 구간 확인');remap.clicked.connect(self.apply_mapping_safe);mapping_form.addRow(remap)
        form.addRow(self.mapping_panel);self.toggle_mapping(False)
        self.channel=QtWidgets.QComboBox();form.addRow('분석 채널',self.channel);self.lock_wheel(self.channel)
        self.direction=QtWidgets.QComboBox();self.direction.addItems(['충전 + 방전','충전','방전']);form.addRow('분석 방향',self.direction);self.lock_wheel(self.direction)
        self.cycles=QtWidgets.QLineEdit('1');self.cycles.setPlaceholderText('1,5,10-50:5 또는 전체');form.addRow('Cycle 선택',self.cycles)
        self.available=QtWidgets.QLabel('');self.available.setWordWrap(True);form.addRow(self.available)
        self.points=self.spin(50,20000,500,50);form.addRow('보간 포인트 수',self.points);self.lock_wheel(self.points)
        self.smooth=QtWidgets.QCheckBox('스무딩 사용');self.smooth.setChecked(True);form.addRow(self.smooth)
        self.auto=QtWidgets.QCheckBox('윈도 자동');self.auto.setChecked(True);form.addRow(self.auto)
        self.window=self.spin(5,19999,21,2);form.addRow('윈도 (포인트)',self.window);self.lock_wheel(self.window)
        self.poly=self.spin(1,10,3);form.addRow('다항식 차수',self.poly);self.lock_wheel(self.poly)
        self.prom=QtWidgets.QDoubleSpinBox();self.prom.setRange(.01,100);self.prom.setValue(5);self.prom.setSuffix(' %');form.addRow('피크 민감도',self.prom);self.lock_wheel(self.prom)
        self.manual_upper=QtWidgets.QCheckBox('충전 상한전압 직접 지정');form.addRow(self.manual_upper)
        self.upper=QtWidgets.QDoubleSpinBox();self.upper.setRange(-100,1000);self.upper.setDecimals(4);self.upper.setValue(4.2);self.upper.setSuffix(' V');form.addRow(self.upper);self.lock_wheel(self.upper)
        self.absolute=QtWidgets.QCheckBox('방전 dQ/dV 절댓값 표시');form.addRow(self.absolute)
        self.show_peaks=QtWidgets.QCheckBox('피크 표시');self.show_peaks.setChecked(True);form.addRow(self.show_peaks)
        defaults_btn=QtWidgets.QPushButton('기본 계산 조건 복원');defaults_btn.clicked.connect(self.restore_defaults);form.addRow(defaults_btn)
        self.analyze_btn=QtWidgets.QPushButton('조건 적용 / 분석');self.analyze_btn.setStyleSheet('background:#2563eb;color:white;padding:9px;');self.analyze_btn.clicked.connect(self.analyze);form.addRow(self.analyze_btn)
        for widget in [self.channel,self.direction]:widget.currentIndexChanged.connect(self.invalidate)
        self.channel.currentIndexChanged.connect(self.update_available)
        self.cycles.textChanged.connect(self.invalidate)
        for widget in [self.points,self.window,self.poly,self.prom,self.upper]:widget.valueChanged.connect(self.invalidate)
        for widget in [self.smooth,self.auto,self.manual_upper,self.absolute,self.show_peaks]:widget.toggled.connect(self.invalidate)
        for widget in [self.smooth,self.auto,self.manual_upper]:widget.toggled.connect(self.sync_controls)
        self.points.valueChanged.connect(self.sync_controls)
        self.tabs=QtWidgets.QTabWidget();split.addWidget(self.tabs);split.setSizes([330,1100])
        graph_page=QtWidgets.QWidget();gl=QtWidgets.QVBoxLayout(graph_page);self.tabs.addTab(graph_page,'그래프')
        bar=QtWidgets.QHBoxLayout();gl.addLayout(bar)
        hint=QtWidgets.QLabel('마우스: 좌표 · 휠: 확대/축소 · 범례: 곡선 표시/숨김');bar.addWidget(hint);bar.addStretch()
        self.drag=QtWidgets.QComboBox();self.drag.addItems(['드래그 이동','영역 확대']);bar.addWidget(self.drag)
        reset=QtWidgets.QPushButton('전체 범위');reset.clicked.connect(self.reset_axes);bar.addWidget(reset)
        self.coordinate=QtWidgets.QLabel('곡선 위로 마우스를 이동하세요.');self.coordinate.setStyleSheet('font-family:Consolas;font-size:13px;padding:5px;background:#eef4ff;');gl.addWidget(self.coordinate)
        self.plots=[];self.crosshairs=[];self.traces=[];self.proxies=[]
        charts=QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal);gl.addWidget(charts)
        for index,title in enumerate(['dQ/dV','원본 V–Q']):
            plot=pg.PlotWidget(title=title);plot.addLegend();plot.showGrid(x=True,y=True,alpha=.2)
            for axis in ['bottom','left']:plot.getAxis(axis).enableAutoSIPrefix(False)
            charts.addWidget(plot);self.register_plot(plot)
        charts.setSizes([550,300]);self.drag.currentIndexChanged.connect(self.set_drag)
        detail_page=QtWidgets.QWidget();detail_layout=QtWidgets.QVBoxLayout(detail_page);self.tabs.addTab(detail_page,'단일 Cycle 상세')
        detail_header=QtWidgets.QHBoxLayout();detail_header.addWidget(QtWidgets.QLabel('상세 Cycle'))
        self.detail_cycle=QtWidgets.QComboBox();self.detail_cycle.currentIndexChanged.connect(self.update_detail);detail_header.addWidget(self.detail_cycle)
        detail_header.addWidget(QtWidgets.QLabel('선택한 한 cycle의 충전·방전 V–Q와 dQ/dV를 함께 표시합니다.'));detail_header.addStretch();detail_layout.addLayout(detail_header)
        detail_charts=QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal);detail_layout.addWidget(detail_charts)
        for title in ['dQ/dV · 단일 Cycle','V–Q · 단일 Cycle']:
            plot=pg.PlotWidget(title=title);plot.addLegend();plot.showGrid(x=True,y=True,alpha=.2)
            for axis in ['bottom','left']:plot.getAxis(axis).enableAutoSIPrefix(False)
            detail_charts.addWidget(plot);self.register_plot(plot)
        detail_charts.setSizes([550,550])
        peak_page=QtWidgets.QWidget();peak_layout=QtWidgets.QVBoxLayout(peak_page);self.tabs.addTab(peak_page,'피크 전압 추이')
        peak_layout.addWidget(QtWidgets.QLabel('선택한 cycle에서 검출된 모든 피크의 전압 위치입니다. 피크 민감도 설정이 그대로 적용됩니다.'))
        peak_plot=pg.PlotWidget(title='Cycle별 dQ/dV Peak Voltage');peak_plot.addLegend();peak_plot.showGrid(x=True,y=True,alpha=.2)
        peak_plot.setLabel('bottom','Cycle');peak_plot.setLabel('left','Peak Voltage',units='V');peak_layout.addWidget(peak_plot);self.register_plot(peak_plot)
        self.peak_table=QtWidgets.QTableWidget();self.tabs.addTab(self.peak_table,'피크 표')
        self.segment_view=QtWidgets.QTableWidget();self.tabs.addTab(self.segment_view,'구간 / 품질')
        self.preview=QtWidgets.QTableWidget();self.tabs.addTab(self.preview,'원본 미리보기')
        export_bar=QtWidgets.QHBoxLayout();outer.addLayout(export_bar);self.exports=[]
        for text,action in [('곡선 CSV',lambda:self.export_csv(False)),('피크 CSV',lambda:self.export_csv(True)),
                            ('분석 설정 JSON',self.export_settings),('그래프 PNG',self.export_png)]:
            b=QtWidgets.QPushButton(text);b.clicked.connect(action);export_bar.addWidget(b);self.exports.append(b)
        self.status=QtWidgets.QLabel('CSV를 불러오세요.');self.status.setWordWrap(True);outer.addWidget(self.status)
        self.sync_controls();self.invalidate()

    @staticmethod
    def spin(low,high,value,step=1):
        w=QtWidgets.QSpinBox();w.setRange(low,high);w.setValue(value);w.setSingleStep(step);return w

    def lock_wheel(self,widget):
        """Keep a scrolling pointer from changing a left-panel setting."""
        self.no_wheel_widgets.append(widget);widget.installEventFilter(self)

    def eventFilter(self,watched,event):
        if watched in self.no_wheel_widgets and event.type()==QtCore.QEvent.Type.Wheel:
            event.accept()
            return True
        return super().eventFilter(watched,event)

    def toggle_mapping(self,visible):
        self.mapping_panel.setVisible(visible)
        self.mapping_toggle.setArrowType(QtCore.Qt.ArrowType.DownArrow if visible else QtCore.Qt.ArrowType.RightArrow)
        self.mapping_toggle.setText('열 · 단위 설정 숨기기' if visible else '열 · 단위 설정 보기')

    def sync_controls(self,*args):
        if self.auto.isChecked():self.window.setValue(max(11,(self.points.value()//25)|1))
        self.window.setEnabled(self.smooth.isChecked() and not self.auto.isChecked())
        self.poly.setEnabled(self.smooth.isChecked());self.upper.setEnabled(self.manual_upper.isChecked())

    @staticmethod
    def cycle_color(index,total):
        """Map the selected cycle order from red (early) to blue (late)."""
        ratio=index/max(total-1,1)
        start,end=QtGui.QColor('#dc2626'),QtGui.QColor('#2563eb')
        return QtGui.QColor(round(start.red()+(end.red()-start.red())*ratio),round(start.green()+(end.green()-start.green())*ratio),round(start.blue()+(end.blue()-start.blue())*ratio))

    def invalidate(self,*args):
        if hasattr(self,'exports'):
            for b in self.exports:b.setEnabled(False)
            self.status.setText('조건이 바뀌었습니다. 조건 적용 / 분석을 누르세요.')

    def restore_defaults(self):
        self.points.setValue(500);self.smooth.setChecked(True);self.auto.setChecked(True)
        self.poly.setValue(3);self.prom.setValue(5);self.manual_upper.setChecked(False)
        self.absolute.setChecked(False);self.sync_controls()

    def return_home(self):
        if self.home is not None:
            self.home.show();self.close()

    def open_file(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Cycling CSV','','CSV (*.csv)')
        if path:
            try:self.load_file(path)
            except Exception as exc:QtWidgets.QMessageBox.warning(self,'파일 읽기 실패',str(exc))

    def load_file(self,path):
        self.raw,encoding=read_csv(Path(path).read_bytes());self.filename=str(path)
        self.file_label.setText(f'{Path(path).name} · {len(self.raw):,}행 · {encoding}')
        for key,combo in self.mapping.items():
            combo.clear()
            if key in ('channel','step','type','time'):combo.addItem('(없음)')
            combo.addItems(list(self.raw.columns));idx=combo.findText(self.defaults[key]);combo.setCurrentIndex(max(idx,0))
        for key in ['voltage','current','capacity']:
            self.units[key].setCurrentText(self.infer_unit(key, self.mapping[key].currentText()))
        self.fill_table(self.preview,self.raw.head(100))
        self.apply_mapping();self.cycles.setText(str(self.df.cycle.iloc[0]));self.analyze()

    def infer_unit(self,key,column):
        """Choose a safe initial unit from a column label, then its numeric scale."""
        label=column.lower().replace('μ','µ')
        if key=='voltage':
            if any(token in label for token in ('µv','uv','microvolt')):return 'µV'
            if any(token in label for token in ('mv','millivolt')):return 'mV'
            values=pd.to_numeric(self.raw[column],errors='coerce').dropna()
            if not values.empty:
                magnitude=values.abs().median()
                if magnitude >= 100000:return 'µV'
                if magnitude >= 100:return 'mV'
            return 'V'
        return 'mA' if key=='current' and '(m' in label else 'mAh' if key=='capacity' and '(m' in label else 'A' if key=='current' else 'Ah'

    def apply_mapping_safe(self):
        try:self.apply_mapping()
        except Exception as exc:QtWidgets.QMessageBox.warning(self,'열 설정 확인',str(exc))

    def apply_mapping(self):
        if self.raw is None:raise ValueError('CSV를 먼저 불러오세요.')
        self.mapping_values={k:(None if w.currentText()=='(없음)' else w.currentText()) for k,w in self.mapping.items()}
        self.unit_values={k:w.currentText() for k,w in self.units.items()}
        self.df=normalize(self.raw,self.mapping_values,self.unit_values,self.positive.isChecked())
        old=self.channel.currentText();self.channel.clear();self.channel.addItems(list(self.df.channel.unique()))
        idx=self.channel.findText(old)
        if idx>=0:self.channel.setCurrentIndex(idx)
        self.fill_table(self.segment_view,segment_table(self.df));self.update_available()

    def update_available(self,*args):
        if self.df is None:return
        cycles=list(self.df[self.df.channel==self.channel.currentText()].cycle.unique())
        self.available.setText('입력 예: 1,5,10-50:5 / 전체\n사용 가능: '+', '.join(cycles[:16])+(' …' if len(cycles)>16 else ''))

    def register_plot(self,plot):
        index=len(self.plots);self.plots.append(plot);self.traces.append([])
        self.proxies.append(pg.SignalProxy(plot.scene().sigMouseMoved,rateLimit=30,slot=lambda event,i=index:self.cursor_at(i,event[0])))

    def reset_plot(self,index):
        plot=self.plots[index];plot.clear()
        if plot.plotItem.legend:plot.plotItem.legend.clear()
        lines=[pg.InfiniteLine(angle=a,movable=False,pen=pg.mkPen('#94a3b8',style=QtCore.Qt.PenStyle.DotLine)) for a in [90,0]]
        for line in lines:plot.addItem(line,ignoreBounds=True);line.hide()
        self.crosshairs[index]=lines
        self.traces[index]=[]

    def analyze(self):
        self.invalidate()
        if self.raw is None:return
        QtWidgets.QApplication.setOverrideCursor(QtCore.Qt.CursorShape.WaitCursor)
        try:
            self.apply_mapping()
            channel_df=self.df[self.df.channel==self.channel.currentText()]
            directions=['charge','discharge'] if self.direction.currentIndex()==0 else ['charge' if self.direction.currentIndex()==1 else 'discharge']
            subset=channel_df[channel_df.direction.isin(directions)]
            chosen,missing=select_cycles(self.cycles.text(),list(subset.cycle.unique()))
            if not chosen:raise ValueError('해당 Cycle 데이터가 없습니다.')
            if self.smooth.isChecked() and not self.auto.isChecked():
                if self.window.value()%2==0 or self.window.value()>=self.points.value() or self.window.value()<=self.poly.value():
                    raise ValueError('윈도는 홀수이며 보간 수보다 작고 다항식 차수보다 커야 합니다.')
            params=dict(n_points=self.points.value(),smooth=self.smooth.isChecked(),smooth_window=None if self.auto.isChecked() else self.window.value(),
                        smooth_polyorder=self.poly.value(),peak_prominence_pct=self.prom.value()/100,upper_voltage_v=self.upper.value() if self.manual_upper.isChecked() else None)
            self.results=[];self.peak_rows=[];self.detail_records=[];excluded=[]
            self.crosshairs=[None for _ in self.plots]
            for index in range(len(self.plots)):self.reset_plot(index)
            for ci,cycle in enumerate(chosen):
                for direction in directions:
                    r,report=calculate_cycle(channel_df,cycle,direction,**params)
                    if r is None:excluded.append(f'{cycle} {direction}: '+report['reason']);continue
                    name=f'Cycle {cycle} · '+('충전' if direction=='charge' else '방전')
                    color=self.cycle_color(ci,len(chosen))
                    pen=pg.mkPen(color,width=2,style=QtCore.Qt.PenStyle.SolidLine if direction=='charge' else QtCore.Qt.PenStyle.DashLine)
                    y=np.abs(r['dqdv']) if self.absolute.isChecked() else r['dqdv']
                    item=self.plots[0].plot(r['voltage_grid'],y,pen=pen,name=name)
                    self.traces[0].append((item,r['voltage_grid'],y,name))
                    g=subset[(subset.cycle==cycle)&(subset.direction==direction)]
                    xq,yv=g.capacity.to_numpy()*1000,g.voltage.to_numpy()
                    itemq=self.plots[1].plot(xq,yv,pen=pen,name=name);self.traces[1].append((itemq,xq,yv,name))
                    if self.show_peaks.isChecked():
                        self.plots[0].plot(r['peak_voltage'],np.abs(r['peak_dqdv']) if self.absolute.isChecked() else r['peak_dqdv'],
                            pen=None,symbol='o',symbolSize=7,symbolPen=color,symbolBrush='w')
                    curve=pd.DataFrame(dict(cycle=cycle,direction=direction,voltage_V=r['voltage_grid'],capacity_mAh=r['capacity_on_vgrid'],dqdv_mAh_per_V=r['dqdv']))
                    self.results.append(curve)
                    self.detail_records.append(dict(cycle=cycle,direction=direction,result=r,raw=g,pen=pen,name=name))
                    self.peak_rows.extend(dict(cycle=cycle,direction=direction,voltage_V=float(v),dqdv_mAh_per_V=float(dq)) for v,dq in zip(r['peak_voltage'],r['peak_dqdv']))
            self.plots[0].setLabel('bottom','Voltage',units='V');self.plots[0].setLabel('left','|dQ/dV|' if self.absolute.isChecked() else 'dQ/dV',units='mAh/V')
            self.plots[1].setLabel('bottom','Capacity',units='mAh');self.plots[1].setLabel('left','Voltage',units='V')
            self.fill_table(self.peak_table,pd.DataFrame(self.peak_rows,columns=['cycle','direction','voltage_V','dqdv_mAh_per_V']))
            self.detail_cycle.blockSignals(True);self.detail_cycle.clear();self.detail_cycle.addItems(chosen);self.detail_cycle.blockSignals(False)
            self.update_detail();self.update_peak_trend()
            self.settings=dict(file=Path(self.filename).name,mapping=self.mapping_values,units=self.unit_values,positive_charge=self.positive.isChecked(),
                channel=self.channel.currentText(),cycles=chosen,directions=directions,parameters=params,absolute_display=self.absolute.isChecked())
            self.reset_axes();self.set_drag()
            for b in self.exports:b.setEnabled(bool(self.results))
            self.status.setText(f'{len(self.results)}개 곡선 · {len(self.peak_rows)}개 피크'+(' | 없는 cycle: '+', '.join(missing) if missing else '')+(' | 제외: '+'; '.join(excluded[:8]) if excluded else ''))
            self.coordinate.setText('곡선 위로 마우스를 이동하세요.');self.tabs.setCurrentIndex(0)
        except Exception as exc:
            self.status.setText('분석할 수 없습니다: '+str(exc))
        finally:QtWidgets.QApplication.restoreOverrideCursor()

    def cursor_at(self,index,pos):
        plot=self.plots[index]
        if not plot.sceneBoundingRect().contains(pos):return
        point=plot.plotItem.vb.mapSceneToView(pos);ranges=plot.viewRange()
        dx=max(ranges[0][1]-ranges[0][0],1e-12);dy=max(ranges[1][1]-ranges[1][0],1e-12)
        best=None
        for item,x,y,name in self.traces[index]:
            if not item.isVisible():continue
            mask=np.isfinite(x)&np.isfinite(y)
            if not mask.any():continue
            xx,yy=x[mask],y[mask];dist=((xx-point.x())/dx)**2+((yy-point.y())/dy)**2;j=int(np.argmin(dist))
            candidate=(float(dist[j]),float(xx[j]),float(yy[j]),name)
            if best is None or candidate[0]<best[0]:best=candidate
        if best is None:return
        _,x,y,name=best
        if self.crosshairs:
            self.crosshairs[index][0].setPos(x);self.crosshairs[index][1].setPos(y)
            for line in self.crosshairs[index]:line.show()
        if index in (0,2):self.coordinate.setText(f'{name} | Voltage {x:.5f} V | dQ/dV {y:.4f} mAh/V')
        elif index in (1,3):self.coordinate.setText(f'{name} | Capacity {x:.4f} mAh | Voltage {y:.5f} V')
        else:self.coordinate.setText(f'{name} | Cycle {x:.0f} | Peak Voltage {y:.5f} V')

    def set_drag(self,*args):
        for p in self.plots:p.plotItem.vb.setMouseMode(pg.ViewBox.PanMode if self.drag.currentIndex()==0 else pg.ViewBox.RectMode)

    def reset_axes(self):
        for p in self.plots:p.autoRange()

    def update_detail(self,*args):
        if not hasattr(self,'detail_records') or not self.detail_cycle.currentText():return
        for index in (2,3):self.reset_plot(index)
        cycle=self.detail_cycle.currentText()
        for record in self.detail_records:
            if record['cycle']!=cycle:continue
            result,raw,pen,name=record['result'],record['raw'],record['pen'],record['name']
            y=np.abs(result['dqdv']) if self.absolute.isChecked() else result['dqdv']
            item=self.plots[2].plot(result['voltage_grid'],y,pen=pen,name=name)
            self.traces[2].append((item,result['voltage_grid'],y,name))
            xq,yv=raw.capacity.to_numpy()*1000,raw.voltage.to_numpy()
            item=self.plots[3].plot(xq,yv,pen=pen,name=name)
            self.traces[3].append((item,xq,yv,name))
            if self.show_peaks.isChecked():
                self.plots[2].plot(result['peak_voltage'],np.abs(result['peak_dqdv']) if self.absolute.isChecked() else result['peak_dqdv'],pen=None,symbol='o',symbolSize=8,symbolPen=pen.color(),symbolBrush='w')
        self.plots[2].setLabel('bottom','Voltage',units='V');self.plots[2].setLabel('left','dQ/dV',units='mAh/V')
        self.plots[3].setLabel('bottom','Capacity',units='mAh');self.plots[3].setLabel('left','Voltage',units='V')
        self.plots[2].autoRange();self.plots[3].autoRange()

    def update_peak_trend(self):
        self.reset_plot(4)
        if not self.peak_rows:return
        peaks=pd.DataFrame(self.peak_rows)
        for direction,color,label in [('charge','#d97706','충전'),('discharge','#2563eb','방전')]:
            subset=peaks[peaks.direction==direction]
            if subset.empty:continue
            item=self.plots[4].plot(subset.cycle.astype(float),subset.voltage_V,pen=None,symbol='o',symbolSize=8,symbolBrush=color,symbolPen=color,name=label)
            self.traces[4].append((item,subset.cycle.to_numpy(float),subset.voltage_V.to_numpy(float),label))
        self.plots[4].setLabel('bottom','Cycle');self.plots[4].setLabel('left','Peak Voltage',units='V');self.plots[4].autoRange()

    @staticmethod
    def fill_table(table,frame):
        table.setRowCount(len(frame));table.setColumnCount(len(frame.columns));table.setHorizontalHeaderLabels([str(c) for c in frame.columns])
        table.setEditTriggers(QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        for row,values in enumerate(frame.itertuples(index=False,name=None)):
            for col,value in enumerate(values):table.setItem(row,col,QtWidgets.QTableWidgetItem(str(value)))
        table.resizeColumnsToContents()

    def export_csv(self,peaks=False):
        if not self.results:return
        path,_=QtWidgets.QFileDialog.getSaveFileName(self,'CSV 저장','peaks.csv' if peaks else 'dqdv.csv','CSV (*.csv)')
        if not path:return
        frame=pd.DataFrame(self.peak_rows,columns=['cycle','direction','voltage_V','dqdv_mAh_per_V']) if peaks else pd.concat(self.results,ignore_index=True)
        for k,v in self.settings['parameters'].items():frame[k]=v
        try:frame.to_csv(path,index=False,encoding='utf-8-sig')
        except Exception as exc:QtWidgets.QMessageBox.warning(self,'저장 실패',str(exc))

    def export_settings(self):
        path,_=QtWidgets.QFileDialog.getSaveFileName(self,'설정 저장','settings.json','JSON (*.json)')
        if path:
            try:Path(path).write_text(json.dumps(self.settings,ensure_ascii=False,indent=2),encoding='utf-8')
            except Exception as exc:QtWidgets.QMessageBox.warning(self,'저장 실패',str(exc))

    def export_png(self):
        path,_=QtWidgets.QFileDialog.getSaveFileName(self,'dQ/dV 그래프 저장','dqdv.png','PNG (*.png)')
        if path:
            try:pg.exporters.ImageExporter(self.plots[0].plotItem).export(path)
            except Exception as exc:QtWidgets.QMessageBox.warning(self,'저장 실패',str(exc))


def smoke(app,output):
    import tempfile
    from legacy_backend.dqdv import compute_dqdv
    with tempfile.TemporaryDirectory() as temp:
        suite=SuiteWindow();suite.show();app.processEvents()
        assert suite.windowTitle()=='Battery Analysis Suite'
        assert len(suite.findChildren(QtWidgets.QPushButton))==2
        suite.close()
        assert MainWindow.cycle_color(0,3).name()=='#dc2626'
        assert MainWindow.cycle_color(2,3).name()=='#2563eb'
        rows=[]
        for cycle in [1,5,10]:
            for direction,sign in [('충전',1),('방전',-1)]:
                for i in range(101):
                    q=i/100;v=3+q+.06*np.sin(q*12)
                    rows.append({'TotCycle':cycle,'Type':direction,'Voltage(V)':v if sign>0 else 7-v,'Current(mA)':sign*1000,'Capacity(mAh)':q*1000})
        raw=pd.DataFrame(rows);path=Path(temp)/'sample.csv';raw.to_csv(path,index=False,encoding='utf-8-sig')
        win=MainWindow();win.show();app.processEvents();win.load_file(path)
        win.cycles.setText('1,5,10');win.analyze();app.processEvents()
        assert len(win.results)==6,win.status.text()
        assert len(win.traces[2])==2 and len(win.traces[3])==2
        assert len(win.traces[4]) <= 2
        for actual in win.results:
            cy=actual.cycle.iloc[0];dr=actual.direction.iloc[0]
            reference=pd.DataFrame(dict(Cycle=raw.TotCycle.astype(str),TypeStd=raw.Type.map({'충전':'CHARGE','방전':'DISCHARGE'}),Voltage_V=raw['Voltage(V)'],Capacity_mAh=raw['Capacity(mAh)'],_row=np.arange(len(raw))))
            expected=compute_dqdv(reference,cy,dr)
            np.testing.assert_allclose(actual.dqdv_mAh_per_V,expected['dqdv'],rtol=1e-9,atol=1e-7)
        win.points.setValue(200);win.analyze();assert all(len(r)==200 for r in win.results)
        win.direction.setCurrentIndex(2);win.analyze();assert len(win.results)==3
        _,x,y,_=win.traces[0][0]
        point=win.plots[0].plotItem.vb.mapViewToScene(QtCore.QPointF(float(x[50]),float(y[50])))
        win.cursor_at(0,point);assert 'Voltage' in win.coordinate.text()
        win.cycles.setText('999');win.analyze();assert not win.exports[0].isEnabled()
        win.cycles.setText('1,5,10');win.restore_defaults();win.direction.setCurrentIndex(0);win.analyze();app.processEvents()
        win.grab().save(str(Path(output).with_suffix('.png')))
        win.close()
    Path(output).write_text('NATIVE_EXE_SELF_TEST_OK',encoding='utf-8')


def main():
    import multiprocessing
    multiprocessing.freeze_support()
    app=QtWidgets.QApplication(sys.argv);app.setStyle('Fusion');app.setFont(QtGui.QFont('Malgun Gothic',10))
    if '--self-test' in sys.argv:
        output=sys.argv[sys.argv.index('--self-test')+1]
        try:smoke(app,output)
        except Exception:
            Path(output+'.error.txt').write_text(traceback.format_exc(),encoding='utf-8');raise
        return
    window=SuiteWindow();window.show();sys.exit(app.exec())


if __name__=='__main__':main()
