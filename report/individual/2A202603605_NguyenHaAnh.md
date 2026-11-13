# Báo cáo cá nhân — Day 06: Data Ingestion Engineering

**Học viên:** Nguyễn Hà Anh · **MSSV:** `2A202603605` · **Lớp:** `L3A`

---

## 1. Dữ liệu và pipeline

### Chủ đề, nguồn/quyền, số trang và quy tắc tính trang
- **Chủ đề hẹp:** Tiêu chuẩn Web & HTTP API của IETF (Web & HTTP API Standards, 2022–2023).
- **Corpus gồm 3 tài liệu PDF công khai** (xem [data/manifest.json](../../data/manifest.json)):
  1. `rfc9111` — *RFC 9111: HTTP Caching* (`starter/data/rfc9111_http_caching.pdf`, STD 98, tháng 6/2022): **35** trang vật lý → **26** trang nội dung hợp lệ (trang 5–30); loại 9 trang (trang 1–4 bìa/bản quyền/mục lục, trang 31–32 chỉ có References, trang 33–35 Index và Authors' Addresses).
  2. `rfc9457` — *RFC 9457: Problem Details for HTTP APIs* (`starter/data/rfc9457_http_problem_details.pdf`, tháng 7/2023): **16** trang vật lý → **11** trang nội dung hợp lệ (trang 3–10, 13–15); loại 5 trang (trang 1–2 bìa/mục lục, trang 11–12 References/Security+Normative References được loại bảo thủ, trang 16 Acknowledgements/Authors' Addresses).
  3. `rfc9309` — *RFC 9309: Robots Exclusion Protocol* (`starter/data/rfc9309_robots_exclusion.pdf`, tháng 9/2022): **12** trang vật lý → **8** trang nội dung hợp lệ (trang 3–10); loại 4 trang (trang 1–2 bìa/mục lục, trang 11 References, trang 12 Authors' Addresses).
- **Tổng hợp:** **45 trang nội dung hợp lệ** / 63 trang vật lý (107.375 ký tự chuẩn hóa trước khi loại tiêu đề/chân trang lặp).
- **Quyền sử dụng:** Cả 3 tài liệu thuộc *IETF Trust Legal Provisions (TLP)*, là đặc tả chuẩn mở cho phép tải, trích xuất, lập chỉ mục và tái phân phối nguyên văn.
- **Quy tắc tính trang:** Đếm trang PDF vật lý (đánh số từ 1) có nội dung kỹ thuật hoặc phụ lục đặc tả thực chất; loại bỏ trang bìa/thông báo trạng thái/bản quyền, trang mục lục (ToC), trang chỉ chứa tài liệu tham khảo (References), lời cảm ơn, bảng chỉ mục (Index) và địa chỉ tác giả.

### Chuẩn hóa, lỗi và giới hạn
- **Chuẩn hóa** ([starter/src/ingestion.py](../../starter/src/ingestion.py)): Dùng `unicodedata.normalize("NFKC", text)` để chuyển các ký tự ghép như `ﬁ`/`ﬂ` về `fi`/`fl`, loại bỏ dòng header/footer lặp của RFC (`RFC XXXX ... 202X`, `... [Page N]`, `Fielding/Nottingham/Koster, et al. Standards Track Page N`), gộp khoảng trắng thừa và giữ ranh giới xuống dòng/đoạn.
- **Lỗi trích xuất phát hiện và log** ([results/ingestion_log.json](../../results/ingestion_log.json)):
  - Không có trang scan hoặc trang rỗng trong 45 trang hợp lệ (`0` trang `empty_or_unreadable`).
  - **Giới hạn của `pypdf` trên PDF tạo bởi `xml2rfc`:** Một số từ khóa BCP 14 (`MUST`, `MUST NOT`, `SHOULD`, `SHOULD NOT`, `MAY`) và tham chiếu chéo (`[HTTP]`, `[RFC2119]`) vốn là `<span>` định vị riêng trong PDF nên bị `pypdf` đẩy xuống cuối đoạn thay vì nằm đúng vị trí giữa câu (ví dụ ở `rfc9457` trang 7: `"It SHOULD NOT change..."` bị tách thành `"It change..."` và `"SHOULD NOT"` nằm cuối đoạn). Điều này làm giảm độ khớp ngữ nghĩa ở câu `q09`.

### Embedding model, Vector store, Metric, Lệnh chạy và Chi phí
- **Embedding model:** Local `sentence-transformers/all-MiniLM-L6-v2` (qua `sentence-transformers==6.3.0`, `torch==2.15.0+cpu` trên Python 3.12), **384 chiều**, `normalize_embeddings=True`, dùng cùng model và cách mã hóa cho cả document và query.
- **Vector store:** PostgreSQL `16.16` + pgvector `0.8.7` chạy qua Docker (`starter/docker-compose.yml`, cổng `127.0.0.1:55433`, bảng `rag_chunks`).
- **Metric tìm kiếm:** Exact cosine similarity `1.0 - (embedding <=> query_vector)` (sắp xếp theo khoảng cách cosine tăng dần `embedding <=> query_vector ASC`).
- **Kiểm tra nạp lại (idempotency):** Thực nghiệm gọi `store.upsert()` 2 lần liên tiếp cho cùng phiên bản dữ liệu trên cả A, B, C; số dòng trong DB giữ nguyên tuyệt đối (`A: 249 -> 249`, `B: 179 -> 179`, `C: 179 -> 179`, `deleted_obsolete = 0`). Khi tài liệu thay đổi, `upsert` chủ động `DELETE` các `chunk_id` cũ thuộc `(strategy, document_id)` không còn tồn tại trong danh sách chunk mới.
- **Lệnh chạy tái lập (PowerShell):**
  ```powershell
  cd starter
  docker compose -p day6_student_starter up -d --wait
  .\.venv\Scripts\python.exe scripts/check_setup.py
  .\.venv\Scripts\python.exe -m src.run
  ```
- **Chi phí:** **$0.00** (chạy hoàn toàn local trên CPU).

### Metadata bắt buộc, trường lọc bổ sung và lý do chọn
- **Metadata bắt buộc:** `document_id`, `source`, `page` (số trang PDF vật lý từ 1).
- **Trường bổ sung:**
  - `category` (`TEXT`: `http_caching`, `http_error_handling`, `web_crawling`) — lấy từ chủ đề chính thức của từng RFC trong manifest; dùng để cô lập ngữ cảnh domain khi các RFC dùng chung thuật ngữ (ví dụ "cache", "redirects", "5xx").
  - `year` (`INTEGER`: `2022`, `2023`) — lấy từ ngày xuất bản trên trang đầu RFC; hỗ trợ lọc theo mốc phiên bản chuẩn.
  - `section` (`TEXT`) — trích xuất tự động từ heading đánh số (`1.2.2.`, `Appendix B.`, ...); giúp truy vết nhanh tới tiểu mục mà không phải đọc lại cả trang.

---

## 2. Cấu hình và benchmark

### Ba chiến lược A / B / C (B–C chỉ khác duy nhất bộ lọc metadata)
| Chiến lược | Chunking | Tham số | Metadata lưu trữ | Truy xuất & Lọc |
|---|---|---|---|---|
| **A** | `fixed_size` | `size=500` ký tự, `overlap=50` | `document_id, source, page, category, year, section` | Top-3 cosine, **không lọc** |
| **B** | `by_paragraph` | Gom đoạn theo cấu trúc/heading trong trang, `max_size=900` | Giống hệt A | Top-3 cosine, **không lọc** |
| **C** | `by_paragraph` | Giống hệt B (`max_size=900`) | Giống hệt B | Top-3 cosine + **SQL `WHERE` lọc theo `category`/`year`** khi câu hỏi có `filter` |

### Bộ câu hỏi Benchmark (20 câu: 15 dev / 5 test)
- File benchmark: [benchmark/questions.json](../../benchmark/questions.json) (khởi tạo và khóa trước khi chạy thử nghiệm).
- Phân bố: **15 câu `dev` (`q01`–`q15`)** và **5 câu `test` (`q16`–`q20`)**, phủ đều 3 RFC và 4 nhóm câu hỏi: trực tiếp (`truc_tiep`), diễn đạt lại (`dien_dat_lai`), điều kiện/ngoại lệ (`dieu_kien_ngoai_le`), và **5 câu kiểm tra metadata filter** (3 dev: `q13`, `q14`, `q15`; 2 test: `q19`, `q20`).
- **Kiểm chứng evidence:** Đã chạy script đối chiếu tự động xác nhận **20/20** `evidence_quote` tồn tại nguyên văn trong văn bản chuẩn hóa của đúng `(gold_source_id, gold_page)`. Giá trị `filter` chỉ sử dụng ngữ cảnh hợp lệ (`category`, `year`), không đưa `gold_source_id` hay đáp án vào query/filter.

### Tiêu chí chọn chiến lược đã chốt trước khi xem test
1. Ưu tiên cao nhất: **`Evidence Hit@3` trên tập `dev`** (15 câu).
2. Hòa điểm ưu tiên tiếp: **`Hit@1` trên `dev`** → **Chunk Coherence trung bình (/2)** → **Grounding Quality trung bình (/2)** → **chi phí & tài nguyên lưu trữ**.

---

## 3. Kết quả

### Bảng 1: Retrieval Accuracy & Tài nguyên (Dev và Test tách riêng)
| Strategy | Split | Hit@1 (n/N) | Evidence Hit@3 (n/N) | Chunk count | Thời gian ingest / query | Chi phí |
|---|---|---:|---:|---:|---:|---:|
| **A** | `dev` | 5/15 (33.3%) | 7/15 (46.7%) | 249 | 3.692s ingest / 0.484s (20q) | $0.00 |
| **A** | `test` | 1/5 (20.0%) | 2/5 (40.0%) | 249 | *(cùng index A)* | $0.00 |
| **B** | `dev` | **12/15 (80.0%)** | **12/15 (80.0%)** | 179 | 3.158s ingest / 0.517s (20q) | $0.00 |
| **B** | `test` | **5/5 (100.0%)** | **5/5 (100.0%)** | 179 | *(cùng index B)* | $0.00 |
| **C** | `dev` | **12/15 (80.0%)** | **12/15 (80.0%)** | 179 | 3.146s ingest / 0.527s (20q) | $0.00 |
| **C** | `test` | **5/5 (100.0%)** | **5/5 (100.0%)** | 179 | *(cùng index C)* | $0.00 |

### Bảng 2: Đánh giá thủ công (Coherence, Metadata Usefulness, Grounding Quality)
| Strategy | Coherence TB /2 (n=10) | Metadata đủ & đúng (test top-3) | Filter tuân thủ (test) | Filter tuân thủ (dev) | Grounding 0/1/2 (test, n=5) & TB /2 |
|---|---:|---:|---:|---:|---|
| **A** | **0.70 / 2** (`0`:3, `1`:7, `2`:0) | **15/15** | **2/2** | 2/3 (`q13` sai) | `0`: 1, `1`: 2, `2`: 2 → TB **1.20 / 2** |
| **B** | **1.90 / 2** (`0`:0, `1`:1, `2`:9) | **15/15** | **2/2** | 2/3 (`q13` sai) | `0`: 0, `1`: 0, `2`: 5 → TB **2.00 / 2** |
| **C** | **1.90 / 2** (`0`:0, `1`:1, `2`:9) | **15/15** | **2/2** | **3/3** | `0`: 0, `1`: 0, `2`: 5 → TB **2.00 / 2** |

### Đường dẫn trace, nhãn thủ công và cách chọn mẫu
- Trace đầy đủ top-3 (60 lượt truy xuất): [results/traces_all.json](../../results/traces_all.json)
- Tổng hợp số liệu & cấu hình: [results/metrics_summary.json](../../results/metrics_summary.json), [results/strategy_stats.json](../../results/strategy_stats.json)
- Audit thủ công Coherence (chọn cố định 10 vị trí đầu theo thứ tự tài liệu/trang trước khi xem điểm: `rfc9111` trang 5–8, `rfc9457` trang 3–5, `rfc9309` trang 3–5): [results/manual_coherence_audit.csv](../../results/manual_coherence_audit.csv)
- Audit thủ công Metadata (15 bản ghi/chiến lược trên 5 câu test × top-3): [results/manual_metadata_audit.csv](../../results/manual_metadata_audit.csv)
- Audit thủ công Grounding (5 câu test/chiến lược): [results/manual_grounding_audit.csv](../../results/manual_grounding_audit.csv)
- *Lưu ý minh bạch:* Người chấm thủ công là tác giả bài làm (Nguyễn Hà Anh), có thể tồn tại thiên lệch xác nhận; toàn bộ câu chữ chunk và lý do chấm từng mẫu đã được lưu nguyên văn trong CSV/JSON để đối chiếu độc lập.

---

## 4. Phân tích và kết luận

### So sánh A–B (Tác động của chiến lược chunking)
- Chuyển từ `fixed_size(500, 50)` (A) sang `by_paragraph(900)` (B) giúp:
  - **Hit@3 tăng mạnh:** từ `7/15 (46.7%)` lên `12/15 (80.0%)` trên `dev`, và từ `2/5 (40.0%)` lên `5/5 (100.0%)` trên `test`.
  - **Hit@1 tăng mạnh hơn nữa:** từ `5/15` lên `12/15` trên `dev` (+46.7 điểm %), nhờ việc gom trọn một quy tắc kỹ thuật + điều kiện ngoại lệ vào cùng 1 chunk, giúp embedding đại diện đúng ý nghĩa cả đoạn.
  - **Coherence tăng từ `0.70/2` lên `1.90/2`:** A cắt đứt giữa từ/giữa câu ở 10/10 vị trí mẫu, trong khi B giữ trọn ý ở 9/10 vị trí (chỉ `rfc9111_p07_c01` đạt 1/2 vì phần danh sách gạch đầu dòng sau dấu `:` rơi sang chunk `c02`).
  - **Tài nguyên giảm:** Số chunk giảm 28.1% (từ 249 xuống 179 chunk), thời gian ingest giảm từ `3.692s` xuống `3.158s` và tổng ký tự lưu trữ giảm từ `113.715` xuống `103.466` ký tự (không bị trùng lặp do overlap).

### So sánh B–C (Tác động của metadata filter)
- Với cùng tập 179 chunk giống hệt nhau, B và C đạt cùng `Evidence Hit@3 = 12/15 (dev)` và `5/5 (test)`, nhưng khác biệt quyết định nằm ở **tính tuân thủ phạm vi lọc (Filter Compliance)**:
  - **Minh họa ở `q13` (`dev`, filter `{"category": "web_crawling"}`):** Câu hỏi hỏi về thời hạn lưu cache file đã tải khi tài nguyên không truy cập được (không nhắc tên `robots.txt`). Ở **B (không lọc)**, dù Rank 1 đúng là `rfc9309_p09_c01`, nhưng Rank 2 (`rfc9111_p15_c02`) và Rank 3 (`rfc9111_p07_c01`) bị rò rỉ từ `http_caching` (`rfc9111`), khiến tỷ lệ tuân thủ filter của B chỉ đạt `2/3`. Ở **C (có SQL `WHERE category = 'web_crawling'`)**, toàn bộ top-3 (`rfc9309_p09_c01`, `rfc9309_p08_c05`, `rfc9309_p08_c03`) đều nằm đúng trong tài liệu `web_crawling` (**3/3** trên `dev` và **2/2** trên `test`).
- **Hữu ích và hạn chế của metadata:**
  - *Hữu ích:* `category` kết hợp `year` ngăn rò rỉ chéo giữa các đặc tả có từ khóa trùng nhau (`cache`, `5xx`, `URI`, `redirect`).
  - *Hạn chế:* (1) Heuristic gán `section` nhận diện heading theo từng trang nên đoạn đầu trang nằm trước heading mới có thể mang tên section trước đó hoặc fallback `"Introduction"` ở trang đầu; (2) `year` không đủ phân biệt hai tài liệu cùng năm (`rfc9111` và `rfc9309` đều năm `2022`), cần dùng kết hợp `category`.

### 2 ví dụ sai tiêu biểu (kèm ID câu hỏi, chunk ID và nguồn gốc)
1. **Lỗi do cắt ngang ranh giới (Chunking Boundary Error) — Câu `q01` (`dev`, Chiến lược A) và `q17` (`test`, Chiến lược A):**
   - **Câu `q01` (nguồn gold: `rfc9111` trang 6, Section `1.2.2. Delta Seconds`):** Chiến lược A trả về chunk `rfc9111_p06_c01` ở Rank 2 (`score=0.7923`) có đúng tiêu đề nhưng bị cắt cụt ngay giữa câu quy tắc (`"...or the greatest positive integer it"`), thiếu mất phần `"can conveniently represent."` (rơi sang `c02`), dẫn đến `Hit@3 = False`. Chiến lược B/C giữ trọn đoạn 529 ký tự trong `rfc9111_p06_c01` nên trúng ngay Rank 1.
   - Tương tự ở **câu `q17` (`test`, nguồn gold: `rfc9111` trang 23, Section `5.2.2.3`)**: A lấy được `rfc9111_p23_c01` ở Rank 2 nhưng cắt cụt giữa từ `"no-store\ndire"` ngay trước mệnh đề điều kiện `"the cache ignore the no-store directive if it understands..."` (Grounding chỉ đạt 1/2).
2. **Lỗi do trích xuất PDF tách từ khóa (PDF Extraction Artifact) — Câu `q09` (`dev`, thất bại ở cả A, B, C):**
   - **Câu `q09` (nguồn gold: `rfc9457` trang 7, Section `3.1.3. "title"`):** Hỏi khi nào trường `"title"` được phép thay đổi giữa các lần lỗi. Dù `rfc9457_p07` chứa đúng đáp án, cả B và C lại xếp `rfc9457_p04_c02` (`0.5853`), `rfc9457_p08_c01` (`0.5309`), `rfc9457_p09_c01` (`0.4966`) vào top-3. Nguyên nhân gốc rễ từ bước `pypdf` ingestion: từ khóa phủ định **`SHOULD NOT`** bị tách khỏi câu `"It [SHOULD NOT] change from occurrence to occurrence..."` xuống cuối trang, làm câu văn mất từ khóa ràng buộc/cho phép và bị các đoạn ví dụ chung về `"title"` lấn át.

### Chiến lược chọn, đánh đổi và điều kiện áp dụng
- **Chiến lược được chọn: Chiến lược C** (`by_paragraph` `max_size=900` + SQL metadata filter).
- **Lý do theo tiêu chí đã chốt:** C đồng hạng nhất với B về `dev Evidence Hit@3` (`12/15`), `dev Hit@1` (`12/15`), Coherence (`1.90/2`), Grounding (`2.00/2`), thời gian ingest (~3.15s) và dung lượng (179 chunks), nhưng **vượt B ở Filter Compliance (`3/3` vs `2/3` trên `dev`)** nên loại bỏ hoàn toàn nhiễu ngoài phạm vi khi người dùng/ứng dụng cung cấp ngữ cảnh `category` hoặc `year`.
- **Đánh đổi & điều kiện áp dụng:**
  - `by_paragraph` đạt coherence và độ chính xác cao hơn nhiều so với `fixed_size`, nhưng phụ thuộc cấu trúc văn bản có ranh giới đoạn/heading rõ ràng (với PDF không có cấu trúc hoặc OCR nhiễu, cần bước tiền xử lý bố cục tốt hơn).
  - SQL metadata filter của C chỉ phát huy tác dụng khi ngữ cảnh đầu vào có `category`/`year` chính xác; nếu người dùng lọc nhầm `category`, SQL hard-filter sẽ loại mất đáp án đúng (cần cơ chế fallback sang không lọc khi kết quả rỗng nếu đưa lên production).

### Hạn chế và hướng cải tiến
- **Hạn chế:** (1) Tập `test` chỉ gồm 5 câu nên tỷ lệ `5/5 (100%)` trên B/C chỉ mang tính minh họa trên bộ câu hỏi nhỏ này, không được suy rộng thành hiệu năng tổng quát; (2) Người chấm audit thủ công là tác giả; (3) `pypdf` chưa giữ đúng vị trí inline của thẻ BCP 14 (`MUST`/`SHOULD NOT`) trong PDF `xml2rfc`.
- **Hướng cải tiến nếu làm lại/mở rộng:**
  1. Thay `pypdf` bằng parser nhận diện tọa độ chính xác hơn (như `pymupdf` / `pdfplumber` theo thứ tự x-y từng từ) để không làm rơi `MUST`/`SHOULD NOT` xuống cuối đoạn.
  2. Thử nghiệm **Hybrid Retrieval** (kết hợp dense cosine + PostgreSQL `tsvector`/BM25) cho các từ khóa đặc hiệu như tên header (`Set-Cookie`, `Pragma`, `ALPHA`, `DIGIT`) — những câu như `q04` hay `q10` mà dense embedding nhỏ (384d) dễ nhầm với các đoạn ví dụ có từ khóa gần giống.
  3. Mở rộng bộ benchmark lên ≥ 50 câu với nhiều câu multi-chunk và đánh giá chéo độc lập.
