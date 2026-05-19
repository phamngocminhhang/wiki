# Wiki Scraper API Documentation

## Overview

The Wiki Scraper API provides endpoints to manage book scraping from wikicv.net, track download progress, and generate EPUB files. The API is built with **FastAPI** and runs on port **8765**.

**Base URL:** `http://localhost:8765/api` (local) or `https://books.example.com/api` (production)

---

## Table of Contents

1. [Status & Daily Limit](#status--daily-limit)
2. [Books Queue Management](#books-queue-management)
3. [Book Details & Download](#book-details--download)
4. [Scraping Control](#scraping-control)
5. [Error Codes](#error-codes)
6. [Rate Limiting](#rate-limiting)
7. [Examples](#examples)

---

## Status & Daily Limit

### GET /api/status

Returns overall system status, queue summary, and daily chapter limit info.

**Request:**
```
GET /api/status
```

**Response:** `200 OK`
```json
{
  "daily": {
    "date": "2026-05-02",
    "used": 45,
    "limit": 200,
    "remaining": 155
  },
  "queue_summary": {
    "total": 5,
    "queued": 2,
    "in_progress": 1,
    "paused": 1,
    "done": 1,
    "error": 0
  },
  "is_scraping": true
}
```

**Response Fields:**
- `daily.date` — Today's date (YYYY-MM-DD)
- `daily.used` — Chapters downloaded today
- `daily.limit` — Maximum chapters per day
- `daily.remaining` — Chapters available today
- `queue_summary` — Count of books in each status
- `is_scraping` — Whether scraping is currently running

---

### GET /api/daily-limit

Returns only the daily chapter limit info.

**Request:**
```
GET /api/daily-limit
```

**Response:** `200 OK`
```json
{
  "date": "2026-05-02",
  "used": 45,
  "limit": 200,
  "remaining": 155
}
```

---

## Books Queue Management

### GET /api/books

Retrieves all books in the queue.

**Request:**
```
GET /api/books
```

**Response:** `200 OK`
```json
{
  "books": [
    {
      "book_url": "https://wikicv.net/sach/truyen-1",
      "status": "done",
      "added_at": "2026-05-01T10:30:45.123456",
      "title": "Truyện Hay",
      "author": "Tác giả A",
      "cover_url": "https://wikicv.net/cover.jpg",
      "total_chapters": 150,
      "downloaded_chapters": 150,
      "epub_path": "/var/www/book-scraper/App/epubs/Truyen-Hay.epub",
      "error": null
    }
  ]
}
```

**Status Values:**
- `queued` — Waiting to be processed
- `in_progress` — Currently downloading
- `paused` — Stopped (waiting for limit reset)
- `done` — All chapters downloaded
- `error` — Failed to process

---

### POST /api/books

Adds a new book to the download queue.

**Request:**
```
POST /api/books
Content-Type: application/json

{
  "url": "https://wikicv.net/sach/book-name"
}
```

**Response:** `200 OK`
```json
{
  "ok": true,
  "url": "https://wikicv.net/sach/book-name"
}
```

**Errors:**
- `400 Bad Request` — Invalid URL (must start with `http`)
- `409 Conflict` — Book already in queue

**Example:**
```bash
curl -X POST http://localhost:8765/api/books \
  -H "Content-Type: application/json" \
  -d '{"url": "https://wikicv.net/sach/truyen-1"}'
```

---

### GET /api/books/{slug}

Retrieves detailed information for a specific book, including chapter list.

**Request:**
```
GET /api/books/truyen-1
```

Where `{slug}` is the last part of the book URL.

**Response:** `200 OK`
```json
{
  "book_url": "https://wikicv.net/sach/truyen-1",
  "status": "in_progress",
  "added_at": "2026-05-01T10:30:45.123456",
  "title": "Truyện Hay",
  "author": "Tác giả A",
  "cover_url": "https://wikicv.net/cover.jpg",
  "total_chapters": 150,
  "downloaded_chapters": 45,
  "epub_path": null,
  "error": null,
  "chapters": [
    {
      "title": "Chương 1",
      "url": "https://wikicv.net/sach/truyen-1/chuong-1",
      "html": null,
      "downloaded": false
    },
    {
      "title": "Chương 2",
      "url": "https://wikicv.net/sach/truyen-1/chuong-2",
      "html": "<p>Chapter content...</p>",
      "downloaded": true
    }
  ],
  "metadata": {
    "book_url": "https://wikicv.net/sach/truyen-1",
    "title": "Truyện Hay",
    "author": "Tác giả A",
    "cover_url": "https://wikicv.net/cover.jpg",
    "cover_info": "<div>...</div>",
    "description": "<div>Book description...</div>"
  }
}
```

**Errors:**
- `404 Not Found` — Book not found in queue

---

### DELETE /api/books/{slug}

Removes a book from the queue. Already downloaded chapters remain in cache.

**Request:**
```
DELETE /api/books/truyen-1
```

**Response:** `200 OK`
```json
{
  "ok": true
}
```

**Errors:**
- `404 Not Found` — Book not found

**Example:**
```bash
curl -X DELETE http://localhost:8765/api/books/truyen-1
```

---

### PUT /api/books/reorder

Reorders books in the queue by providing an ordered list of URLs.

**Request:**
```
PUT /api/books/reorder
Content-Type: application/json

{
  "ordered_urls": [
    "https://wikicv.net/sach/book-1",
    "https://wikicv.net/sach/book-3",
    "https://wikicv.net/sach/book-2"
  ]
}
```

**Response:** `200 OK`
```json
{
  "ok": true
}
```

**Notes:**
- Books not in the list are appended to the end
- Order takes effect immediately for the next scraping session
- In-progress books cannot be reordered

**Example:**
```bash
curl -X PUT http://localhost:8765/api/books/reorder \
  -H "Content-Type: application/json" \
  -d '{
    "ordered_urls": [
      "https://wikicv.net/sach/book-1",
      "https://wikicv.net/sach/book-2"
    ]
  }'
```

---

## Book Details & Download

### GET /api/books/{slug}/download

Builds an EPUB file from downloaded chapters and returns it as a download.

**Request:**
```
GET /api/books/truyen-1/download
```

**Response:** `200 OK`
- Content-Type: `application/epub+zip`
- File download triggered

**Features:**
- Automatically builds EPUB with downloaded chapters
- Includes cover image, metadata, and styling
- Chapters are numbered sequentially
- Table of contents auto-generated

**Errors:**
- `404 Not Found` — Book not found
- `400 Bad Request` — No downloaded chapters to build EPUB
- `404 Not Found` — EPUB file missing after build

**Example:**
```bash
# Download to file
curl -X GET http://localhost:8765/api/books/truyen-1/download \
  --output book.epub
```

---

## Scraping Control

### POST /api/run-now

Manually triggers a scraping session immediately (outside the 7 AM schedule).

**Request:**
```
POST /api/run-now
```

**Response:** `200 OK`
```json
{
  "ok": true,
  "message": "Scraping session started"
}
```

**Response:** `200 OK` (Already Running)
```json
{
  "ok": false,
  "message": "Already running"
}
```

**Notes:**
- Returns immediately (scraping runs in background)
- Cannot run while another session is active
- Respects daily chapter limit
- Check `/api/status` to monitor progress

**Example:**
```bash
curl -X POST http://localhost:8765/api/run-now
```

---

## Error Codes

| Code | Meaning | Example |
|------|---------|---------|
| `200` | Success | Request completed successfully |
| `400` | Bad Request | Invalid URL, missing chapters for EPUB |
| `404` | Not Found | Book not in queue, file missing |
| `409` | Conflict | Book already in queue |

---

## Rate Limiting

- No rate limiting enforced by default
- Browser delays controlled by `config.json`:
  - `WAIT_TIME_PER_CHAPTER` — Seconds between chapters (default: 1.5)
  - `EXTRA_WAIT_AFTER_PAGE_LOAD` — Extra wait for page load (default: 23)

---

## Data Models

### Book Object

```json
{
  "book_url": "https://wikicv.net/sach/book-name",
  "status": "in_progress",
  "added_at": "2026-05-01T10:30:45.123456",
  "title": "Book Title",
  "author": "Author Name",
  "cover_url": "https://example.com/cover.jpg",
  "total_chapters": 150,
  "downloaded_chapters": 45,
  "epub_path": "/path/to/file.epub",
  "error": null
}
```

### Chapter Object

```json
{
  "title": "Chapter Title",
  "url": "https://wikicv.net/sach/book-name/chapter-1",
  "html": "<p>Chapter content...</p>",
  "downloaded": true
}
```

### Daily Limit Object

```json
{
  "date": "2026-05-02",
  "used": 45,
  "limit": 200,
  "remaining": 155
}
```

---

## Examples

### Example 1: Add a Book and Check Status

```bash
# Add book
curl -X POST http://localhost:8765/api/books \
  -H "Content-Type: application/json" \
  -d '{"url": "https://wikicv.net/sach/truyen-hay"}'

# Check status
curl http://localhost:8765/api/status

# Trigger immediate scrape
curl -X POST http://localhost:8765/api/run-now

# Wait a few seconds, then check progress
sleep 5
curl http://localhost:8765/api/books/truyen-hay
```

### Example 2: Queue Multiple Books and Reorder

```bash
# Add three books
curl -X POST http://localhost:8765/api/books \
  -H "Content-Type: application/json" \
  -d '{"url": "https://wikicv.net/sach/book-1"}'

curl -X POST http://localhost:8765/api/books \
  -H "Content-Type: application/json" \
  -d '{"url": "https://wikicv.net/sach/book-2"}'

curl -X POST http://localhost:8765/api/books \
  -H "Content-Type: application/json" \
  -d '{"url": "https://wikicv.net/sach/book-3"}'

# Reorder: book-3 first, then book-1, then book-2
curl -X PUT http://localhost:8765/api/books/reorder \
  -H "Content-Type: application/json" \
  -d '{
    "ordered_urls": [
      "https://wikicv.net/sach/book-3",
      "https://wikicv.net/sach/book-1",
      "https://wikicv.net/sach/book-2"
    ]
  }'

# Verify order
curl http://localhost:8765/api/books
```

### Example 3: Download EPUB After Scraping

```bash
# Check if chapters are downloaded
curl http://localhost:8765/api/books/truyen-1 | grep downloaded_chapters

# Download EPUB (wait until at least 1 chapter is downloaded)
curl -X GET http://localhost:8765/api/books/truyen-1/download \
  --output "Truyen-Hay.epub"

# File saved as Truyen-Hay.epub
ls -lh Truyen-Hay.epub
```

### Example 4: Monitor Daily Limit

```bash
# Check daily limit
while true; do
  curl http://localhost:8765/api/daily-limit | jq '.'
  sleep 5
done
```

---

## CORS Policy

The API has CORS enabled for all origins, methods, and headers:

```python
allow_origins=["*"]
allow_methods=["*"]
allow_headers=["*"]
```

---

## WebSocket Support

Not currently implemented. Use polling with `/api/status` for real-time updates.

---

## Notes for Developers

- All times are in **ISO 8601 format** with timezone info
- Book slugs are extracted from the last part of the URL
- Chapter HTML is stored in cache, not returned by default (except in `/api/books/{slug}`)
- EPUB files are stored in `epubs/` folder and remain after book removal
- Daily limit resets at **7:00 AM** server time daily

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| `Cannot reach backend` | Ensure `uvicorn main:app` is running on port 8765 |
| `Book already in queue` | Remove with DELETE, then re-add |
| `No downloaded chapters` | Wait for scraper to run or trigger manually with `/run-now` |
| `EPUB download fails` | Check logs in `logs/scraper.log` for errors |
| `Permission denied` | Run service with proper user permissions (see main README) |
