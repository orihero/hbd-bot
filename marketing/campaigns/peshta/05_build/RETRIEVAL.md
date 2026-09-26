# Retrieval — CONFIRMED 2026-09-19 (was ASSUMED in 05_HIGGSFIELD_RECREATION_SETUP.md Step 6)

1. `generate_image` / `generate_video` return `{"results":[{"id":"<uuid>","status":"pending",...}]}`.
   `count:4` returns FOUR separate job ids, one per image — not one job with four outputs.
2. Wait with `jobs_wait`, whose arg is `jobs: [{"index":<int>,"job_id":"<uuid>"}]` — **objects, not
   bare id strings**, `index` is REQUIRED, and the array is capped at **12 jobs per call**.
   `timeout_seconds` max is 15.
3. The file URL is **`jobs[].result_url`** — a cloudfront URL. Download with plain `curl -L`.
   No `show_generation_by_ids` call is needed to get the URL; it is already in the wait response.
