# Maigym

maishift 공개 프로필 기록을 파싱해서 maimai DX 고레벨 채보를 추천하는 로컬 웹 앱입니다.

## 구성

- `back/`: FastAPI 백엔드입니다. maishift 프로필 파싱, 캐시, 추천 API를 담당합니다.
- `front/`: Streamlit 프론트엔드입니다. 추천 조건 입력, 결과 카드, PNG 이미지 저장을 담당합니다.
- `tools/`: 곡 DB와 cohort 통계를 갱신하거나 maishift 데이터를 점검하는 유지보수 스크립트입니다.
- `back/data/`: 앱 실행에 필요한 CSV/JSON 데이터입니다.

## 로컬 실행

백엔드:

```powershell
cd C:\maimai-recommender\back
.\venv\Scripts\python.exe -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

프론트엔드:

```powershell
cd C:\maimai-recommender\front
python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

브라우저에서 `http://127.0.0.1:8501`을 열고 maishift 프로필 URL을 입력합니다.

## 주요 API

- `GET /health`: 백엔드와 차트 DB 상태 확인
- `POST /recommend-by-url`: maishift 프로필 URL 기반 추천 생성
- `POST /recommend`: 내부 테스트용 추천 생성

## 데이터 갱신

필요할 때 `tools/update_database.py`를 실행해 프로필 URL 수집, Best 50 기록 수집, cohort 통계 생성을 순서대로 수행할 수 있습니다.

```powershell
python tools\update_database.py
```

생성되는 디버그 로그와 임시 산출물은 `.gitignore`에 포함되어 있습니다.
