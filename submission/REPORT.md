# Báo cáo cá nhân — K4-L3B Day 13 Monitoring & LLMOps

> Mỗi học viên hoàn thiện một file duy nhất này. Khi dẫn evidence, dùng đường dẫn tương đối, ví dụ `evidence/07-trace-waterfall.png`.

## 1. Thông tin học viên

- **Họ và tên:** Dinh Lenh Tien Anh
- **MSSV:** 2A202602928
- **Lớp:** K4-L3B
- **Repository URL:** https://github.com/AIVIETNAM-AIO-AnhDinh/K4-L3B-Day13-DinhLenhTienAnh-2A202602928-Monitoring-LLMOps
- **Commit SHA cuối:** commit cuối trên nhánh `main` (`git log -1`), đã nộp kèm URL trên LMS/Codelabs
- **Challenge ID:** `day13-k4-l3b-monitoring-llmops-v1` (cohort K4)
- **Tên project Langfuse cá nhân:** `K4-L3-DAY13-DinhLenhTienAnh-2A202602928-Monitoring-LLMOps` (project id `cmunh5vij0fhoad0cuivi8yo8`, project riêng của tôi, không dùng chung)

## 2. Evidence index

Điền đúng đường dẫn tới evidence thực tế. Có thể đổi tên hoặc dùng nhiều ảnh nếu cần.

| Evidence | Đường dẫn |
|---|---|
| Baseline (CP0) | [`evidence/00-baseline-validators.txt`](evidence/00-baseline-validators.txt) |
| Pytest cuối | [`evidence/01-pytest.txt`](evidence/01-pytest.txt) |
| Log validator | [`evidence/02-log-validator.txt`](evidence/02-log-validator.txt) |
| Dashboard validator | [`evidence/03-dashboard-validator.txt`](evidence/03-dashboard-validator.txt) |
| Structured log | [`evidence/04-structured-log.txt`](evidence/04-structured-log.txt) |
| PII redaction | [`evidence/05-pii-redaction.txt`](evidence/05-pii-redaction.txt) |
| Trace list | [`evidence/06-trace-list.png`](evidence/06-trace-list.png) · [`evidence/06-trace-list.txt`](evidence/06-trace-list.txt) |
| Trace waterfall | [`evidence/07-trace-waterfall.png`](evidence/07-trace-waterfall.png) · [`evidence/07-trace-waterfall.txt`](evidence/07-trace-waterfall.txt) |
| Trace metadata | [`evidence/08-trace-metadata.png`](evidence/08-trace-metadata.png) · [`evidence/08-trace-metadata.txt`](evidence/08-trace-metadata.txt) |
| Prompt versions | [`evidence/09-prompt-versions.png`](evidence/09-prompt-versions.png) · [`evidence/09-prompt-versions.txt`](evidence/09-prompt-versions.txt) |
| Prompt rollback | [`evidence/10-prompt-rollback.png`](evidence/10-prompt-rollback.png) · [`evidence/10-prompt-rollback.txt`](evidence/10-prompt-rollback.txt) |
| Dashboard runtime | [`evidence/11-dashboard-overview.png`](evidence/11-dashboard-overview.png) · [`evidence/11-dashboard-overview-2.png`](evidence/11-dashboard-overview-2.png) · [`evidence/11-dashboard-overview-3.png`](evidence/11-dashboard-overview-3.png) |
| Incident metric | [`evidence/12-incident-metric.png`](evidence/12-incident-metric.png) · [`evidence/12-incident-metric.txt`](evidence/12-incident-metric.txt) |
| Incident log | [`evidence/13-incident-log.png`](evidence/13-incident-log.png) · [`evidence/13-incident-log.txt`](evidence/13-incident-log.txt) |
| Incident trace | [`evidence/14-incident-trace.png`](evidence/14-incident-trace.png) · [`evidence/14-incident-trace.txt`](evidence/14-incident-trace.txt) |

> Ảnh Langfuse đã che public key (`scope.attributes.public_key`) và email tài khoản. Ba ảnh `11-dashboard-overview*.png` là dashboard **Langfuse Home** của project cá nhân (time range Past 1 day), chụp theo thứ tự từ trên xuống.

## 3. Kết quả kỹ thuật

| Nội dung | Baseline | Kết quả cuối | Nhận xét |
|---|---|---|---|
| `validate_logs.py` | 30/100 — 20/21 record thiếu `correlation_id`/enrichment, 0 correlation ID | 100/100 — 147 record, 67 correlation ID, 0 leak (cuối, gồm CP1–CP3) | Log cũ đã đổi tên thành `data/logs.baseline.jsonl` trước khi đo lại |
| `validate_dashboard.py` | HỢP LỆ 6/6 | HỢP LỆ 6/6 | Validator chỉ kiểm tra contract `config/dashboard.yaml`; dashboard runtime là Langfuse Home (xem mục 6) |
| `pytest` | 22 passed | 49 passed (cuối) | CP1: test PII, middleware, enrichment, scrub. CP2: test child observation, không lọt PII vào trace, span lỗi |
| Số traces hợp lệ | 0 (trace chỉ có root `lab-agent-run`, prompt `local-fallback` vì chưa có prompt trên Langfuse) | 18 trace `dev` đủ root + `retrieval` + `llm-generation`, gắn prompt v1/v2; thêm 40 trace `practice` | Danh sách: [06-trace-list.txt](evidence/06-trace-list.txt) |
| Số PII leak | 0 | 0 | Baseline 0 chỉ vì `summarize_text` scrub `message_preview`; processor chưa được đăng ký nên `session_id`, lỗi, exception không được bảo vệ |
| Latency P95 / TTFT P95 | CP1: P95 ≈ 430ms/request warm | Warm ≈ 161ms; P95 cửa sổ 60 phút 1,375ms / TTFT P95 55ms | P95 cửa sổ bị kéo lên bởi request đầu tiên của mỗi process (fetch prompt 1.3–1.9s). Warm giảm từ ~430ms xuống ~161ms sau khi tạo prompt, vì trước đó mỗi request đều gọi Langfuse và nhận 404 (không được cache) |
| Retrieval success rate | 100% | 100% (`dev`); practice `tool_fail` 0% | Panel Errors hiển thị cả error rate và retrieval success |

## 4. Logging và PII

- **Cách tạo/nhận và truyền correlation ID:** `CorrelationIdMiddleware` (`app/middleware.py`) gọi `clear_contextvars()` đầu mỗi request để không dính context của request trước. Nếu client gửi `x-request-id` hợp lệ (chỉ gồm `[A-Za-z0-9._-]`, tối đa 64 ký tự) thì dùng lại; nếu không thì sinh `req-<8-hex>` từ `uuid4`. Giá trị hợp lệ mới được dùng để tránh client chèn PII/xuống dòng vào log qua header. ID được `bind_contextvars` nên mọi log trong request tự có `correlation_id`, được gán vào `request.state` để truyền sang `agent.run` (trace metadata), và trả về trong header `x-request-id` cùng `x-response-time-ms` và trong body `correlation_id`.
- **Các metadata được ghi vào structured log:** mỗi log `service=api` có `ts`, `level`, `event`, `correlation_id`, `user_id_hash` (SHA-256 12 ký tự, không log `user_id` gốc), `session_id`, `feature`, `model`, `env`; `response_sent` thêm `latency_ms`, `ttft_ms`, `tokens_in`, `tokens_out`, `cost_usd`, `quality_score`, `tool_name`, `tool_success`. Context được bind trong `app/main.py` trước log `request_received`.
- **Cách bảo đảm PII được scrub trước khi ghi:** `scrub_event` được đăng ký trong chuỗi processor của structlog, sau `format_exc_info` (để scrub cả traceback) và trước `JsonlFileProcessor`/`JSONRenderer`, nên không có dữ liệu nào được serialize hay ghi file trước khi scrub. `scrub_event` duyệt đệ quy mọi chuỗi trong event (không chỉ `payload`), vì `session_id`/`feature` cũng do client gửi lên. `app/pii.py` có pattern cho email, thẻ thanh toán 13–19 số, CCCD 12 số, điện thoại VN (`0`/`+84`/`84`, có dấu cách/chấm/gạch) và hộ chiếu VN. Thứ tự pattern có chủ đích: email trước để số trong địa chỉ email không bị phone_vn redact dở; chuỗi số dài (thẻ > CCCD > điện thoại) trước chuỗi ngắn.
- **Cách kiểm chứng kết quả:** `tests/test_pii.py` (từng loại PII, nhiều định dạng, thứ tự pattern, và chuỗi không phải PII như `req-…`, timestamp, số latency không bị redact) và `tests/test_correlation_logging.py` (ID sinh mới/dùng lại/từ chối ID không an toàn, mỗi request một ID, log được enrich, PII không xuống tới file). Chạy thực tế: `load_test.py` tuần tự và `--concurrency 5`; mỗi trong 20 correlation ID có đúng 2 dòng log với cùng `session_id`/`user_id_hash`, tức context không bị lẫn giữa các request đồng thời. `validate_logs.py` đạt 100/100 ([evidence/02-log-validator.txt](evidence/02-log-validator.txt)); ví dụ log và redaction ở [evidence/04-structured-log.txt](evidence/04-structured-log.txt), [evidence/05-pii-redaction.txt](evidence/05-pii-redaction.txt).

## 5. Tracing và prompt versioning

- **Cách xác nhận traces do chính tôi tạo trong project cá nhân:** app dùng key trong `.env` của project cá nhân (project id `cmunh5vij0fhoad0cuivi8yo8`). Tôi đọc lại trace bằng `GET /api/public/v2/observations` với cùng key và đối chiếu từng `correlation_id` trong metadata với `data/logs.jsonl` ([06-trace-list.txt](evidence/06-trace-list.txt)). Trace chạy practice có `environment=practice`, tách khỏi `dev`.
- **Cấu trúc root/retrieval/generation observations:** trace `day13-agent-request` → root `lab-agent-run` (agent, `@observe`) → hai child tạo bằng `start_as_current_observation` của SDK v4:
  - `retrieval` (retriever): input là `query_preview` đã scrub, output là `doc_count` và preview tài liệu. Nếu lỗi thì span có `level=ERROR` và `status_message`, ví dụ `RuntimeError: Vector store timeout`.
  - `llm-generation` (generation): có `model`, prompt được link (`day13-chat` vN), `usage_details` input/output/total, `cost_details` input/output/total, `completion_start_time` (Langfuse tính TTFT từ đây) và input/output là preview đã scrub.

  Không gửi prompt/câu trả lời thô vì có thể chứa PII; có test chặn điều này. Waterfall: [07-trace-waterfall.txt](evidence/07-trace-waterfall.txt); metadata: [08-trace-metadata.txt](evidence/08-trace-metadata.txt).
- **Cách nối trace với log:** middleware sinh `correlation_id` và truyền vào `agent.run`. `propagate_attributes(metadata={"correlation_id": ...})` ghi ID này lên mọi observation của trace. Cùng ID có trên mọi dòng log của request và trong header `x-request-id`. Dòng `response_sent` còn ghi `prompt_name/prompt_label/prompt_version`, nên từ log cũng biết request đã dùng prompt nào.
- **Prompt name:** `day13-chat` (text prompt, giữ ba biến `{{feature}}`, `{{docs}}`, `{{message}}`)
- **Version/label baseline:** v1, labels `baseline` + `production`, là template contract của đề ([09-prompt-versions.txt](evidence/09-prompt-versions.txt))
- **Version/label candidate:** v2, label `candidate`, thêm một dòng yêu cầu trả lời tối đa 3 gạch đầu dòng và trích tài liệu. Cùng input, `tokens_in` tăng từ 32 lên 49.
- **Trace ID của mỗi version:** cùng input `"Explain why metrics traces and logs work together"`:
  - v1/`baseline`: `30555bb0980526dde5a39429065205fe` (`req-fbcf1201`)
  - v2/`candidate`: `c38c889da262a2a8c065ed9415879e87` (`req-cf3b2011`)
  - v2 qua `production` sau promote: `ff77b7f57bd56db87a89bef60c7d9c30` (`req-adae3bbb`)
  - v1 qua `production` sau rollback: `ba4e8833c9bd9b98b59615c6c8bac247` (`req-edfe7dbb`)
- **Cách promote và rollback `production`:** code chỉ hỏi Langfuse theo `LANGFUSE_PROMPT_LABEL=production`, nên đổi version không cần sửa code. Promote là chuyển label `production` sang v2 (`update_prompt(name="day13-chat", version=2, new_labels=["candidate","production"])`, tương đương thao tác trên UI). Rollback là chuyển `production` về v1. App đang chạy (không restart) nhận version mới sau một chu kỳ cache 60s: request đầu tiên sau khi hết hạn cache vẫn dùng bản cũ (stale-while-revalidate), request kế tiếp dùng bản mới. Timeline kèm trace ID ở [10-prompt-rollback.txt](evidence/10-prompt-rollback.txt). Hệ quả vận hành: rollback không có hiệu lực tức thì, cần tính ~60s vào thời gian mitigation.

## 6. Dashboard, SLO và alerts

- **Dashboard và sáu panel:** dashboard runtime là **Langfuse Home** của project cá nhân (time range Past 1 day, env `dev` + `practice`), dữ liệu từ các trace của lab ([11](evidence/11-dashboard-overview.png), [11-2](evidence/11-dashboard-overview-2.png), [11-3](evidence/11-dashboard-overview-3.png)). Đối chiếu với sáu panel trong `config/dashboard.yaml`:
  - **Latency:** widget *Trace latency percentiles* cho `day13-agent-request` p50 0.16s, p90 2.66s, p95 2.67s, p99 2.67s. *Observation latency percentiles* tách theo bước: `retrieval` p95 2.51s, `llm-generation` p95 0.16s. TTFT không có widget riêng; xem cột *Time To First Token* của từng generation trong Tracing (~0.05–0.06s).
  - **Traffic:** *Traces* 115 trace `day13-agent-request`, *Observations by time* 271 observation.
  - **Errors:** *Observations by Level*: ERROR 20, DEFAULT 251. 20 ERROR là 10 request practice `tool_fail` (root + `retrieval` mỗi request). Retrieval success không có widget riêng; từ observation `retriever` là 73/83 ≈ 88%, nếu chỉ tính `dev` là 100%.
  - **Cost:** *Model costs* $0.21 (`claude-sonnet-4-5`, 16.16K token); *User consumption* chia theo `user_id_hash`.
  - **Tokens:** *Model Usage* → tab *Usage by type* (input/output).
  - **Quality:** `quality_score` hiện chỉ có trong log `response_sent`, chưa gửi lên Langfuse làm score, nên widget *Scores* báo "No data".
  - Các con số theo đúng contract (P50/P95/P99, TTFT P95, error rate, retrieval success, cost, tokens in/out, quality) được tính lại từ `data/logs.jsonl` cho từng pha sự cố ở [12-incident-metric.txt](evidence/12-incident-metric.txt). Endpoint `/metrics` của API trả P50/P95/P99, TTFT P95, cost, token, error breakdown và quality trung bình.
  - Practice incident chạy trên server riêng (log riêng, `APP_ENV=practice`): `tool_fail` cho error 25% và retrieval 75% trên cả phiên practice; `rag_slow` đẩy P95 lên 2,666ms; `cost_spike` đẩy chi phí từ ~0.0018 lên ~0.0078 USD/request. Trên Langfuse Home thấy tương ứng ERROR (Sum: 20) và `retrieval` p95 2.51s.
- **SLO và lý do chọn:** giữ SLO của đề (`config/slo.yaml`): 99.5% request trong 28 ngày phải có `response_sent` với `latency_ms <= 3000`. Mỗi `request_failed` tự động là bad event.
  - Giữ 3000ms vì khớp threshold panel Latency; baseline warm ~161ms và cold start 1.3–1.9s đều dưới ngưỡng, nên cold start không bị tính là lỗi.
  - Hạn chế đã thấy: `latency_ms` đo bên trong `agent.run`, không gồm thời gian request phải chờ khi event loop bị chặn. Client đo ~2.2s ở concurrency 5 trong khi server ghi ~160ms, nên SLI này đánh giá thấp latency người dùng thực sự thấy.
- **Cách tính error budget:** budget = 100% − 99.5% = 0.5% số request trong 28 ngày. Ví dụ 1,000 req/ngày × 28 = 28,000 request thì được phép tối đa 140 request lỗi hoặc > 3000ms. Burn rate = tỷ lệ bad ÷ 0.5%: error rate 1% kéo dài là burn rate 2, hết budget trong 14 ngày. Trong lần practice `tool_fail`, 10/40 request fail (25%), tức burn rate 50: với traffic đó budget 28 ngày chỉ đủ cho khoảng 13 giờ, vì vậy alert lỗi là `critical` với duration ngắn.
- **Ba alert và runbook tương ứng:** định nghĩa ở `config/alert_rules.yaml`, runbook ở `docs/alerts.md`. Cả ba gửi Slack `#k4-l3b-alerts`, owner `student-2A202602928`.
  - `HighLatencyP95` (warning, 5m): P95 > 2000ms. Ngưỡng đặt dưới đường SLO vì practice `rag_slow` làm request chậm 16 lần (P95 ~2667ms) mà vẫn dưới 3000ms; alert ở 3000ms sẽ bỏ lỡ sự cố này.
  - `HighErrorRateOrRetrievalFailing` (critical, 3m): error rate > 2% hoặc retrieval success < 90%.
  - `CostPerRequestSpike` (warning, 15m): chi phí trung bình mỗi request > 0.004 USD (~2 lần baseline). Dùng chi phí mỗi request thay vì tổng để alert không bắn chỉ vì traffic tăng.

  Mỗi runbook đi theo thứ tự dashboard → lọc log lấy `correlation_id` → mở trace cùng ID, so `retrieval` với `llm-generation` → mitigation.

> Ví dụ cách viết error budget: "SLO 99.5% trong 28 ngày nghĩa là error budget 0.5%. Nếu workload có 10,000 request thì tối đa 50 request được phép lỗi hoặc chậm hơn ngưỡng SLO."

## 7. Điều tra challenge

- **Challenge ID:** `day13-k4-l3b-monitoring-llmops-v1` (cohort K4, seed 1312, 5 query `monitoring`, `latency_threshold_ms` 2000)
- **Khoảng thời gian điều tra:** 2026-09-30, 10:36–10:39 giờ VN (03:36–03:39 UTC). Cùng 5 query challenge được chạy ba lần với `--concurrency 5`:
  - healthy: 10:36:56, trước khi inject, để có mốc so sánh cùng input;
  - sự cố: 10:37:17 → 10:37:31, sau `inject_incident.py`;
  - sau fix: 10:38:51.
- **Triệu chứng từ metrics:** latency P95 tăng từ **162ms lên 2,672ms** (16.5 lần), P50 từ 161ms lên 2,666ms. Mức này vượt `latency_threshold_ms` 2000 của challenge và ngưỡng alert `HighLatencyP95`, nhưng vẫn dưới đường 3000ms của dashboard.
  - Không đổi: TTFT P95 giữ 55ms, error rate 0%, retrieval success 100%, cost/token nằm trong dao động ngẫu nhiên của fake LLM, quality 0.84.
  - Suy ra: thời gian tăng thêm nằm **trước** lúc LLM sinh token đầu tiên. Bảng so sánh ở [12-incident-metric.txt](evidence/12-incident-metric.txt); ảnh [12-incident-metric.png](evidence/12-incident-metric.png) là snapshot dashboard cục bộ chụp ngay lúc điều tra (spike ở phút 10:37, hồi phục ở 10:38). Script dashboard này sau đó đã được gỡ khỏi repo; bảng số trong file `.txt` tính lại được trực tiếp từ `data/logs.jsonl`.
- **Log line và correlation ID liên quan:** cả 5 dòng `response_sent` trong cửa sổ sự cố đều có `latency_ms` khoảng 2,662–2,672 nhưng HTTP 200, `tool_success=true`, `ttft_ms` 50–55 và vẫn `prompt_version=1` như trước sự cố. Như vậy không phải lỗi và không phải do đổi prompt. Request chậm nhất: `req-54ab57b0` (`latency_ms=2672`, `ttft_ms=55`, 03:37:25.855Z) ([13-incident-log.txt](evidence/13-incident-log.txt)).
- **Trace ID và span gây ảnh hưởng:** trace `fff9da7d4a21f23e69b45c1aa403a280` (metadata `correlation_id=req-54ab57b0`).
  - Span **`retrieval` (retriever) kéo dài 2,512ms, chiếm 94% của 2,673ms**. `llm-generation` chỉ bắt đầu sau khi retrieval xong và vẫn 161ms, TTFT 0.056s.
  - So sánh cùng query khi healthy (`req-54c4a3a5`, trace `c0bbed79385b60aa8677e121caa05e2a`): retrieval 0ms, generation 161ms ([14-incident-trace.txt](evidence/14-incident-trace.txt)).
- **Root cause:** bước retrieval (vector store / RAG) chậm thêm khoảng 2.5s mỗi request, trong khi LLM, prompt và tỷ lệ lỗi không đổi.
  - Metric (P95 tăng, TTFT không đổi), log (không lỗi, cùng prompt v1) và trace (span `retrieval` chiếm 94%) cùng chỉ về một chỗ.
  - Log control-plane `incident_enabled` lúc 03:37:17Z trùng thời điểm bắt đầu, và scenario trong file challenge đúng là retrieval chậm (`rag_slow`). Tôi chỉ đối chiếu file sau khi đã kết luận từ evidence.
- **Fix action:** tắt nguồn gây chậm bằng `python scripts/inject_incident.py --disable` lúc 03:38:51Z. Trong hệ thống thật, bước tương ứng là khôi phục hoặc chuyển sang vector store dự phòng, hoặc bật context fallback.
  - Đã kiểm chứng bằng cách chạy lại đúng 5 query: P95 về 161ms, span `retrieval` về 0ms (trace `857c270f5354285150f8e546f6486915`, `req-308bcb4e`).
- **Preventive measure:**
  - Giữ alert `HighLatencyP95` ở 2000ms. Sự cố này nằm dưới đường 3000ms của dashboard, nên alert đặt theo đường đó sẽ không bắn.
  - Thêm alert riêng cho độ trễ span `retrieval` (ví dụ p95 > 500ms trong 5 phút), vì retrieval bình thường gần 0ms.
  - Đặt timeout cho retrieval (ví dụ 800ms) kèm fallback context để một vector store chậm không làm chậm toàn bộ request.
  - Chạy async hoặc tách retrieval khỏi event loop. Hiện `/chat` gọi hàm blocking nên ở concurrency 5 các request xếp hàng: client thấy 10.7–13.4s trong khi server ghi ~2.67s. Cũng nên đo thêm SLI latency phía client/middleware.
  - Thêm bước vào runbook: so sánh TTFT với P95 để biết ngay chậm nằm trước hay trong LLM.

> Gợi ý cách viết ngắn, không thay cho evidence thực tế: "Metric cho thấy `[latency/error/cost/quality]` bất thường trong `[khoảng thời gian]`. Log line `[event]` có `correlation_id=[...]` đại diện cho request bị ảnh hưởng. Trace cùng `correlation_id` cho thấy span `[retrieval/generation/prompt/tool]` có dấu hiệu `[chậm/lỗi/token tăng]`. Root cause là `[nguyên nhân suy ra từ evidence]`. Fix action là `[hành động khôi phục]`; preventive measure là `[alert/runbook/test/guardrail để ngăn tái diễn]`."

## 8. Giải thích và tự đánh giá

- **Một quyết định kỹ thuật quan trọng và lý do:** đặt alert `HighLatencyP95` ở **2000ms**, không phải 3000ms như đường SLO/dashboard.
  - Khi chạy practice `rag_slow`, P95 tăng từ ~160ms lên ~2667ms (chậm 16 lần) nhưng vẫn dưới 3000ms, nên alert copy từ dashboard sẽ không bao giờ bắn.
  - Challenge CP3 đúng là trường hợp này (P95 2,672ms), và ngưỡng 2000ms bắt được nó.
  - Quyết định thứ hai: `scrub_event` scrub **mọi** chuỗi trong log (đệ quy), không chỉ `payload`, vì `session_id`/`feature` cũng do client gửi và có thể chứa PII.
- **Một lỗi/blocker đã gặp:** trước khi tạo prompt `day13-chat` trên Langfuse, mọi trace đều có `prompt_source=local-fallback` và latency warm khoảng 430ms/request, trong khi phần xử lý thật chỉ ~160ms.
- **Cách tìm nguyên nhân và xử lý:**
  - Metadata `prompt_fetch_error` cùng `prompt_source=local-fallback` trên trace cho thấy fetch prompt thất bại.
  - `prompts.list(name="day13-chat")` trả về rỗng, tức prompt chưa tồn tại. SDK gọi Langfuse mỗi request, nhận 404 và không cache lỗi, nên tốn ~270ms mỗi lần.
  - Sau khi tạo v1/v2, latency warm về ~161ms.
  - Blocker phụ: API `GET /api/public/traces` trả 410 (bị tắt với org mới), nên tôi chuyển sang `GET /api/public/v2/observations` để đọc trace.
- **Cách hiểu luồng Metrics → Logs → Traces:** metrics cho biết **cái gì** xấu và **khi nào**; logs cho biết **request nào** bị ảnh hưởng; trace cho biết **bước nào** gây ra. Ở CP3:
  - Metrics: P95 tăng 16 lần trong khi TTFT, error, cost giữ nguyên, nên vấn đề nằm trước LLM.
  - Logs: loại trừ lỗi và việc đổi prompt, và chọn được `req-54ab57b0`.
  - Trace cùng `correlation_id`: span `retrieval` chiếm 94% thời gian.

  Mỗi lớp thu hẹp phạm vi cho lớp sau; mở trace ngẫu nhiên thì không biết request đó có đại diện cho sự cố hay không.
- **Vai trò của prompt version, token/cost, SLO hoặc rollback trong vận hành LLM:**
  - Prompt là một phần của "code" chạy production. Version và label cho biết mỗi request dùng prompt nào: v2 dài hơn một dòng làm `tokens_in` tăng 32→49, tức cost tăng theo đúng tỷ lệ.
  - Rollback bằng cách chuyển label, không cần deploy, nhưng có độ trễ đến một chu kỳ cache (60s) và phải tính thời gian đó vào mitigation.
  - SLO/error budget biến "hệ thống có ổn không" thành một con số, và cho biết sự cố nào cần xử lý ngay: ví dụ burn rate 50 khi 25% request lỗi.
- **Điều quan trọng nhất đã học:** chỉ kết luận khi metric, log và trace cùng chỉ về một chỗ. Ngưỡng alert phải được kiểm chứng bằng sự cố thử nghiệm thật, không chỉ lấy từ con số trên dashboard.
- **Hạn chế hoặc phần chưa hoàn thành, nếu có:**
  - `latency_ms` chỉ đo bên trong `agent.run`. `/chat` là `async def` nhưng gọi hàm blocking, nên ở concurrency 5 request phải xếp hàng: client thấy 10.7–13.4s trong khi log ghi ~2.67s. SLI hiện tại vì vậy đánh giá thấp latency người dùng thấy.
  - Quality proxy chỉ là heuristic.
  - Dashboard runtime dùng Langfuse Home mặc định nên chưa khớp hoàn toàn contract `config/dashboard.yaml`: time range 1 ngày thay vì 60 phút, không có đường threshold, thiếu widget riêng cho TTFT P95, retrieval success và quality.
  - Alert mới là định nghĩa YAML, chưa nối Slack thật.
  - Tên project Langfuse chưa theo đúng mẫu `day13-k4-l3b-<MSSV>` của đề.

## 9. Checklist trước khi nộp

- [x] Kết quả và evidence thuộc commit SHA cuối.
- [x] Tất cả ảnh/output mở được bằng đường dẫn tương đối.
- [x] Incident evidence nối đúng metric → log → trace.
- [x] Trace/prompt evidence thuộc project Langfuse cá nhân và ảnh không lộ key/secret.
- [x] Repository chạy lại được theo README.
- [x] Không có secret, API key, PII thô hoặc evidence của người khác/lớp khác.
- [ ] URL repo và commit SHA cuối đã được nộp trên LMS/Codelabs.
