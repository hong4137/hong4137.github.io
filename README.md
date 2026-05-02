# hong4137.github.io

개인 메인 페이지 (대시보드). GitHub Pages로 자동 배포됨 — `main` 푸시 시 1분 내 반영.

## 로컬 개발 절차

```bash
# 1. 작업 시작 전 항상 pull (Actions가 sports.json을 자동 갱신함)
git pull

# 2. 수정 후 브라우저로 index.html 직접 열어 확인

# 3. 커밋 & 푸시
git add <파일>
git commit -m "<메시지>"
git push
```

## ⚠️ 자동화 주의

`.github/workflows/sports_update.yml`이 **6시간마다 `sports.json`을 자동 커밋/푸시**합니다 (KST 03/09/15/21시).

- 로컬 작업 시작 전 반드시 `git pull` — 안 그러면 푸시할 때 non-fast-forward 에러
- `sports.json`은 직접 수정하지 말 것 (Actions가 덮어씀). 데이터 로직 변경은 `scripts/update_sports.py`에서

## 구조

| 경로 | 역할 |
|---|---|
| `index.html` | 메인 대시보드 (날씨, 주식 위젯, 스포츠 카드, Quick Links) |
| `sports.json` | 스포츠 데이터 (자동 갱신, 직접 수정 금지) |
| `scripts/update_sports.py` | 스포츠 데이터 수집 스크립트 (Actions가 실행) |
| `manifest.json` / `sw.js` | PWA 설정 / Service Worker |
| `datepicker*/` `placepicker/` `mgmt-2026/` | 서브 도구 페이지 |
| `.github/workflows/` | GitHub Actions (스포츠 갱신, 모델 체크 등) |
