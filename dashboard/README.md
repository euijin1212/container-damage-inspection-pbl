# 검수자 대시보드 (Layer 3)

관리자가 검수 결과를 조회하고 승인/수정/반려하며, Bedrock 일일 리포트를 확인하는 화면.
(구현 예정 — 담당: 정의진)

## 데이터 소스

- **검수 큐 / 상세 / 검수 처리**: `lambda/dashboard_api` (API Gateway 뒤) → DynamoDB `container-inspection`
- **일일 리포트**: `lambda/report_generator` → Bedrock 요약 결과
- **이미지**: S3 `container-damage`

## 화면 구성 (안)

1. **검수 큐**: `review_status = MANUAL_NEEDED` 목록 (위험도 높은 순)
2. **상세**: 저장 이미지 + `detections`(유형/정도/신뢰도) + `risk_score` / `risk_level`
3. **검수 처리**: 승인(approve) / 수정(modify: risk_level 변경) / 반려(reject)
4. **일일 리포트 뷰어**: 날짜 선택 → Bedrock 리포트 표시

## dashboard_api (예정)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/inspections?status=MANUAL_NEEDED&date=2026-07-13` | 검수 큐 조회 |
| GET | `/inspections/{event_id}` | 단건 상세 |
| POST | `/inspections/{event_id}/review` | 승인/수정/반려 (body: `{action, risk_level?, reviewer, memo}`) |

## 실행 (예: Streamlit)

```bash
pip install streamlit boto3
streamlit run app.py     # app.py 는 추후 구현
```

> 5일 일정에서는 React보다 Streamlit + boto3 조합이 빠르다. 인증이 필요하면 Cognito를 선택 적용.
