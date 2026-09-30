# Template Alert và Runbook

Mỗi alert phải dựa trên triệu chứng người dùng hoặc SLO, không dựa trực tiếp vào tên implementation nội bộ.

## Alert mẫu để tham khảo

Ví dụ dưới đây minh họa mức độ cụ thể cần có. Học viên không cần copy nguyên, nhưng ba alert trong bài nộp nên rõ ràng tương tự: điều kiện là gì, kéo dài bao lâu, ảnh hưởng tới user ra sao và người trực cần kiểm tra gì trước.

- Tên: `HighLatencyP95`
- Severity: `warning`
- Duration: `5m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: latency P95 của `response_sent.latency_ms`
- Điều kiện và thời gian duy trì: `p95(latency_ms) > 3000ms` trong 5 phút
- Ảnh hưởng tới người dùng: người dùng phải chờ lâu hơn trước khi nhận câu trả lời
- Ba bước kiểm tra đầu tiên:
  1. Mở dashboard latency để xác nhận P95/P99 và khoảng thời gian tăng.
  2. Lọc `data/logs.jsonl` trong khoảng đó, lấy một `correlation_id` có `latency_ms` cao.
  3. Mở trace cùng `correlation_id` trên Langfuse, so sánh các span chính để xác định bước nào bất thường.
- Mitigation tạm thời: dựa trên evidence thực tế để rollback prompt, khôi phục cấu hình liên quan, tắt practice scenario hoặc giảm tải khi demo.
- Owner: `student-<MSSV>`

## Lọc log nhanh (dùng chung cho cả ba runbook)

```bash
# Request chậm nhất trong log (ts, correlation_id, latency, prompt version)
python -c "import json; rs=[json.loads(l) for l in open('data/logs.jsonl')]; [print(r['ts'], r['correlation_id'], r['latency_ms'], 'prompt v'+str(r.get('prompt_version'))) for r in sorted((r for r in rs if r.get('event')=='response_sent'), key=lambda r: -r['latency_ms'])[:5]]"
# Request lỗi và loại lỗi
grep '"request_failed"' data/logs.jsonl | tail -5
# Mọi dòng log của một request
grep '"req-xxxxxxxx"' data/logs.jsonl
```

Trên Langfuse: Tracing → lọc metadata `correlation_id = req-xxxxxxxx` → mở waterfall `lab-agent-run` và so sánh hai child `retrieval` (retriever) và `llm-generation` (generation).

## Alert 1

- Tên: `HighLatencyP95`
- Severity: `warning`
- Duration: `5m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: SLO `fast_successful_requests` (99.5% request có `response_sent` và `latency_ms <= 3000` trong 28 ngày); panel Latency.
- Điều kiện và thời gian duy trì: `p95(response_sent.latency_ms)` trên cửa sổ 5 phút `> 2000ms`, kéo dài liên tục 5 phút. Ngưỡng 2000ms thấp hơn đường SLO 3000ms có chủ đích: practice `rag_slow` đẩy P95 từ ~160ms lên ~2667ms (chậm 16 lần) nhưng vẫn dưới 3000ms, nên alert đặt ở 3000ms sẽ im lặng.
- Ảnh hưởng tới người dùng: phải chờ lâu hơn nhiều trước khi nhận câu trả lời; nếu tiếp tục tăng qua 3000ms thì bắt đầu đốt error budget.
- Ba bước kiểm tra đầu tiên:
  1. Dashboard panel Latency: xác nhận P95/P99 tăng từ phút nào; so TTFT P95 — TTFT bình thường (~55ms) mà P95 tăng nghĩa là chậm nằm **trước** LLM (retrieval/prompt), TTFT tăng nghĩa là chậm ở LLM.
  2. Lọc log `response_sent` trong khoảng đó, lấy `correlation_id` có `latency_ms` cao nhất; kiểm tra `prompt_version` có đổi đúng lúc latency tăng không.
  3. Mở trace cùng `correlation_id`, so thời lượng span `retrieval` với `llm-generation` để khoanh bước chậm.
- Mitigation tạm thời: span `retrieval` chậm → giảm tải/khởi động lại vector store, bật timeout + fallback context; span `llm-generation` chậm hoặc prompt mới làm tăng token → rollback label `production` về version trước trên Langfuse (có hiệu lực sau ≤ 60s cache TTL); trong lab: tắt practice scenario bằng `python scripts/inject_incident.py --scenario <tên> --disable`.
- Owner: `student-2A202602928`

## Alert 2

- Tên: `HighErrorRateOrRetrievalFailing`
- Severity: `critical`
- Duration: `3m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: SLO `fast_successful_requests` (mỗi `request_failed` là một bad event); guardrails `error_rate_pct_max: 2`, `retrieval_success_rate_pct_min: 90`; panel Errors.
- Điều kiện và thời gian duy trì: `error_rate_pct > 2` **hoặc** `tool_success_rate_pct < 90` trên cửa sổ 5 phút, kéo dài 3 phút. Duration ngắn hơn alert 1 vì lỗi làm người dùng không nhận được câu trả lời và đốt budget rất nhanh (practice `tool_fail`: 100% request trả 500).
- Ảnh hưởng tới người dùng: request trả HTTP 500, không có câu trả lời; với SLO 99.5%, 1% lỗi kéo dài sẽ tiêu hết budget 28 ngày trong khoảng 14 ngày.
- Ba bước kiểm tra đầu tiên:
  1. Dashboard panel Errors: xem error rate, dòng "Errors by type" và retrieval success bắt đầu giảm từ phút nào.
  2. `grep '"request_failed"' data/logs.jsonl`: xem `error_type`, `tool_name`, `payload.detail` và lấy một `correlation_id`.
  3. Mở trace cùng `correlation_id`: observation nào có level `ERROR` và `status_message` gì (ví dụ `retrieval` báo `RuntimeError: Vector store timeout`).
- Mitigation tạm thời: lỗi ở `retrieval` → chuyển sang context fallback/degraded mode hoặc khôi phục vector store; lỗi ở `llm-generation` → rollback prompt/model vừa đổi; lỗi sau deploy → rollback bản deploy. Trong lab: tắt practice scenario.
- Owner: `student-2A202602928`

## Alert 3

- Tên: `CostPerRequestSpike`
- Severity: `warning`
- Duration: `15m`
- Kênh thông báo: Slack `#k4-l3b-alerts`
- SLI/SLO liên quan: guardrail `daily_cost_usd_max: 2.5`; panel Cost và Tokens.
- Điều kiện và thời gian duy trì: `avg(response_sent.cost_usd)` trên cửa sổ 15 phút `> 0.004 USD/request`, kéo dài 15 phút. Baseline ~0.0018–0.0022 USD/request, nên 0.004 ≈ 2x baseline; practice `cost_spike` cho ~0.0078 USD/request. Dùng chi phí **mỗi request** thay vì tổng để alert không bắn chỉ vì traffic tăng.
- Ảnh hưởng tới người dùng: không thấy lỗi ngay, nhưng câu trả lời dài bất thường (output token tăng) và chi phí vượt ngân sách ngày nếu kéo dài.
- Ba bước kiểm tra đầu tiên:
  1. Dashboard panel Cost và Tokens: chi phí tăng do `tokens_in` (prompt/context dài hơn) hay `tokens_out` (câu trả lời dài hơn)?
  2. Lọc log `response_sent` có `cost_usd` cao, lấy `correlation_id`, kiểm tra `prompt_version` và `feature` của các request đó.
  3. Mở trace cùng `correlation_id`: xem `usage_details`/`cost_details` của `llm-generation` và prompt version được link.
- Mitigation tạm thời: nếu trùng thời điểm đổi prompt → rollback label `production`; nếu output token tăng → giới hạn `max_tokens`/độ dài câu trả lời; tạm hạ model cho feature ít quan trọng. Trong lab: tắt practice scenario.
- Owner: `student-2A202602928`
