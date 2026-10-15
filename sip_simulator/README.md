# SiP Simulator – HBM/Stack별 결과 비교

## 데이터 폴더 규칙

SIP_DATA_ROOT 바로 아래에 HBM 세대와 Stack 수별 시뮬레이션 폴더를 둡니다.

```
SIP_DATA_ROOT/
  SIP_A_HBM3E_12H_POR/
    *.txt
    *.py
    *.inp
    *.odb
  SIP_A_HBM4_12H/
    *.txt
    *.py
    *.inp
    *.odb
  SIP_A_HBM4_8H/
    *.txt
    *.py
    *.inp
    *.odb
```

폴더명 규칙은 <SiP Product>_<HBM Gen>_<Stack Count>[_POR]입니다. 제품명에 밑줄(_)이 있어도 _HBM... 토큰을 기준으로 분리합니다.

- _POR로 끝나는 폴더만 POR로 표시하며, POR가 있으면 HBM/Stack 선택 콤보박스의 기본값으로 선택합니다.
- HBM 세대와 Stack 수가 다르면 별개의 해석 조건입니다. 각 폴더의 TXT, PY, INP, ODB 파일을 독립적으로 사용합니다.
- POR가 아닌 폴더도 선택·비교할 수 있습니다.
- 필수 확장자 .txt/.py/.inp/.odb 중 하나라도 없으면 해당 조건은 사용할 수 없고 관리자 안내를 표시합니다.
- 폴더명에서 추출한 HBM 세대와 .py의 HBM_Gen이 다르면 화면에 경고를 표시합니다. .py는 실행하지 않고 정적으로 분석합니다.

## 포함 기능

- SiP Product 콤보박스와 HBM/Stack 조건 콤보박스
- 선택한 조건 폴더의 TXT 결과 파싱 및 마지막 _숫자 기준 Part 그룹화
- metric 선택, X=접미 숫자/Y=metric 값 XY plot
- 여러 조건의 결과를 한 그래프에서 비교하고 CSV로 내보내기
- 그래프 아래에 비교 조건별 .py 입력 파라미터를 나란히 표시
- FastAPI를 통한 NAS/UNC 경로 연동
- Abaqus/CAE Python API로 INP를 읽고 Part별 색상으로 3D 메시 렌더링 (회전/확대/축소)
- .odb의 U3 추출 상태 표시 (실제 ODB 추출은 후속 구현)

## Abaqus 서버 설정

- Windows 서버에 Abaqus/CAE와 유효한 라이선스가 설치되어 있어야 합니다.
- `ABAQUS_COMMAND` 환경변수에 Abaqus 실행 명령 또는 `abaqus.bat`의 전체 경로를 지정할 수 있습니다. 기본값은 `abaqus`입니다.
- `SIP_ABAQUS_TIMEOUT`은 메시 변환 제한 시간(초)이며 기본값은 300입니다.
- 웹 서버 프로세스 계정이 데이터 NAS 경로와 Abaqus 실행 환경에 접근할 수 있어야 합니다.
- 첫 변환은 Abaqus 실행 시간이 필요하며, 같은 INP 파일의 결과는 파일 수정 시간/크기 기준으로 메모리 캐시됩니다.
- 웹 서버에서 외부 CDN을 차단하는 환경이라면 Three.js 스크립트를 사내 정적 파일로 제공하도록 바꿔야 합니다.

## 실행

Python 3.10+ 권장.

```powershell
cd sip_simulator/backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:SIP_DATA_ROOT="\\NAS\SiPData"
uvicorn app:app --host 0.0.0.0 --port 8000
```

## API 요약

- GET /api/products: 폴더명에서 추출한 SiP 제품/HBM/Stack/POR 조건 목록
- GET /api/products/{variant_id}/results: 해당 조건 폴더의 TXT 결과 및 PY 파라미터
- GET /api/products/{variant_id}/parameters: 해당 조건 폴더의 PY 파라미터
- GET /api/products/{variant_id}/file-status: INP/ODB 파일 상태
- GET /api/products/{variant_id}/mesh?file_name=<INP 파일명>: Abaqus/CAE Python API를 호출해 Part별 삼각형 표면 및 메시 edge를 JSON으로 생성

## 파일별 역할 / 제한

- TXT: 결과 테이블 및 XY 비교
- PY: 정적 파싱만 수행하며 임의 스크립트를 실행하지 않습니다.
- INP: `abaqus_export_mesh.py`를 Abaqus/CAE Python으로 실행해 `ModelFromInputFile` API로 읽습니다. Part별 경계면과 요소 edge를 내보내고 웹의 Three.js가 Part마다 고유 색상으로 렌더링합니다. 지원 요소 타입 외의 형상은 일부 누락될 수 있습니다.
- ODB: 현재는 파일의 존재/목록만 확인합니다. Abaqus Python/OdbAccess 기반 U3 추출은 후속 구현입니다.
- 이 버전은 Abaqus 해석을 실행하지 않습니다.

운영 환경에서는 사내 인증, 접근제어, CORS 허용 origin 제한을 설정하세요.
