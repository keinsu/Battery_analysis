# dQ/dV Cycling Desktop v0.4.0

`DQDVAnalyzer-Desktop.exe` 하나를 다운로드하고 실행합니다. Python 설치, 브라우저, 웹 서버, 별도 _internal 폴더가 필요하지 않습니다. 첫 실행 시 포함된 런타임을 임시 폴더에 풀기 때문에 잠시 걸릴 수 있습니다.

1. CSV 열기를 누르고 파일을 선택합니다.
2. 열과 단위를 확인합니다. 필요하면 왼쪽 설정을 바꾸고 열·단위 적용을 누릅니다.
3. Cycle에 `1,5,10-50:5` 또는 `전체`를 입력하고 충전/방전 방향을 선택합니다.
4. 조건 적용 / 분석을 누릅니다.
5. 마우스를 그래프 위로 이동하면 가까운 데이터점의 cycle·전압·dQ/dV 좌표와 십자선을 봅니다.
6. 휠로 확대/축소, 드래그 이동 또는 영역 확대, 전체 범위 버튼으로 초기화합니다.
7. 곡선 CSV, 피크 CSV, 분석 설정 JSON, 그래프 PNG를 저장할 수 있습니다.

계산은 첨부 원본 dqdv.py를 변경 없이 호출합니다. 기본 500포인트, Savitzky–Golay 21포인트/3차, 두 번 스무딩, 상한전압 기반 CV 제외, 피크 민감도 5%입니다. 입력 장비별 CSV 파서는 기존 Qt 프로그램 전체를 복제한 것이 아니며 열·단위 확인이 필요합니다.

여러 step의 용량 리셋은 원본 계산 로직처럼 합산하지 않습니다. 구간/품질 탭과 원본 V–Q도 확인하세요. 대용량 CSV 로드와 다수 cycle 계산 중에는 창이 잠시 응답을 기다릴 수 있습니다.

개발: Python 3.12에서 requirements-native.txt 설치 후 `python native_app.py`.
빌드: `python -m PyInstaller --noconfirm --clean native.spec`.
검증: `python verify_native.py dist/DQDVAnalyzer-Desktop.exe`.
