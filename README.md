# Day 06 · Data Ingestion Engineering (Bài nộp cá nhân)

**Học viên:** Nguyễn Hà Anh (`2A202603605` · Lớp `L3A`)  
**Chủ đề corpus:** Web & HTTP API Standards — IETF RFC 9111 (HTTP Caching), RFC 9457 (Problem Details for HTTP APIs), RFC 9309 (Robots Exclusion Protocol)

---

## Cấu trúc bài nộp

- [STUDENT.md](STUDENT.md): Thông tin học viên và corpus.
- [data/manifest.json](data/manifest.json): Manifest đầy đủ của 3 tài liệu PDF (45 trang nội dung hợp lệ / 63 trang vật lý, quy tắc tính trang, giấy phép IETF TLP).
- [benchmark/questions.json](benchmark/questions.json): Bộ 20 câu hỏi benchmark (15 `dev` / 5 `test`, 5 câu có `filter`), có `evidence_quote` kiểm chứng nguyên văn trên trang nguồn.
- [starter/src/](starter/src/): Mã nguồn pipeline ingestion, chunking (`fixed_size` & `by_paragraph`), embedding local (`sentence-transformers/all-MiniLM-L6-v2`), lưu trữ & truy vấn PostgreSQL + pgvector (`store.py`), đánh giá (`evaluation.py`) và script chạy tổng hợp (`run.py`).
- [artifacts/experiment_log.csv](artifacts/experiment_log.csv): Bảng tổng hợp cấu hình, giả thuyết và kết quả A/B/C.
- [results/](results/): Toàn bộ log ingest, thống kê chiến lược, trace top-3 đầy đủ (`traces_all.json`), bảng đo (`metrics_summary.json`/`.csv`) và 3 bộ nhãn audit thủ công (`manual_coherence_audit`, `manual_metadata_audit`, `manual_grounding_audit`).
- [report/individual/2A202603605_NguyenHaAnh.md](report/individual/2A202603605_NguyenHaAnh.md): Báo cáo cá nhân đầy đủ theo 5 khía cạnh đánh giá.

---

## Hướng dẫn cài đặt và chạy tái lập

> Yêu cầu: **Docker Desktop** (hoặc Docker Engine + Compose) và **Python 3.12** (để chạy `torch` CPU + `sentence-transformers` local).

1. **Khởi động PostgreSQL + pgvector qua Docker (từ thư mục `starter/`):**
   ```powershell
   cd starter
   Copy-Item .env.example .env
   docker compose -p day6_student_starter up -d --wait
   ```

2. **Tạo virtual environment Python 3.12 và cài dependencies:**
   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install --upgrade pip
   .\.venv\Scripts\python.exe -m pip install torch --index-url https://download.pytorch.org/whl/cpu
   .\.venv\Scripts\python.exe -m pip install sentence-transformers -r requirements.txt
   ```

3. **Kiểm tra kết nối database & pgvector:**
   ```powershell
   .\.venv\Scripts\python.exe scripts/check_setup.py
   ```
   Kỳ vọng: in ra phiên bản PostgreSQL, pgvector `0.8.7` và `Setup OK`.

4. **Chạy toàn bộ pipeline ingestion, lưu vector và benchmark A/B/C:**
   ```powershell
   .\.venv\Scripts\python.exe -m src.run
   ```
   Kết quả và trace sẽ được xuất vào `results/` (và `starter/results/`).

5. **Dừng container sau khi hoàn tất (giữ nguyên dữ liệu trong volume):**
   ```powershell
   docker compose -p day6_student_starter stop
   ```

---

## Tóm tắt kết quả chính

| Strategy | Chunking & Filter | Dev Hit@1 | Dev Hit@3 | Test Hit@1 | Test Hit@3 | Coherence (/2) | Grounding (/2) | Dev Filter |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| **A** | Fixed 500 (overlap 50), không lọc | 5/15 (33.3%) | 7/15 (46.7%) | 1/5 (20.0%) | 2/5 (40.0%) | 0.70 | 1.20 | 2/3 |
| **B** | By paragraph (max 900), không lọc | 12/15 (80.0%) | 12/15 (80.0%) | 5/5 (100.0%) | 5/5 (100.0%) | 1.90 | 2.00 | 2/3 |
| **C** | **By paragraph (max 900) + SQL filter** | **12/15 (80.0%)** | **12/15 (80.0%)** | **5/5 (100.0%)** | **5/5 (100.0%)** | **1.90** | **2.00** | **3/3** |
