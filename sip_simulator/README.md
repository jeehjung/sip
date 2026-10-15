# SiP Simulator – 1차 구현

## 포함 기능
- SiP 폴더 바로 아래에 이름이 정확히 `POR`인 대표 결과 폴더 검증
- POR 내부의 `.txt` 결과표 파싱 및 마지막 `_숫자` 기준 Part 그룹화
- metric을 선택해 X=접미 숫자, Y=값인 XY plot 표시
- 여러 제품의 동일 그룹/metric을 한 그래프에 비교하고 CSV로 내보내기
- FastAPI NAS/UNC 경로 연동 API
- `.py` 파일을 실행하지 않고 변수 할당문을 정적으로 분석

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

NAS 구조:
```
SIP_DATA_ROOT/
  Product_A/
    POR/
      *.txt
      *.py
      *.inp
      *.odb
```

개발 시 `SIP_DATA_ROOT`를 샘플 폴더에 지정할 수 있습니다.

## 대표 결과 검증
- 각 제품 폴더 바로 아래에서 정확히 `POR`라는 이름의 폴더만 인정합니다.
- `por`, `POR_old`, `PRE_POR`는 인정하지 않습니다.
- 필수 확장자 `.txt`, `.py`, `.inp`, `.odb` 파일이 모두 하나 이상 있어야 결과를 노출합니다.
- 조건 미충족 시: `관리자 (jeeh.jung@samsung.com)에게 문의하세요.`

## 파일별 역할 / 제한
- TXT: 결과 테이블 및 XY 비교
- PY: 정적 파싱만 수행하며 임의 스크립트를 실행하지 않습니다.
- INP: 현재는 파일의 존재/목록만 확인합니다. 실제 3D mesh 변환/렌더링은 후속 구현입니다.
- ODB: 현재는 파일의 존재/목록만 확인합니다. Abaqus Python/OdbAccess 기반 U3 추출은 후속 구현입니다.
- 이 버전은 Abaqus 해석을 실행하지 않습니다.

운영 환경에서는 사내 인증, 접근제어, CORS 허용 origin 제한을 설정하세요.
