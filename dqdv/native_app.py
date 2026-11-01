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
from core import read_csv, normalize, segment_table, calculate_cycle, calculate_step, lowest_current_step, latest_cycle_for_step
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
        cards.addWidget(self.tool_card('Step dQ/dV Analyzer','한 cycle에서 지정한 충전 Step과 방전 Step의 dQ/dV·dV/dQ를 분석합니다.','분석 시작',self.open_step_dqdv,True))
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

    def open_step_dqdv(self):
        self.active_window=MainWindow(home=self,selection_mode='step');self.hide();self.active_window.show()

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
    (MAIN_DQDV_CHARGE,MAIN_DQDV_DISCHARGE,MAIN_DVDQ_CHARGE,MAIN_DVDQ_DISCHARGE,MAIN_VQ,
     DETAIL_DQDV_CHARGE,DETAIL_DQDV_DISCHARGE,DETAIL_VQ_CHARGE,DETAIL_VQ_DISCHARGE,PEAK_TREND)=range(10)

    def __init__(self,home=None,selection_mode='cycle'):
        super().__init__()
        self.home=home;self.selection_mode=selection_mode
        self.setWindowTitle(('Step dQ/dV Analyzer' if selection_mode=='step' else 'dQ/dV Analyzer')+' — Battery Analysis Suite')
        self.resize(1440,940)
        self.raw=None;self.df=None;self.compare_raw=None;self.compare_df=None;self.results=[];self.peak_rows=[];self.settings={}
        self.traces=[[],[]];self.proxies=[];self.filename=''
        central=QtWidgets.QWidget();self.setCentralWidget(central)
        outer=QtWidgets.QVBoxLayout(central)
        header=QtWidgets.QHBoxLayout()
        title=QtWidgets.QLabel('dQ/dV · '+('Step 분석' if selection_mode=='step' else 'Cycling'));title.setStyleSheet('font-size:24px;font-weight:600;')
        header.addWidget(title);header.addStretch()
        if self.home is not None:
            home_btn=QtWidgets.QPushButton('프로그램 목록');home_btn.clicked.connect(self.return_home);header.addWidget(home_btn)
        self.file_label=QtWidgets.QLabel('CSV 파일을 선택하세요');header.addWidget(self.file_label)
        open_btn=QtWidgets.QPushButton('CSV 열기');open_btn.clicked.connect(self.open_file);header.addWidget(open_btn)
        self.compare_btn=QtWidgets.QPushButton('비교 CSV 추가');self.compare_btn.clicked.connect(self.open_compare_file);header.addWidget(self.compare_btn)
        self.remove_compare_btn=QtWidgets.QPushButton('비교 제거');self.remove_compare_btn.clicked.connect(self.remove_compare_file);self.remove_compare_btn.setVisible(False);header.addWidget(self.remove_compare_btn)
        outer.addLayout(header)
        split=QtWidgets.QSplitter();outer.addWidget(split,1)
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
        self.direction=QtWidgets.QComboBox();self.direction.addItems(['충전 + 방전','충전','방전']);self.lock_wheel(self.direction)
        self.cycles=QtWidgets.QLineEdit('1');self.cycles.setPlaceholderText('1,5,10-50:5 또는 전체')
        self.step_charge=QtWidgets.QLineEdit();self.step_charge.setPlaceholderText('충전 Step 번호')
        self.step_discharge=QtWidgets.QLineEdit();self.step_discharge.setPlaceholderText('방전 Step 번호')
        self.step_charge_cycle=QtWidgets.QLineEdit();self.step_charge_cycle.setPlaceholderText('충전 Step의 Cycle')
        self.step_discharge_cycle=QtWidgets.QLineEdit();self.step_discharge_cycle.setPlaceholderText('방전 Step의 Cycle')
        if self.selection_mode=='step':
            form.addRow('충전 Step',self.step_charge);form.addRow('충전 Cycle',self.step_charge_cycle)
            form.addRow('방전 Step',self.step_discharge);form.addRow('방전 Cycle',self.step_discharge_cycle)
        else:
            form.addRow('분석 방향',self.direction);form.addRow('Cycle 선택',self.cycles)
        self.available=QtWidgets.QLabel('');self.available.setWordWrap(True);form.addRow(self.available)
        self.compare_panel=QtWidgets.QWidget();compare_form=QtWidgets.QFormLayout(self.compare_panel);compare_form.setContentsMargins(0,4,0,4)
        self.compare_channel=QtWidgets.QComboBox();compare_form.addRow('비교 채널 (B)',self.compare_channel);self.lock_wheel(self.compare_channel)
        self.compare_cycles=QtWidgets.QLineEdit('1');self.compare_cycles.setPlaceholderText('비교 파일 Cycle')
        self.compare_step_charge=QtWidgets.QLineEdit();self.compare_step_charge.setPlaceholderText('비교 파일 충전 Step')
        self.compare_step_discharge=QtWidgets.QLineEdit();self.compare_step_discharge.setPlaceholderText('비교 파일 방전 Step')
        self.compare_step_charge_cycle=QtWidgets.QLineEdit();self.compare_step_charge_cycle.setPlaceholderText('비교 파일 충전 Cycle')
        self.compare_step_discharge_cycle=QtWidgets.QLineEdit();self.compare_step_discharge_cycle.setPlaceholderText('비교 파일 방전 Cycle')
        if self.selection_mode=='step':
            compare_form.addRow('충전 Step (B)',self.compare_step_charge);compare_form.addRow('충전 Cycle (B)',self.compare_step_charge_cycle)
            compare_form.addRow('방전 Step (B)',self.compare_step_discharge);compare_form.addRow('방전 Cycle (B)',self.compare_step_discharge_cycle)
        else:compare_form.addRow('비교 Cycle (B)',self.compare_cycles)
        self.compare_available=QtWidgets.QLabel('');self.compare_available.setWordWrap(True);compare_form.addRow(self.compare_available)
        form.addRow(self.compare_panel);self.compare_panel.setVisible(False)
        self.points=self.spin(50,20000,500,50);form.addRow('보간 포인트 수',self.points);self.lock_wheel(self.points)
        self.smooth=QtWidgets.QCheckBox('스무딩 사용');self.smooth.setChecked(True);form.addRow(self.smooth)
        self.auto=QtWidgets.QCheckBox('윈도 자동');self.auto.setChecked(True);form.addRow(self.auto)
        self.window=self.spin(5,19999,21,2);form.addRow('윈도 (포인트)',self.window);self.lock_wheel(self.window)
        self.poly=self.spin(1,10,3);form.addRow('다항식 차수',self.poly);self.lock_wheel(self.poly)
        self.prom=QtWidgets.QDoubleSpinBox();self.prom.setRange(.01,100);self.prom.setValue(3);self.prom.setSuffix(' %');form.addRow('피크 민감도',self.prom);self.lock_wheel(self.prom)
        self.manual_upper=QtWidgets.QCheckBox('충전 상한전압 직접 지정');form.addRow(self.manual_upper)
        self.upper=QtWidgets.QDoubleSpinBox();self.upper.setRange(-100,1000);self.upper.setDecimals(4);self.upper.setValue(4.2);self.upper.setSuffix(' V');form.addRow(self.upper);self.lock_wheel(self.upper)
        self.absolute=QtWidgets.QCheckBox('방전 dQ/dV 절댓값 표시');form.addRow(self.absolute)
        self.show_peaks=QtWidgets.QCheckBox('피크 표시');self.show_peaks.setChecked(True);form.addRow(self.show_peaks)
        defaults_btn=QtWidgets.QPushButton('기본 계산 조건 복원');defaults_btn.clicked.connect(self.restore_defaults);form.addRow(defaults_btn)
        self.analyze_btn=QtWidgets.QPushButton('조건 적용 / 분석');self.analyze_btn.setStyleSheet('background:#2563eb;color:white;padding:9px;');self.analyze_btn.clicked.connect(self.analyze);form.addRow(self.analyze_btn)
        for widget in [self.channel,self.direction,self.compare_channel]:widget.currentIndexChanged.connect(self.invalidate)
        self.channel.currentIndexChanged.connect(self.update_available)
        self.compare_channel.currentIndexChanged.connect(self.update_compare_available)
        for widget in [self.cycles,self.compare_cycles,self.step_charge,self.step_discharge,self.step_charge_cycle,self.step_discharge_cycle,self.compare_step_charge,self.compare_step_discharge,self.compare_step_charge_cycle,self.compare_step_discharge_cycle]:widget.textChanged.connect(self.invalidate)
        for widget in [self.points,self.window,self.poly,self.prom,self.upper]:widget.valueChanged.connect(self.invalidate)
        for widget in [self.smooth,self.auto,self.manual_upper,self.absolute,self.show_peaks]:widget.toggled.connect(self.invalidate)
        for widget in [self.smooth,self.auto,self.manual_upper]:widget.toggled.connect(self.sync_controls)
        self.points.valueChanged.connect(self.sync_controls)
        self.tabs=QtWidgets.QTabWidget();split.addWidget(self.tabs);split.setSizes([330,1100])
        graph_page=QtWidgets.QWidget();gl=QtWidgets.QVBoxLayout(graph_page);self.tabs.addTab(graph_page,'그래프')
        bar=QtWidgets.QHBoxLayout();gl.addLayout(bar)
        hint=QtWidgets.QLabel('색상:');bar.addWidget(hint)
        self.gradient_start=QtWidgets.QLabel('A 시작');self.gradient_start.setStyleSheet('color:#123b8a;font-weight:600;');bar.addWidget(self.gradient_start)
        self.gradient_bar=QtWidgets.QLabel();self.gradient_bar.setFixedSize(120,14);self.gradient_bar.setStyleSheet('border:1px solid #94a3b8;border-radius:3px;background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #123b8a,stop:.33 #8ec5ff,stop:.66 #ffaaa5,stop:1 #b91c1c);');bar.addWidget(self.gradient_bar)
        self.gradient_end=QtWidgets.QLabel('A 끝');self.gradient_end.setStyleSheet('color:#b91c1c;font-weight:600;');bar.addWidget(self.gradient_end)
        self.gradient_b_start=QtWidgets.QLabel('B 시작');self.gradient_b_start.setStyleSheet('color:#1f2937;font-weight:600;');bar.addWidget(self.gradient_b_start)
        self.gradient_b_bar=QtWidgets.QLabel();self.gradient_b_bar.setFixedSize(120,14);self.gradient_b_bar.setStyleSheet('border:1px solid #94a3b8;border-radius:3px;background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #1f2937,stop:.33 #b8c0cc,stop:.66 #d8b4fe,stop:1 #6d28d9);');bar.addWidget(self.gradient_b_bar)
        self.gradient_b_end=QtWidgets.QLabel('B 끝');self.gradient_b_end.setStyleSheet('color:#6d28d9;font-weight:600;');bar.addWidget(self.gradient_b_end)
        self.compare_gradient_widgets=[self.gradient_b_start,self.gradient_b_bar,self.gradient_b_end]
        for widget in self.compare_gradient_widgets:widget.setVisible(False)
        style_note=QtWidgets.QLabel('실선 충전 / 점선 방전');style_note.setStyleSheet('color:#475569;');bar.addWidget(style_note);bar.addStretch()
        self.vq_toggle=QtWidgets.QToolButton();self.vq_toggle.setCheckable(True);self.vq_toggle.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.vq_toggle.toggled.connect(self.toggle_raw_vq);bar.addWidget(self.vq_toggle)
        self.drag=QtWidgets.QComboBox();self.drag.addItems(['드래그 이동','영역 확대']);bar.addWidget(self.drag)
        reset=QtWidgets.QPushButton('전체 범위');reset.clicked.connect(self.reset_axes);bar.addWidget(reset)
        self.coordinate=QtWidgets.QLabel('곡선 위로 마우스를 이동하세요.');self.coordinate.setStyleSheet('font-family:Consolas;font-size:13px;padding:5px;background:#eef4ff;');self.coordinate.setFixedHeight(32);self.coordinate.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,QtWidgets.QSizePolicy.Policy.Fixed);gl.addWidget(self.coordinate)
        self.plots=[];self.crosshairs=[];self.traces=[];self.proxies=[]
        self.main_charts=QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal);gl.addWidget(self.main_charts,1)
        self.main_dqdv_charts=self.stacked_charts(self.main_charts,['dQ/dV · 충전','dQ/dV · 방전'])
        self.main_dvdq_charts=self.stacked_charts(self.main_charts,['dV/dQ · 충전','dV/dQ · 방전'])
        self.main_vq=pg.PlotWidget(title='원본 V–Q');self.main_vq.showGrid(x=True,y=True,alpha=.2)
        for axis in ['bottom','left']:self.main_vq.getAxis(axis).enableAutoSIPrefix(False)
        self.main_charts.addWidget(self.main_vq);self.register_plot(self.main_vq)
        self.main_charts.setSizes([500,500,300]);self.toggle_raw_vq(False);self.drag.currentIndexChanged.connect(self.set_drag)
        selection_word='Step' if self.selection_mode=='step' else 'Cycle'
        detail_page=QtWidgets.QWidget();detail_layout=QtWidgets.QVBoxLayout(detail_page);self.tabs.addTab(detail_page,'단일 '+selection_word+' 상세')
        detail_header=QtWidgets.QHBoxLayout();self.detail_label=QtWidgets.QLabel('상세 '+selection_word+' (A)');detail_header.addWidget(self.detail_label)
        self.detail_cycle=QtWidgets.QComboBox();self.detail_cycle.currentIndexChanged.connect(self.update_detail);detail_header.addWidget(self.detail_cycle)
        self.detail_compare_label=QtWidgets.QLabel('상세 '+selection_word+' (B)');detail_header.addWidget(self.detail_compare_label)
        self.detail_compare_cycle=QtWidgets.QComboBox();self.detail_compare_cycle.currentIndexChanged.connect(self.update_detail);detail_header.addWidget(self.detail_compare_cycle)
        self.detail_compare_widgets=[self.detail_compare_label,self.detail_compare_cycle]
        for widget in self.detail_compare_widgets:widget.setVisible(False)
        if self.selection_mode=='step':
            self.detail_label.setText('지정한 충전·방전 Step');self.detail_cycle.setVisible(False)
        detail_header.addWidget(QtWidgets.QLabel('각 파일의 선택 '+selection_word+' 충전·방전 V–Q와 dQ/dV를 함께 표시합니다.'));detail_header.addStretch();detail_layout.addLayout(detail_header)
        detail_charts=QtWidgets.QSplitter(QtCore.Qt.Orientation.Horizontal);detail_layout.addWidget(detail_charts,1)
        self.detail_dqdv_charts=self.stacked_charts(detail_charts,['dQ/dV · 충전','dQ/dV · 방전'],legend=True)
        self.detail_vq_charts=self.stacked_charts(detail_charts,['V–Q · 충전','V–Q · 방전'],legend=True)
        detail_charts.setSizes([550,550])
        peak_page=QtWidgets.QWidget();peak_layout=QtWidgets.QVBoxLayout(peak_page);self.tabs.addTab(peak_page,'피크 전압 추이')
        trend_word='Step' if self.selection_mode=='step' else 'cycle'
        peak_layout.addWidget(QtWidgets.QLabel('선택한 '+trend_word+'에서 검출된 dQ/dV peak(○)와 valley(×)의 전압 위치입니다. dV/dQ 극값은 피크 표에서 확인합니다.'))
        peak_plot=pg.PlotWidget(title=trend_word+'별 dQ/dV Extrema Voltage');peak_plot.addLegend();peak_plot.showGrid(x=True,y=True,alpha=.2)
        peak_plot.setLabel('bottom',trend_word);peak_plot.setLabel('left','Extrema Voltage',units='V');peak_layout.addWidget(peak_plot,1);self.register_plot(peak_plot)
        self.peak_table=QtWidgets.QTableWidget();self.tabs.addTab(self.peak_table,'피크 표')
        self.segment_view=QtWidgets.QTableWidget();self.tabs.addTab(self.segment_view,'구간 / 품질')
        self.preview=QtWidgets.QTableWidget();self.tabs.addTab(self.preview,'원본 미리보기')
        export_bar=QtWidgets.QHBoxLayout();outer.addLayout(export_bar);self.exports=[]
        for text,action in [('곡선 CSV',lambda:self.export_csv(False)),('피크 CSV',lambda:self.export_csv(True)),
                            ('분석 설정 JSON',self.export_settings),('그래프 PNG',self.export_png)]:
            b=QtWidgets.QPushButton(text);b.clicked.connect(action);export_bar.addWidget(b);self.exports.append(b)
        self.status=QtWidgets.QLabel('CSV를 불러오세요.');self.status.setWordWrap(False);self.status.setFixedHeight(28);self.status.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,QtWidgets.QSizePolicy.Policy.Fixed);outer.addWidget(self.status)
        self.sync_controls();self.invalidate()

    @staticmethod
    def spin(low,high,value,step=1):
        w=QtWidgets.QSpinBox();w.setRange(low,high);w.setValue(value);w.setSingleStep(step);return w

    def stacked_charts(self,parent,titles,legend=False):
        """Create vertically separated charge/discharge plots in one metric column."""
        container=QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical);parent.addWidget(container)
        for title in titles:
            plot=pg.PlotWidget(title=title)
            if legend:plot.addLegend()
            plot.showGrid(x=True,y=True,alpha=.2)
            for axis in ['bottom','left']:plot.getAxis(axis).enableAutoSIPrefix(False)
            container.addWidget(plot);self.register_plot(plot)
        container.setSizes([1,1])
        return container

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

    def toggle_raw_vq(self,visible):
        self.plots[self.MAIN_VQ].setVisible(visible)
        self.vq_toggle.setArrowType(QtCore.Qt.ArrowType.DownArrow if visible else QtCore.Qt.ArrowType.RightArrow)
        self.vq_toggle.setText('원본 V–Q 숨기기' if visible else '원본 V–Q 보기')
        self.main_charts.setSizes([400,400,300] if visible else [500,500,0])

    @staticmethod
    def cycle_color(index,total,source_index=0):
        """Interpolate each source through its own readable cycle palette."""
        palettes=(('#123b8a','#8ec5ff','#ffaaa5','#b91c1c'),
                  ('#1f2937','#b8c0cc','#d8b4fe','#6d28d9'))
        stops=[QtGui.QColor(value) for value in palettes[min(source_index,len(palettes)-1)]]
        position=(index/max(total-1,1))*(len(stops)-1)
        lower=min(int(position),len(stops)-2);fraction=position-lower
        start,end=stops[lower],stops[lower+1]
        return QtGui.QColor(round(start.red()+(end.red()-start.red())*fraction),round(start.green()+(end.green()-start.green())*fraction),round(start.blue()+(end.blue()-start.blue())*fraction))

    def invalidate(self,*args):
        if hasattr(self,'exports'):
            for b in self.exports:b.setEnabled(False)
            self.status.setText('조건이 바뀌었습니다. 조건 적용 / 분석을 누르세요.')

    def restore_defaults(self):
        self.points.setValue(500);self.smooth.setChecked(True);self.auto.setChecked(True)
        self.poly.setValue(3);self.prom.setValue(3);self.manual_upper.setChecked(False)
        self.absolute.setChecked(False);self.sync_controls()

    def return_home(self):
        if self.home is not None:
            self.home.show();self.close()

    def open_file(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'Cycling CSV','','CSV (*.csv)')
        if path:
            try:self.load_file(path)
            except Exception as exc:QtWidgets.QMessageBox.warning(self,'파일 읽기 실패',str(exc))

    def open_compare_file(self):
        path,_=QtWidgets.QFileDialog.getOpenFileName(self,'비교 Cycling CSV','','CSV (*.csv)')
        if not path:return
        try:
            self.load_compare_file(path)
        except Exception as exc:QtWidgets.QMessageBox.warning(self,'비교 파일 읽기 실패',str(exc))

    def load_compare_file(self,path):
        raw,encoding=read_csv(Path(path).read_bytes())
        mapping={key:self.best_mapping_column(key,raw) for key in self.mapping}
        required={'cycle':'Cycle 열','voltage':'전압 열','current':'전류 열','capacity':'용량 열'}
        if self.selection_mode=='step':required['step']='Step 열'
        missing=[label for key,label in required.items() if not mapping[key]]
        if missing:raise ValueError('자동으로 찾지 못한 항목: '+', '.join(missing))
        units={'voltage':self.infer_unit('voltage',mapping['voltage'],raw),'current':self.infer_unit('current',mapping['current'],raw),
               'capacity':self.infer_unit('capacity',mapping['capacity'],raw),'time':'H:M:S / Nd H:M:S'}
        self.compare_raw=raw;self.compare_mapping=mapping;self.compare_units=units;self.compare_filename=str(path);self.compare_encoding=encoding
        self.compare_df=normalize(raw,mapping,units,self.positive.isChecked())
        self.compare_channel.clear();self.compare_channel.addItems(list(self.compare_df.channel.unique()))
        if self.selection_mode=='step':
            self.set_default_steps(self.compare_df,self.compare_channel.currentText(),self.compare_step_charge,self.compare_step_charge_cycle,self.compare_step_discharge,self.compare_step_discharge_cycle)
        else:self.compare_cycles.setText(str(self.compare_df.cycle.iloc[0]))
        self.compare_panel.setVisible(True);self.remove_compare_btn.setVisible(True)
        for widget in self.compare_gradient_widgets:widget.setVisible(True)
        for widget in self.detail_compare_widgets:widget.setVisible(self.selection_mode!='step')
        self.refresh_file_label();self.update_compare_available();self.invalidate()

    def remove_compare_file(self):
        self.compare_raw=None;self.compare_df=None;self.compare_filename='';self.compare_channel.clear();self.compare_panel.setVisible(False);self.remove_compare_btn.setVisible(False)
        self.detail_compare_cycle.clear()
        for widget in self.compare_gradient_widgets+self.detail_compare_widgets:widget.setVisible(False)
        self.refresh_file_label();self.invalidate()

    def load_file(self,path):
        self.raw,encoding=read_csv(Path(path).read_bytes());self.filename=str(path)
        self.encoding=encoding
        for key,combo in self.mapping.items():
            combo.clear()
            if key in ('channel','step','type','time'):combo.addItem('(없음)')
            combo.addItems(list(self.raw.columns))
            selected=self.best_mapping_column(key,self.raw)
            combo.setCurrentIndex(combo.findText(selected) if selected is not None else -1)
        for key in ['voltage','current','capacity']:
            self.units[key].setCurrentText(self.infer_unit(key, self.mapping[key].currentText(),self.raw))
        self.refresh_file_label()
        self.fill_table(self.preview,self.raw.head(100))
        self.apply_mapping()
        if self.selection_mode=='step':self.set_default_steps(self.df,self.channel.currentText(),self.step_charge,self.step_charge_cycle,self.step_discharge,self.step_discharge_cycle)
        else:self.cycles.setText(str(self.df.cycle.iloc[0]))
        self.analyze()

    @staticmethod
    def normalized_column_name(value):
        return ''.join(char for char in str(value).lower() if char.isalnum())

    def refresh_file_label(self):
        if self.raw is None:
            self.file_label.setText('CSV 파일을 선택하세요.');return
        primary=f'A: {Path(self.filename).name} · {len(self.raw):,}행 · {self.encoding} · 전압: {self.mapping["voltage"].currentText()} / {self.units["voltage"].currentText()}'
        if self.compare_raw is not None:
            primary+=f' | B: {Path(self.compare_filename).name} · {len(self.compare_raw):,}행 · 전압: {self.compare_mapping["voltage"]} / {self.compare_units["voltage"]}'
        self.file_label.setText(primary)

    def best_mapping_column(self,key,raw=None):
        """Match a meaningful measurement column; never fall back to DataSequence."""
        raw=self.raw if raw is None else raw
        columns=[str(column) for column in raw.columns]
        default=self.defaults[key]
        if default in columns:return default
        default_norm=self.normalized_column_name(default)
        for column in columns:
            if self.normalized_column_name(column)==default_norm:return column
        aliases={
            'channel':['channel','channelno','ch'], 'cycle':['totcycle','cycle','cyc'],
            'step':['stepno','step','stage'], 'type':['type','mode','state','status'],
            'time':['tottime','steptime','elapsedtime','time'],
            'voltage':['voltage','volt','vtg','전압'], 'current':['current','curr','crt','전류'],
            'capacity':['capacity','capa','cap','용량'],
        }[key]
        best_score,best_column=-1,None
        for column in columns:
            name=self.normalized_column_name(column)
            for order,alias in enumerate(aliases):
                if name.startswith(alias):score=100-order
                elif alias in name:score=70-order
                else:continue
                if key=='voltage' and any(token in name for token in ('avg','mean','set')):score-=40
                if score>best_score:best_score,best_column=score,column
        return best_column

    def infer_unit(self,key,column,raw=None):
        """Use numeric plausibility before a possibly incorrect column-unit suffix."""
        raw=self.raw if raw is None else raw
        label=column.lower().replace('μ','µ')
        if key=='voltage':
            values=pd.to_numeric(raw[column],errors='coerce').dropna()
            if not values.empty:
                magnitude=values.abs().replace(0,np.nan).median()
                plausible=[]
                for unit,scale in [('V',1),('mV',.001),('µV',.000001)]:
                    if pd.notna(magnitude) and .05 <= magnitude*scale <= 20:
                        plausible.append(unit)
                if len(plausible)==1:return plausible[0]
                if magnitude >= 100000:return 'µV'
                if magnitude >= 100:return 'mV'
            if any(token in label for token in ('µv','uv','microvolt')):return 'µV'
            if any(token in label for token in ('mv','millivolt')):return 'mV'
            return 'V'
        return 'mA' if key=='current' and '(m' in label else 'mAh' if key=='capacity' and '(m' in label else 'A' if key=='current' else 'Ah'

    def apply_mapping_safe(self):
        try:self.apply_mapping()
        except Exception as exc:QtWidgets.QMessageBox.warning(self,'열 설정 확인',str(exc))

    def apply_mapping(self):
        if self.raw is None:raise ValueError('CSV를 먼저 불러오세요.')
        self.mapping_values={k:(None if w.currentText() in ('(없음)','') else w.currentText()) for k,w in self.mapping.items()}
        required={'cycle':'Cycle 열','voltage':'전압 열','current':'전류 열','capacity':'용량 열'}
        if self.selection_mode=='step':required['step']='Step 열'
        missing=[label for key,label in required.items() if not self.mapping_values[key]]
        if missing:raise ValueError('자동으로 찾지 못한 항목: '+', '.join(missing)+' — 열 · 단위 설정 보기에서 선택하세요.')
        self.unit_values={k:w.currentText() for k,w in self.units.items()}
        self.df=normalize(self.raw,self.mapping_values,self.unit_values,self.positive.isChecked())
        old=self.channel.currentText();self.channel.clear();self.channel.addItems(list(self.df.channel.unique()))
        idx=self.channel.findText(old)
        if idx>=0:self.channel.setCurrentIndex(idx)
        self.fill_table(self.segment_view,segment_table(self.df));self.update_available()

    def update_available(self,*args):
        if self.df is None:return
        if self.selection_mode=='step':
            channel_df=self.df[self.df.channel==self.channel.currentText()]
            charge=list(channel_df[channel_df.direction=='charge'].step.unique());discharge=list(channel_df[channel_df.direction=='discharge'].step.unique())
            self.available.setText('추출된 Step — 충전: '+(', '.join(charge[:16]) or '없음')+(' …' if len(charge)>16 else '')+'\n방전: '+(', '.join(discharge[:16]) or '없음')+(' …' if len(discharge)>16 else ''))
            return
        cycles=list(self.df[self.df.channel==self.channel.currentText()].cycle.unique())
        if not cycles:
            self.available.setText('추출된 Cycle이 없습니다. 열·단위 설정을 확인하세요.')
            return
        preview=', '.join(cycles[:16])+(' …' if len(cycles)>16 else '')
        self.available.setText(f'추출된 전체 Cycle: {len(cycles):,}개  |  범위: {cycles[0]} ~ {cycles[-1]}\n입력 예: 1,5,10-50:5 또는 전체\n사용 가능: {preview}')

    @staticmethod
    def set_default_steps(df,channel,charge_box,charge_cycle_box,discharge_box,discharge_cycle_box):
        subset=df[df.channel==channel]
        charge_step=lowest_current_step(subset,'charge');discharge_step=lowest_current_step(subset,'discharge')
        charge_box.setText(charge_step);charge_cycle_box.setText(latest_cycle_for_step(subset,charge_step,'charge'))
        discharge_box.setText(discharge_step);discharge_cycle_box.setText(latest_cycle_for_step(subset,discharge_step,'discharge'))

    def update_compare_available(self,*args):
        if self.compare_df is None:return
        if self.selection_mode=='step':
            channel_df=self.compare_df[self.compare_df.channel==self.compare_channel.currentText()]
            charge=list(channel_df[channel_df.direction=='charge'].step.unique());discharge=list(channel_df[channel_df.direction=='discharge'].step.unique())
            self.compare_available.setText('비교 파일 Step — 충전: '+(', '.join(charge[:12]) or '없음')+(' …' if len(charge)>12 else '')+'\n방전: '+(', '.join(discharge[:12]) or '없음')+(' …' if len(discharge)>12 else ''))
            return
        cycles=list(self.compare_df[self.compare_df.channel==self.compare_channel.currentText()].cycle.unique())
        if not cycles:
            self.compare_available.setText('비교 파일에서 추출된 Cycle이 없습니다.');return
        preview=', '.join(cycles[:12])+(' …' if len(cycles)>12 else '')
        self.compare_available.setText(f'비교 파일 전체 Cycle: {len(cycles):,}개  |  범위: {cycles[0]} ~ {cycles[-1]}\n사용 가능: {preview}')

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
            if self.selection_mode=='step':
                directions=['charge','discharge']
                chosen=[value for value in [self.step_charge.text().strip(),self.step_discharge.text().strip()] if value]
                entries=[(self.step_charge.text().strip(),self.step_charge_cycle.text().strip(),'charge'),(self.step_discharge.text().strip(),self.step_discharge_cycle.text().strip(),'discharge')]
                entries=[entry for entry in entries if entry[0] and entry[1]]
                missing=[]
                if not entries:raise ValueError('충전/방전 Step과 Cycle을 한 쌍 이상 입력하세요.')
                sources=[('파일 A',channel_df,channel_df,entries,0)]
            else:
                directions=['charge','discharge'] if self.direction.currentIndex()==0 else ['charge' if self.direction.currentIndex()==1 else 'discharge']
                subset=channel_df[channel_df.direction.isin(directions)]
                chosen,missing=select_cycles(self.cycles.text(),list(subset.cycle.unique()))
                if not chosen:raise ValueError('파일 A에 해당 Cycle 데이터가 없습니다.')
                entries=[(cycle,'',direction) for cycle in chosen for direction in directions]
                sources=[('파일 A',channel_df,subset,entries,0)]
            compare_missing=[];compare_chosen=[]
            if self.compare_df is not None:
                self.compare_df=normalize(self.compare_raw,self.compare_mapping,self.compare_units,self.positive.isChecked())
                compare_df=self.compare_df[self.compare_df.channel==self.compare_channel.currentText()]
                if self.selection_mode=='step':
                    compare_chosen=[value for value in [self.compare_step_charge.text().strip(),self.compare_step_discharge.text().strip()] if value]
                    compare_entries=[(self.compare_step_charge.text().strip(),self.compare_step_charge_cycle.text().strip(),'charge'),(self.compare_step_discharge.text().strip(),self.compare_step_discharge_cycle.text().strip(),'discharge')]
                    compare_entries=[entry for entry in compare_entries if entry[0] and entry[1]]
                    if not compare_entries:raise ValueError('파일 B의 충전/방전 Step과 Cycle을 한 쌍 이상 입력하세요.')
                    sources.append(('파일 B',compare_df,compare_df,compare_entries,1))
                else:
                    compare_subset=compare_df[compare_df.direction.isin(directions)]
                    compare_chosen,compare_missing=select_cycles(self.compare_cycles.text(),list(compare_subset.cycle.unique()))
                    if not compare_chosen:raise ValueError('파일 B에 해당 Cycle 데이터가 없습니다.')
                    compare_entries=[(cycle,'',direction) for cycle in compare_chosen for direction in directions]
                    sources.append(('파일 B',compare_df,compare_subset,compare_entries,1))
            if self.smooth.isChecked() and not self.auto.isChecked():
                if self.window.value()%2==0 or self.window.value()>=self.points.value() or self.window.value()<=self.poly.value():
                    raise ValueError('윈도는 홀수이며 보간 수보다 작고 다항식 차수보다 커야 합니다.')
            params=dict(n_points=self.points.value(),smooth=self.smooth.isChecked(),smooth_window=None if self.auto.isChecked() else self.window.value(),
                        smooth_polyorder=self.poly.value(),peak_prominence_pct=self.prom.value()/100,upper_voltage_v=self.upper.value() if self.manual_upper.isChecked() else None)
            self.results=[];self.peak_rows=[];self.detail_records=[];excluded=[]
            self.gradient_start.setText(f'A {chosen[0]}')
            self.gradient_end.setText(f'A {chosen[-1]}')
            for widget in self.compare_gradient_widgets:widget.setVisible(self.compare_df is not None)
            for widget in self.detail_compare_widgets:widget.setVisible(self.compare_df is not None and self.selection_mode!='step')
            if self.compare_df is not None:
                self.gradient_b_start.setText(f'B {compare_chosen[0]}')
                self.gradient_b_end.setText(f'B {compare_chosen[-1]}')
            self.crosshairs=[None for _ in self.plots]
            for index in range(len(self.plots)):self.reset_plot(index)
            for source_name,source_df,source_subset,source_entries,source_index in sources:
                for ci,(selection,selected_cycle,direction) in enumerate(source_entries):
                        r,report=(calculate_step(source_df,selection,direction,cycle=selected_cycle,**params) if self.selection_mode=='step' else calculate_cycle(source_df,selection,direction,**params))
                        if r is None:excluded.append(f'{source_name} {selection} {direction}: '+report['reason']);continue
                        selection_label=('Step' if self.selection_mode=='step' else 'Cycle')
                        cycle=selected_cycle or selection
                        name=f'{source_name} · {selection_label} {selection}'+(f' · Cycle {selected_cycle}' if self.selection_mode=='step' else '')+' · '+('충전' if direction=='charge' else '방전')
                        color=self.cycle_color(ci,max(len(source_entries),2),source_index)
                        pen=pg.mkPen(color,width=2,style=QtCore.Qt.PenStyle.SolidLine if direction=='charge' else QtCore.Qt.PenStyle.DashLine)
                        y=np.abs(r['dqdv']) if self.absolute.isChecked() else r['dqdv']
                        main_dqdv=self.MAIN_DQDV_CHARGE if direction=='charge' else self.MAIN_DQDV_DISCHARGE
                        main_dvdq=self.MAIN_DVDQ_CHARGE if direction=='charge' else self.MAIN_DVDQ_DISCHARGE
                        item=self.plots[main_dqdv].plot(r['voltage_grid'],y,pen=pen)
                        self.traces[main_dqdv].append((item,r['voltage_grid'],y,name))
                        item_dvdq=self.plots[main_dvdq].plot(r['capacity_grid'],r['dvdq'],pen=pen)
                        self.traces[main_dvdq].append((item_dvdq,r['capacity_grid'],r['dvdq'],name))
                        g=(source_subset[(source_subset.step.astype(str)==str(selection))&(source_subset.cycle.astype(str)==str(selected_cycle))&(source_subset.direction==direction)] if self.selection_mode=='step' else source_subset[(source_subset.cycle==cycle)&(source_subset.direction==direction)])
                        xq,yv=g.capacity.to_numpy()*1000,g.voltage.to_numpy()
                        itemq=self.plots[self.MAIN_VQ].plot(xq,yv,pen=pen);self.traces[self.MAIN_VQ].append((itemq,xq,yv,name))
                        if self.show_peaks.isChecked():
                            self.plots[main_dqdv].plot(r['dqdv_peak_voltage'],np.abs(r['dqdv_peak_value']) if self.absolute.isChecked() else r['dqdv_peak_value'],pen=None,symbol='o',symbolSize=7,symbolPen=color,symbolBrush='w')
                            self.plots[main_dqdv].plot(r['dqdv_valley_voltage'],np.abs(r['dqdv_valley_value']) if self.absolute.isChecked() else r['dqdv_valley_value'],pen=None,symbol='x',symbolSize=8,symbolPen=color)
                            self.plots[main_dvdq].plot(r['dvdq_peak_capacity'],r['dvdq_peak_value'],pen=None,symbol='o',symbolSize=7,symbolPen=color,symbolBrush='w')
                            self.plots[main_dvdq].plot(r['dvdq_valley_capacity'],r['dvdq_valley_value'],pen=None,symbol='x',symbolSize=8,symbolPen=color)
                        curve=pd.DataFrame(dict(source=source_name,cycle=cycle,direction=direction,voltage_V=r['voltage_grid'],capacity_mAh=r['capacity_on_vgrid'],dqdv_mAh_per_V=r['dqdv']))
                        self.results.append(curve)
                        self.detail_records.append(dict(source_index=source_index,cycle=cycle,direction=direction,result=r,raw=g,pen=pen,name=name))
                        extrema=[('dQ/dV','peak',r['dqdv_peak_voltage'],r['dqdv_peak_value']),('dQ/dV','valley',r['dqdv_valley_voltage'],r['dqdv_valley_value']),
                                 ('dV/dQ','peak',r['dvdq_peak_capacity'],r['dvdq_peak_value']),('dV/dQ','valley',r['dvdq_valley_capacity'],r['dvdq_valley_value'])]
                        for metric,kind,axis,derivative in extrema:
                            self.peak_rows.extend(dict(source=source_name,cycle=cycle,direction=direction,metric=metric,kind=kind,axis_value=float(x),derivative_value=float(y)) for x,y in zip(axis,derivative))
            for index in (self.MAIN_DQDV_CHARGE,self.MAIN_DQDV_DISCHARGE):
                self.plots[index].setLabel('bottom','Voltage',units='V');self.plots[index].setLabel('left','|dQ/dV|' if self.absolute.isChecked() else 'dQ/dV',units='mAh/V')
            for index in (self.MAIN_DVDQ_CHARGE,self.MAIN_DVDQ_DISCHARGE):
                self.plots[index].setLabel('bottom','Capacity',units='mAh');self.plots[index].setLabel('left','dV/dQ',units='V/mAh')
            self.plots[self.MAIN_VQ].setLabel('bottom','Capacity',units='mAh');self.plots[self.MAIN_VQ].setLabel('left','Voltage',units='V')
            self.fill_table(self.peak_table,pd.DataFrame(self.peak_rows,columns=['source','cycle','direction','metric','kind','axis_value','derivative_value']))
            self.detail_cycle.blockSignals(True);self.detail_cycle.clear();self.detail_cycle.addItems(chosen);self.detail_cycle.blockSignals(False)
            self.detail_compare_cycle.blockSignals(True);self.detail_compare_cycle.clear()
            if self.compare_df is not None:self.detail_compare_cycle.addItems(compare_chosen)
            self.detail_compare_cycle.blockSignals(False)
            self.update_detail();self.update_peak_trend()
            self.settings=dict(file_a=Path(self.filename).name,mapping_a=self.mapping_values,units_a=self.unit_values,positive_charge=self.positive.isChecked(),
                channel_a=self.channel.currentText(),cycles_a=chosen,file_b=Path(self.compare_filename).name if self.compare_raw is not None else None,
                channel_b=self.compare_channel.currentText() if self.compare_raw is not None else None,cycles_b=compare_chosen,directions=directions,parameters=params,absolute_display=self.absolute.isChecked())
            self.reset_axes();self.set_drag()
            for b in self.exports:b.setEnabled(bool(self.results))
            missing_text=missing+compare_missing
            missing_kind='Step' if self.selection_mode=='step' else 'cycle'
            self.status.setText(f'{len(self.results)}개 곡선 · {len(self.peak_rows)}개 피크'+(f' | 없는 {missing_kind}: '+', '.join(missing_text) if missing_text else '')+(' | 제외: '+'; '.join(excluded[:8]) if excluded else ''))
            self.coordinate.setText('곡선 위로 마우스를 이동하세요.');self.tabs.setCurrentIndex(0)
        except Exception as exc:
            self.status.setText(f'분석할 수 없습니다 ({type(exc).__name__}): {exc}')
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
        if index in (self.MAIN_DQDV_CHARGE,self.MAIN_DQDV_DISCHARGE,self.DETAIL_DQDV_CHARGE,self.DETAIL_DQDV_DISCHARGE):self.coordinate.setText(f'{name} | Voltage {x:.5f} V | dQ/dV {y:.4f} mAh/V')
        elif index in (self.MAIN_DVDQ_CHARGE,self.MAIN_DVDQ_DISCHARGE):self.coordinate.setText(f'{name} | Capacity {x:.4f} mAh | dV/dQ {y:.6f} V/mAh')
        elif index in (self.MAIN_VQ,self.DETAIL_VQ_CHARGE,self.DETAIL_VQ_DISCHARGE):self.coordinate.setText(f'{name} | Capacity {x:.4f} mAh | Voltage {y:.5f} V')
        else:self.coordinate.setText(f'{name} | Cycle {x:.0f} | Peak Voltage {y:.5f} V')

    def set_drag(self,*args):
        for p in self.plots:p.plotItem.vb.setMouseMode(pg.ViewBox.PanMode if self.drag.currentIndex()==0 else pg.ViewBox.RectMode)

    def reset_axes(self):
        for p in self.plots:p.autoRange()

    def update_detail(self,*args):
        if not hasattr(self,'detail_records') or (self.selection_mode!='step' and not self.detail_cycle.currentText()):return
        for index in (self.DETAIL_DQDV_CHARGE,self.DETAIL_DQDV_DISCHARGE,self.DETAIL_VQ_CHARGE,self.DETAIL_VQ_DISCHARGE):self.reset_plot(index)
        selected_cycles={} if self.selection_mode=='step' else {0:self.detail_cycle.currentText()}
        if self.selection_mode!='step' and self.compare_df is not None and self.detail_compare_cycle.currentText():selected_cycles[1]=self.detail_compare_cycle.currentText()
        for record in self.detail_records:
            if self.selection_mode!='step' and (record['source_index'] not in selected_cycles or record['cycle']!=selected_cycles[record['source_index']]):continue
            result,raw,pen,name=record['result'],record['raw'],record['pen'],record['name']
            y=np.abs(result['dqdv']) if self.absolute.isChecked() else result['dqdv']
            detail_dqdv=self.DETAIL_DQDV_CHARGE if record['direction']=='charge' else self.DETAIL_DQDV_DISCHARGE
            detail_vq=self.DETAIL_VQ_CHARGE if record['direction']=='charge' else self.DETAIL_VQ_DISCHARGE
            item=self.plots[detail_dqdv].plot(result['voltage_grid'],y,pen=pen,name=name)
            self.traces[detail_dqdv].append((item,result['voltage_grid'],y,name))
            xq,yv=raw.capacity.to_numpy()*1000,raw.voltage.to_numpy()
            item=self.plots[detail_vq].plot(xq,yv,pen=pen,name=name)
            self.traces[detail_vq].append((item,xq,yv,name))
            if self.show_peaks.isChecked():
                self.plots[detail_dqdv].plot(result['dqdv_peak_voltage'],np.abs(result['dqdv_peak_value']) if self.absolute.isChecked() else result['dqdv_peak_value'],pen=None,symbol='o',symbolSize=8,symbolPen=pen.color(),symbolBrush='w')
                self.plots[detail_dqdv].plot(result['dqdv_valley_voltage'],np.abs(result['dqdv_valley_value']) if self.absolute.isChecked() else result['dqdv_valley_value'],pen=None,symbol='x',symbolSize=9,symbolPen=pen.color())
        for index in (self.DETAIL_DQDV_CHARGE,self.DETAIL_DQDV_DISCHARGE):
            self.plots[index].setLabel('bottom','Voltage',units='V');self.plots[index].setLabel('left','dQ/dV',units='mAh/V');self.plots[index].autoRange()
        for index in (self.DETAIL_VQ_CHARGE,self.DETAIL_VQ_DISCHARGE):
            self.plots[index].setLabel('bottom','Capacity',units='mAh');self.plots[index].setLabel('left','Voltage',units='V');self.plots[index].autoRange()

    def update_peak_trend(self):
        self.reset_plot(self.PEAK_TREND)
        if not self.peak_rows:return
        peaks=pd.DataFrame(self.peak_rows)
        peaks=peaks[peaks.metric=='dQ/dV']
        for direction,color,label in [('charge','#d97706','충전'),('discharge','#2563eb','방전')]:
            for kind,symbol in [('peak','o'),('valley','x')]:
                subset=peaks[(peaks.direction==direction)&(peaks.kind==kind)]
                if subset.empty:continue
                cycles=pd.to_numeric(subset.cycle,errors='coerce').to_numpy(dtype=float);voltages=subset.axis_value.to_numpy(dtype=float)
                valid=np.isfinite(cycles)&np.isfinite(voltages)
                cycles,voltages=cycles[valid],voltages[valid]
                if not len(cycles):continue
                name=f'{label} · '+('peak' if kind=='peak' else 'valley')
                item=self.plots[self.PEAK_TREND].plot(cycles,voltages,pen=None,symbol=symbol,symbolSize=8,symbolBrush=color if kind=='peak' else None,symbolPen=color,name=name)
                self.traces[self.PEAK_TREND].append((item,cycles,voltages,name))
        self.plots[self.PEAK_TREND].setLabel('bottom','Step' if self.selection_mode=='step' else 'Cycle');self.plots[self.PEAK_TREND].setLabel('left','Extrema Voltage',units='V');self.plots[self.PEAK_TREND].autoRange()

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
        frame=pd.DataFrame(self.peak_rows,columns=['source','cycle','direction','metric','kind','axis_value','derivative_value']) if peaks else pd.concat(self.results,ignore_index=True)
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
            try:pg.exporters.ImageExporter(self.plots[self.MAIN_DQDV_CHARGE].plotItem).export(path)
            except Exception as exc:QtWidgets.QMessageBox.warning(self,'저장 실패',str(exc))


def smoke(app,output):
    import tempfile
    from legacy_backend.dqdv import compute_dqdv
    with tempfile.TemporaryDirectory() as temp:
        suite=SuiteWindow();suite.show();app.processEvents()
        assert suite.windowTitle()=='Battery Analysis Suite'
        assert len(suite.findChildren(QtWidgets.QPushButton))==3
        suite.close()
        assert MainWindow.cycle_color(0,3,0).name().lower()=='#123b8a'
        assert MainWindow.cycle_color(2,3,0).name().lower()=='#b91c1c'
        assert MainWindow.cycle_color(0,3,1).name().lower()=='#1f2937'
        assert MainWindow.cycle_color(2,3,1).name().lower()=='#6d28d9'
        unit_probe=MainWindow();unit_probe.raw=pd.DataFrame({'DataSequence':[1_113_200,1_114_100],'Voltage(mV)':[1113.2,1114.1],'Voltage(uV)':[1_113_200,1_114_100]})
        assert unit_probe.best_mapping_column('voltage')=='Voltage(mV)'
        assert unit_probe.infer_unit('voltage','Voltage(mV)')=='mV'
        assert unit_probe.infer_unit('voltage','Voltage(uV)')=='µV'
        unit_probe.close()
        rows=[]
        for cycle in [1,5,10]:
            for direction,sign in [('충전',1),('방전',-1)]:
                for i in range(101):
                    q=i/100;v=3+q+.06*np.sin(q*12)
                    rows.append({'TotCycle':cycle,'StepNo':1 if sign>0 else 2,'Type':direction,'Voltage(V)':v if sign>0 else 7-v,'Current(mA)':sign*1000,'Capacity(mAh)':q*1000})
        raw=pd.DataFrame(rows);path=Path(temp)/'sample.csv';raw.to_csv(path,index=False,encoding='utf-8-sig')
        step_win=MainWindow(selection_mode='step');step_win.show();app.processEvents();step_win.load_file(path);app.processEvents()
        assert len(step_win.results)==2,step_win.status.text()
        assert step_win.step_charge_cycle.text()=='10' and step_win.step_discharge_cycle.text()=='10'
        step_win.close()
        win=MainWindow();win.show();app.processEvents();win.load_file(path)
        win.cycles.setText('1,5,10');win.analyze();app.processEvents()
        assert len(win.results)==6,win.status.text()
        assert len(win.traces[win.MAIN_DVDQ_CHARGE])==3 and len(win.traces[win.MAIN_DVDQ_DISCHARGE])==3
        assert len(win.traces[win.DETAIL_DQDV_CHARGE])==1 and len(win.traces[win.DETAIL_DQDV_DISCHARGE])==1
        assert len(win.traces[win.DETAIL_VQ_CHARGE])==1 and len(win.traces[win.DETAIL_VQ_DISCHARGE])==1
        assert len(win.traces[win.PEAK_TREND]) <= 4
        win.peak_rows=[dict(source='파일 A',cycle='1',direction='charge',metric='dQ/dV',kind='peak',axis_value=3.2,derivative_value=1.0),
                       dict(source='파일 A',cycle='1',direction='discharge',metric='dQ/dV',kind='valley',axis_value=3.1,derivative_value=-1.0),
                       dict(source='파일 A',cycle='2',direction='discharge',metric='dQ/dV',kind='peak',axis_value=3.0,derivative_value=-1.1)]
        win.update_peak_trend();assert len(win.traces[win.PEAK_TREND])==3
        for actual in win.results:
            cy=actual.cycle.iloc[0];dr=actual.direction.iloc[0]
            reference=pd.DataFrame(dict(Cycle=raw.TotCycle.astype(str),TypeStd=raw.Type.map({'충전':'CHARGE','방전':'DISCHARGE'}),Voltage_V=raw['Voltage(V)'],Capacity_mAh=raw['Capacity(mAh)'],_row=np.arange(len(raw))))
            expected=compute_dqdv(reference,cy,dr)
            np.testing.assert_allclose(actual.dqdv_mAh_per_V,expected['dqdv'],rtol=1e-9,atol=1e-7)
        compare_raw=raw.copy();compare_raw['Voltage(V)']+=.02
        compare_path=Path(temp)/'compare.csv';compare_raw.to_csv(compare_path,index=False,encoding='utf-8-sig')
        win.load_compare_file(compare_path);win.compare_cycles.setText('1,5,10');win.analyze();app.processEvents()
        assert len(win.results)==12 and {r.source.iloc[0] for r in win.results}=={'파일 A','파일 B'}
        assert len(win.traces[win.MAIN_DVDQ_CHARGE])==6 and len(win.traces[win.MAIN_DVDQ_DISCHARGE])==6
        assert len(win.traces[win.DETAIL_DQDV_CHARGE])==2 and len(win.traces[win.DETAIL_DQDV_DISCHARGE])==2
        assert len(win.traces[win.DETAIL_VQ_CHARGE])==2 and len(win.traces[win.DETAIL_VQ_DISCHARGE])==2
        win.detail_compare_cycle.setCurrentText('10');app.processEvents()
        assert win.detail_compare_cycle.currentText()=='10' and len(win.traces[win.DETAIL_DQDV_CHARGE])==2
        win.remove_compare_file()
        win.points.setValue(200);win.analyze();assert all(len(r)==200 for r in win.results)
        win.direction.setCurrentIndex(2);win.analyze();assert len(win.results)==3
        _,x,y,_=win.traces[win.MAIN_DQDV_DISCHARGE][0]
        point=win.plots[win.MAIN_DQDV_DISCHARGE].plotItem.vb.mapViewToScene(QtCore.QPointF(float(x[50]),float(y[50])))
        win.cursor_at(win.MAIN_DQDV_DISCHARGE,point);assert 'Voltage' in win.coordinate.text()
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
