# Book Scraper App - User Guide

## Overview

The Book Scraper App is a web-based application for downloading chapters from **wikicv.net** and converting them into EPUB ebook files. It runs a scheduled scraper that respects daily chapter limits and manages a download queue automatically.

---

## Getting Started

### Opening the App

#### **Local Setup (Development)**

1. Navigate to the `App` folder:
   ```bash
   cd App
   ```

2. Start the server:
   ```bash
   uvicorn main:app --host 127.0.0.1 --port 8765
   ```

3. Open your browser and go to:
   ```
   http://127.0.0.1:8765
   ```

#### **VPS/Production Setup**

The app will automatically start with systemd (if configured) when your server boots. Access it through your domain:
```
https://books.example.com
```

---

## Main Features

### 1. **Add Books to Queue**

- Click **"Add Book"** button
- Paste the wikicv.net book URL (e.g., `https://wikicv.net/book-name`)
- Click **"Add"** to add to the download queue
- Books cannot be added twice (duplicates are rejected)

### 2. **View Queue & Status**

- See all books in your queue with their current status:
  - **Queued**: Waiting to be processed
  - **In Progress**: Currently downloading chapters
  - **Paused**: Stopped due to daily limit
  - **Done**: All chapters downloaded
  - **Error**: Failed to process

- Status updates show:
  - Book title and author
  - Total chapters
  - Downloaded chapters count
  - Progress percentage

### 3. **Reorder Queue**

- Drag books to change download priority
- Books at the top are processed first when scraping runs
- Changes take effect immediately

### 4. **Cancel Books**

- Click the **"Remove"** button on any book
- Book is deleted from queue and will not be processed
- Already downloaded chapters are kept in cache

### 5. **Download EPUB Files**

- Once at least one chapter is downloaded, the **"Download EPUB"** button becomes active
- Click **"Download EPUB"** to:
  - Build the EPUB file with downloaded chapters
  - Automatically download the file to your device
- The EPUB includes:
  - Book cover
  - Metadata (title, author)
  - All downloaded chapters with formatting
  - Table of contents (TOC)

### 6. **View Daily Limit**

The app respects a daily chapter limit (default: 200 chapters/day):

- Remaining chapters for today shown in the dashboard
- Limit resets at **7:00 AM** daily
- When limit is reached, scraper pauses and resumes tomorrow

---

## How Scraping Works

### **Automatic Schedule** ⭐ NO USER ACTION NEEDED

The app automatically runs a scraping session **every day at 7:00 AM** — **you don't need to do anything!**

Just add books to the queue and the app will:

1. Wait until 7:00 AM (server time)
2. Automatically process books in queue order
3. Download one chapter at a time
4. Respect the daily limit
5. Save progress automatically after each chapter
6. Resume next day if limit is reached

**How it works:**
- The scheduler starts when the app launches
- It calculates time until 7 AM
- At exactly 7 AM, it triggers the scraper automatically
- This repeats every day

### **Manual Trigger** (Optional)

If you want to scrape **right now** instead of waiting for 7 AM:

- Click the **"Run Now"** button on the dashboard
- Immediately starts a scraping session
- Respects daily limits even for manual runs
- Does NOT override the automatic 7 AM schedule

### **What Happens During Scraping**

1. **Fetch book intro** (first time only)
   - Extracts title, author, cover image
   - Gets complete chapter list

2. **Download chapters** one by one
   - Waits 1.5 seconds between chapters (configurable)
   - Removes ads and injected content
   - Saves chapter HTML in cache

3. **Auto-resume**
   - If daily limit is reached mid-book, scraper pauses
   - Tomorrow at 7 AM, it automatically resumes where it left off

### **Pausing & Resuming**

- Books can be manually paused (no direct UI button)
- Paused books resume automatically next scraping session
- Remove books to cancel them permanently

---

## Configuration

Edit **`config.json`** to customize the app behavior:

```json
{
    "MAX_CHAPTERS_PER_DAY": 200,          // Daily chapter limit
    "WAIT_TIME_PER_CHAPTER": 1.5,         // Seconds between chapters
    "EXTRA_WAIT_AFTER_PAGE_LOAD": 23,    // Seconds to wait after page loads
    "BROWSER_HEADLESS": true,             // Use headless browser (recommended)
    "BOOK_CACHE_DIR": "book_cache",       // Where to store chapter cache
    "BOOK_QUEUE_FILE": "books_queue.json",// Queue storage file
    "DAILY_LIMIT_FILE": "daily_limit.json"// Daily limit tracking
}
```

**Tips for Configuration:**
- Increase `WAIT_TIME_PER_CHAPTER` if you get timeouts
- Increase `EXTRA_WAIT_AFTER_PAGE_LOAD` if pages aren't fully loading
- Reduce `MAX_CHAPTERS_PER_DAY` if scraping is too aggressive
- Change waits if scraping fails due to rate limiting

---

## File Structure

```
App/
├── main.py                      # FastAPI backend (do not edit)
├── book_scraper_app.html       # Web UI (do not edit)
├── config.json                 # ⭐ Edit this for settings
├── requirements.txt            # Python dependencies
├── README.md                   # Installation & deployment guide
├── book_cache/                 # 📁 Chapter cache (auto-created)
│   └── *.json                  # Per-book chapter data
├── epubs/                      # 📁 Generated EPUB files
│   └── *.epub                  # Download from here
├── logs/                       # 📁 Scraper logs
│   └── scraper.log            # Check for errors
└── daily_limit.json           # Daily limit tracker (auto-managed)
```

---

## Checking Logs

If something goes wrong:

1. Open **`logs/scraper.log`** to see detailed logs
2. Look for **[ERROR]** lines to find problems
3. Common issues:
   - **Timeout errors**: Increase `EXTRA_WAIT_AFTER_PAGE_LOAD`
   - **Page not found**: Book URL might be incorrect
   - **Playwright errors**: Run `python -m playwright install chromium`

---

## API Endpoints (For Advanced Users)

If you want to integrate with other tools:

```
GET  /api/status                 # Overall status & daily limit
GET  /api/books                  # List all books
POST /api/books                  # Add a book (JSON: {"url": "..."})
GET  /api/books/{slug}           # Get book details
DELETE /api/books/{slug}         # Remove a book
PUT  /api/books/reorder          # Reorder queue
GET  /api/books/{slug}/download  # Download EPUB
POST /api/run-now               # Trigger scraping manually
GET  /api/daily-limit           # Check daily limit
```

---

## Common Workflows

### **Workflow 1: Quick Download**

1. Add a book URL
2. Click "Run Now"
3. Wait for scraping to finish
4. Click "Download EPUB"

### **Workflow 2: Queue Multiple Books**

1. Add multiple book URLs to the queue
2. Arrange them in priority order (drag to reorder)
3. App automatically processes them daily at 7 AM
4. Download EPUBs as they complete

### **Workflow 3: Resume Next Day**

1. Add books to queue
2. Run scraper (it will download some chapters)
3. If daily limit is reached, scraper pauses automatically
4. Next morning at 7 AM, scraper resumes automatically
5. Download EPUB when done

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Book already in queue" | The book URL is already in your queue. Remove it first if you want to add again. |
| EPUB download fails | Ensure at least 1 chapter is downloaded. Check logs for errors. |
| Scraper stops unexpectedly | Check `logs/scraper.log`. Likely timeout or network issue. |
| No chapters downloading | Verify the wikicv.net book URL is correct. Check logs. |
| Browser crashes | Increase `EXTRA_WAIT_AFTER_PAGE_LOAD` in config.json |
| Daily limit not resetting | Check `daily_limit.json`. Should reset at 7 AM server time. |
| EPUB missing chapters | Download again to rebuild. Or check `book_cache/` folder for cached data. |

---

## Tips & Best Practices

✅ **Do:**
- Add books during off-peak hours to avoid rate limiting
- Monitor logs if scraping frequently
- Adjust `WAIT_TIME_PER_CHAPTER` based on site stability
- Back up your `book_cache/` folder regularly
- Download EPUBs periodically to free up disk space

❌ **Don't:**
- Add extremely long books all at once (breaks them into smaller requests)
- Set `MAX_CHAPTERS_PER_DAY` too high (risk of blocking)
- Delete `book_cache/` while scraping is running
- Manually edit JSON files while the app is running

---

## Need Help?

- **Check the logs**: `App/logs/scraper.log`
- **Review config.json**: Ensure settings match your needs
- **Restart the app**: Sometimes fixes transient issues
- **Clear cache**: Delete `App/book_cache/` to start fresh (losing progress)

---

## Technical Support

For deployment or advanced configuration, refer to **README.md** in this folder.
