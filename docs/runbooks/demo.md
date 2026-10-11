# Runbook — Demo AgentQA end-to-end (P32.2)

- Ngày: 2026-10-11
- Trạng thái: Harness đã triển khai; receipts đang chạy/bổ sung
- Liên quan: [spec product](../specs/product-spec.md), [plan gói 09](../plans/09-release.md)

## 1. Phạm vi

Demo user flow hoàn chỉnh trên ứng dụng synthetic (taskboard) và tài khoản synthetic:

```text
URL/tài liệu → source/requirement → authoring proposal → source confirmation →
promote case ready → agent run (fake models) → replay → benign mutation/heal →
bug detection → evidence/report → compare
```

## 2. Tài khoản và dữ liệu synthetic

- Owner workspace: `ui-owner-*` (tạo mới mỗi lần demo, mật khẩu test cố định trong harness).
- Ứng dụng mục tiêu: taskboard fixture (`taskboard@1`) với namespace riêng mỗi run.
- Models: **fake** — authoring/policy/engine dùng fake transports (`HarnessAuthoringGo`, PlanDrivenGo/ScriptedJev).
  Không có live call nào tới Go/Zen trong demo; `live_calls=0` trong receipt.

## 3. Chạy demo

```text
uv run --locked python tools/run_demo.py --models fake
```

- `--models` chỉ nhận `fake`. Chế độ live không thuộc runbook này.
- Output: tóm tắt JSON các bước + đường dẫn report trong `artifacts/demo/`.
- Report mới nhất: `artifacts/demo/latest.json` — chứa `mode`, `live_calls`, từng step với ok/detail.

## 4. Các bước và bằng chứng

| Bước | Diễn giải | Bằng chứng |
|---|---|---|
| source.document_ingested | Upload tài liệu `demo-source.md` và trích xuất segments | `source_id`, `revision_no`, số segments trong receipt |
| authoring.proposal_generated | Authoring job từ source + requirement `create_item` bằng fake model | `job_id`, `state`, số proposals trong receipt |
| authoring.proposal_applied | Áp proposal vào draft `demo_case` qua `edit_version`/diff | `edit_version`, số dòng diff trong receipt |
| case.promoted_ready | Xác nhận nguồn (`confirm-sources`) và promote revision ready | `revision_id`, `content_digest` trong receipt |
| agent.run_passed | Submit run policy `llm` với fake agent script | `verdict=passed`, `item_count=1` trong receipt |
| replay.run_passed | Replay strict của cùng revision | `verdict`, `gate` trong receipt |
| mutation.healed | Drill fixture (`healing_delete_item`) + phục hồi với `allow_healing` | `verdict=passed`, annotation `healed` trong receipt |
| bug.detected | Ca duplicate chạy trên seed cho phép trùng → business failed | `verdict=failed`, `duplicate_count=2` trong receipt |
| evidence.report | Tạo báo cáo JSON cho run lỗi | `report_id`, `digest`, HTTP 200 content trong receipt |
| compare.config_diff | So agent run và replay run | `policy` khác nhau, cùng config còn lại trong receipt |

## 5. Ghi chú trung thực

- Mọi bước ghi `mode=fake`. Không tráo fake panels thành model thật trong UI/demo.
- `live_calls=0`: số call thật tới provider. Usage trong ledger fake tokens chỉ dùng cho accounting nội bộ, không phải chi phí thật.
- Demo không thay thế bằng chứng live của P15/P29.
