# Equipment Interchange Receipt (EIR) — RAG 참고 지침

이 문서는 표준 EIR 전표 양식을 기준으로 한다.
최종 PDF는 시스템에서 EIR 양식(표/체크박스/Disposition)으로 렌더링되므로,
모델은 **전표 Remarks·판정란에 들어갈 짧은 문구만** 작성하면 된다.

원본 양식(이미지 PDF):
https://static1.squarespace.com/static/61e20975f5be5d0c64faa00e/t/641d06de7cb186410ca6b5d5/1727883532868/Equipment+Interchange+Receipt+%28EIR%29.pdf

---

## EIR 전표에 채워지는 칸

| 전표 항목 | 채움 방식 |
|---|---|
| Equipment No. | container_id |
| Reference No. | event_id |
| Date/Time In | captured_at |
| Equipment Condition | detections 있으면 DAMAGE, 없으면 NO DAMAGE |
| Damage Types | hole / dent / rust (실제 탐지분만) |
| Damage Description 표 | type, severity, location, description |
| Remarks | summary + assessment + action (짧게) |
| Disposition | USABLE / REPAIR_NEEDED / REJECT |

essay형 보고서(서론·본론·결론)를 쓰지 말 것. **전표 메모 스타일**만.

---

## 손상 유형

- hole: 구멍/관통
- dent: 찌그러짐/변형
- rust: 녹/부식

confidence는 전표에 쓰지 않는다.

---

## Disposition 기준

- USABLE: 무손상 또는 low 위주
- REPAIR_NEEDED: medium 중심, 수리 후 사용
- REJECT: hole high 또는 구조적 손상으로 사용 불가

---

## Remarks 문체

- 한국어, 1~3문장, 사실만
- 예: "하단부 rust(medium) 2건 확인. 구조 관통 없음. 모니터링 후 인수 가능."
