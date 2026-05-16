"""

Book Scraper Web App - FastAPI Backend

Manages a queue of books to scrape from wikicv.net,

respects daily chapter limits, and auto-schedules at 7AM daily.

"""


import asyncio

import json

import logging

import os

import re

import time

from datetime import datetime, date

from pathlib import Path

from typing import Optional

from urllib.parse import unquote


from pymongo import MongoClient

import requests

import uvicorn

from bs4 import BeautifulSoup

from fastapi import FastAPI, HTTPException, BackgroundTasks

from fastapi.middleware.cors import CORSMiddleware

from fastapi.responses import FileResponse

from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel


# ─────────────────────────────────────────────

# CONFIG

# ─────────────────────────────────────────────

BASE_DIR = Path(__file__).parent

CONFIG_FILE = BASE_DIR / "config.json"


def load_config():

    if CONFIG_FILE.exists():

        with open(CONFIG_FILE, "r") as f:

            return json.load(f)

    return {}


_config = load_config()


BOOK_CACHE_DIR = BASE_DIR / _config.get("BOOK_CACHE_DIR", "book_cache")

EPUB_DIR = BASE_DIR / "epubs"

LOG_DIR = BASE_DIR / "logs"

QUEUE_FILE = BASE_DIR / _config.get("BOOK_QUEUE_FILE", "books_queue.json")

DAILY_LIMIT_FILE = BASE_DIR / _config.get("DAILY_LIMIT_FILE", "daily_limit.json")


BOOK_CACHE_DIR.mkdir(exist_ok=True)

EPUB_DIR.mkdir(exist_ok=True)

LOG_DIR.mkdir(exist_ok=True)


MAX_CHAPTERS_PER_DAY = _config.get("MAX_CHAPTERS_PER_DAY", 50)

WAIT_TIME_PER_CHAPTER = _config.get("WAIT_TIME_PER_CHAPTER", 2)

EXTRA_WAIT_AFTER_PAGE_LOAD = _config.get("EXTRA_WAIT_AFTER_PAGE_LOAD", 2)

BROWSER_HEADLESS = _config.get("BROWSER_HEADLESS", True)


client = MongoClient(_config.get("MONGO_URI"))

db = client['wiki']


logging.basicConfig(

    level=logging.INFO,

    format="%(asctime)s [%(levelname)s] %(message)s",

    handlers=[

        logging.FileHandler(LOG_DIR / "scraper.log", encoding="utf-8"),

        logging.StreamHandler(),

    ],

)

log = logging.getLogger(__name__)


# ─────────────────────────────────────────────

# APP

# ─────────────────────────────────────────────

app = FastAPI(title="Book Scraper API")

app.add_middleware(

    CORSMiddleware,

    allow_origins=["*"],

    allow_methods=["*"],

    allow_headers=["*"],

)


# Global flag to prevent concurrent scraping runs

_scraping_lock = asyncio.Lock()

_scheduler_task: Optional[asyncio.Task] = None


# ─────────────────────────────────────────────

# DATA MODELS

# ─────────────────────────────────────────────

class AddBookRequest(BaseModel):

    url: str


class ReorderRequest(BaseModel):

    ordered_urls: list[str]


# ─────────────────────────────────────────────

# DAILY LIMIT TRACKER

# ─────────────────────────────────────────────

def load_daily_limit() -> dict:

    if DAILY_LIMIT_FILE.exists():

        try:

            with open(DAILY_LIMIT_FILE, "r") as f:

                d = json.load(f)

            if d.get("date") == date.today().isoformat():

                return d

        except Exception:

            pass

    fresh = {"date": date.today().isoformat(), "count": 0, "last_reset": datetime.now().isoformat()}

    save_daily_limit(fresh)

    return fresh


def save_daily_limit(data: dict):

    with open(DAILY_LIMIT_FILE, "w") as f:

        json.dump(data, f, indent=2)


def daily_remaining() -> int:

    d = load_daily_limit()

    return max(0, MAX_CHAPTERS_PER_DAY - d["count"])


def daily_increment():

    d = load_daily_limit()

    d["count"] += 1

    save_daily_limit(d)


# ─────────────────────────────────────────────

# BOOK QUEUE

# ─────────────────────────────────────────────

def load_queue() -> dict:

    if QUEUE_FILE.exists():

        with open(QUEUE_FILE, "r", encoding="utf-8") as f:

            return json.load(f)

    return {"books": []}


def save_queue(data: dict):

    with open(QUEUE_FILE, "w", encoding="utf-8") as f:

        json.dump(data, f, indent=2, ensure_ascii=False)


def queue_books() -> list:

    return load_queue().get("books", [])


def get_book_by_url(url: str) -> Optional[dict]:

    for b in queue_books():

        if b["book_url"] == url:

            return b

    return None


def update_book(url: str, updates: dict):

    q = load_queue()

    for b in q["books"]:

        if b["book_url"] == url:

            b.update(updates)

            break

    save_queue(q)


def add_book_to_queue(url: str):

    q = load_queue()

    # Don't add duplicates

    if any(b["book_url"] == url for b in q["books"]):

        raise ValueError("Book already in queue")

    q["books"].append({

        "book_url": url,

        "status": "queued",  # queued | in_progress | paused | done | error

        "added_at": datetime.now().isoformat(),

        "title": None,

        "author": None,

        "cover_url": None,

        "total_chapters": 0,

        "downloaded_chapters": 0,

        "epub_path": None,

        "error": None,

    })

    save_queue(q)


def remove_book_from_queue(url: str):

    q = load_queue()

    q["books"] = [b for b in q["books"] if b["book_url"] != url]

    save_queue(q)


def reorder_queue(ordered_urls: list[str]):

    q = load_queue()

    url_map = {b["book_url"]: b for b in q["books"]}

    reordered = [url_map[u] for u in ordered_urls if u in url_map]

    # Add any books not in the list at the end

    extras = [b for b in q["books"] if b["book_url"] not in ordered_urls]

    q["books"] = reordered + extras

    save_queue(q)


# ─────────────────────────────────────────────

# BOOK CACHE (per-book JSON in book_cache/)

# ─────────────────────────────────────────────

def slug_from_url(url: str) -> str:

    return url.rstrip("/").split("/")[-1]


def cache_path(url: str) -> Path:

    return BOOK_CACHE_DIR / f"{slug_from_url(url)}.json"


def _chapter_record(chapter: dict, html: str = None, downloaded: bool = False) -> dict:

    return {

        "title": chapter.get("title", ""),

        "url": chapter.get("url", ""),

        "html": html,

        "downloaded": downloaded,

    }


def _downloaded_chapters(chapters: list[dict]) -> list[dict]:

    return [ch for ch in chapters if ch.get("downloaded") and ch.get("html")]


def _downloaded_count(chapters: list[dict]) -> int:

    return sum(1 for ch in chapters if ch.get("downloaded"))


def load_book_cache(url: str) -> dict:

    p = cache_path(url)

    if p.exists():

        with open(p, "r", encoding="utf-8") as f:

            return json.load(f)

    return {

        "url": url,

        "metadata": {},

        "chapters": [],  # [{title, url, html, downloaded}]

    }


def save_book_cache(url: str, data: dict):

    p = cache_path(url)

    with open(p, "w", encoding="utf-8") as f:

        json.dump(data, f, indent=2, ensure_ascii=False)


# ─────────────────────────────────────────────

# BACKUP TO MONGO DB 

# ─────────────────────────────────────────────


def upsert_book_record(book, cache_data):

    log.info(f"Backup book: {book.get('book_url', 'Unknown')}")

    result = db.book_info.update_one({'book_url': book['book_url']}, {'$set': book}, upsert=True)

    if result.upserted_id:

        book_id = result.upserted_id

    else:

        book_id = db.book_info.find_one({'book_url': book['book_url']})['_id']


    db.book_chapters.update_one({'book_id': book_id}, {'$set': cache_data}, upsert=True)

    log.info(f"Updated backup for book {book['title']}: {book_id}")


# ─────────────────────────────────────────────

# CONTENT CLEANER — Remove ads

# ─────────────────────────────────────────────

class ContentCleaner:

    """Removes ads and unwanted elements from chapter content"""


    UNWANTED_STRINGS = [

        "·",

        "dkạhsdsadjdá",

        "oiewơie",

        "✧⋄⋆⋅⋆⋄✧⋄⋆⋅⋆⋄✧ ฅ/ᐠ｡ꞈ｡ᐟ\ฅ Convert by Haruko ฅ/ᐠ｡ꞈ｡ᐟ\ฅ ✧⋄⋆⋅⋆⋄✧⋄⋆⋅⋆⋄✧",

        "☀Truyện được đăng bởi Reine☀"

    ]


    @classmethod

    def clean(cls, content_div) -> str:

        """Extract clean paragraphs and remove ads, scripts, and unwanted elements"""

        if content_div is None:

            return ""

        # Extract clean paragraphs and remove unwanted elements

        paragraphs = content_div.find_all("p")

        clean_html = ""


        for p in paragraphs:

            if not p:

                continue


            para_text = p.get_text(strip=True)

            if not para_text:

                continue


            # Remove unwanted strings from paragraph text          

            pattern = '|'.join(re.escape(s) for s in cls.UNWANTED_STRINGS)

            para_text = re.sub(pattern, '', str(para_text))


            # Only add if text remains after cleaning

            if para_text:

                clean_html += f"<p>{para_text}</p>"

                

        content_div.clear()

        cleaned_soup = BeautifulSoup(clean_html, "html.parser")

        for child in list(cleaned_soup.contents):

            content_div.append(child)

            


        return clean_html


def _fetch_page_sync(url: str) -> BeautifulSoup:

    """Fetch with Playwright in headless mode."""

    

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:

        browser = p.chromium.launch(headless=BROWSER_HEADLESS)

        context = browser.new_context(user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

        page = context.new_page()


        page.goto(url, wait_until="domcontentloaded", timeout=120000)

        time.sleep(EXTRA_WAIT_AFTER_PAGE_LOAD)

        html = page.content()

        if any(keyword in html for keyword in ["Đăng nhập để xem nội dung", "Đã hết lượt truy cập", "Đăng nhập và xác minh email có thêm lượt truy cập"]):

            raise Exception("Access limit hit")

        browser.close()

    return BeautifulSoup(html, "html.parser")



def _get_intro_data_sync(url: str) -> tuple[dict, list]:

    """Extract metadata and chapter list from intro page."""

    soup = _fetch_page_sync(url)


    # Title

    title_tag = soup.find("h2", style=lambda x: x and "font-size: 1.7rem" in x)

    book_title = title_tag.get_text(strip=True) if title_tag else "Unknown"


    # Author

    author = "Không rõ"

    for p in soup.find_all("p"):

        if "tác giả" in p.get_text().lower():

            author = p.get_text().split(":")[-1].strip()

            break


    # Cover URL

    cover_url = None

    img = soup.select_one(".cover-wrapper img, .book-info img[src*='cover']")

    if img:

        cover_url = img.get("src")

        if cover_url and not cover_url.startswith("http"):

            cover_url = "https://wikicv.net" + (cover_url if cover_url.startswith("/") else "/" + cover_url)


    metadata = {

        "book_url": url,

        "title": book_title,

        "author": author,

        "cover_url": cover_url,

        "cover_info": str(soup.select_one(".cover-info")) if soup.select_one(".cover-info") else "",

        "description": str(soup.select_one(".book-desc")) if soup.select_one(".book-desc") else "",

    }


    chapters = []

    v_list = soup.select_one("div.volume-list")

    if v_list:

        for a in v_list.find_all("a", class_="truncate", href=True):

            href = a["href"]

            if href.startswith("/"):

                href = "https://wikicv.net" + href

            chapters.append({"title": a.get_text(strip=True), "url": href})


    return metadata, chapters



def _get_updated_data_sync(url: str) -> tuple[dict, list]:

    """Extract metadata and chapter list from intro page, handling pagination."""

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:

        browser = p.chromium.launch(headless=BROWSER_HEADLESS)

        context = browser.new_context(

            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

        page = context.new_page()

        try:

            page.goto(url, wait_until="domcontentloaded", timeout=120000)

            time.sleep(EXTRA_WAIT_AFTER_PAGE_LOAD)

            html = page.content()

            soup = BeautifulSoup(html, "html.parser")


            # ── Metadata ──────────────────────────────────────────────

            title_tag = soup.find("h2", style=lambda x: x and "font-size: 1.7rem" in x)

            book_title = title_tag.get_text(strip=True) if title_tag else "Unknown"


            author = "Không rõ"

            for p_tag in soup.find_all("p"):

                if "tác giả" in p_tag.get_text().lower():

                    author = p_tag.get_text().split(":")[-1].strip()

                    break


            cover_url = None

            img = soup.select_one(".cover-wrapper img, .book-info img[src*='cover']")

            if img:

                cover_url = img.get("src")

                if cover_url and not cover_url.startswith("http"):

                    cover_url = "https://wikicv.net" + (

                        cover_url if cover_url.startswith("/") else "/" + cover_url)


            metadata = {

                    "book_url": url,

                    "title": book_title,

                    "author": author,

                    "cover_url": cover_url,

                    "cover_info": str(soup.select_one(".cover-info")) if soup.select_one(".cover-info") else "",

                    "description": str(soup.select_one(".book-desc")) if soup.select_one(".book-desc") else "",

            }


            # ── Helper: extract chapters from current DOM ─────────────

            def extract_chapters_from_current_page() -> list:

                current_html = page.content()

                current_soup = BeautifulSoup(current_html, "html.parser")

                v_list = current_soup.select_one("div.volume-list")

                found = []

                if v_list:

                    for a in v_list.find_all("a", class_="truncate", href=True):

                        href = a["href"]

                        if href.startswith("/"):

                            href = "https://wikicv.net" + href

                        found.append({"title": a.get_text(strip=True), "url": href})

                return found


            # ── Collect pagination page buttons ───────────────────────

            pagination_items = soup.select(

                    "ul.pagination li a[data-action='loadBookIndex']"

                )

            # Filter to numbered pages only (skip arrow icons)

            seen_starts = set()

            page_links = []


            for a in pagination_items:

                page_text = a.get_text(strip=True)

                data_start = a.get("data-start")


                if not page_text.isdigit():

                    continue


                if data_start in seen_starts:

                    continue


                seen_starts.add(data_start)

                page_links.append(a)


                # ── Page 1 is already loaded ──────────────────────────────

            chapters = extract_chapters_from_current_page()


            if not page_links or len(page_links) <= 1:

                # No pagination or single page — we already have all chapters

                log.info(f"  No pagination detected. {len(chapters)} chapters found.")

            else:

                log.info(f"  Found {len(page_links)} pagination page(s)")

                # ── Iterate remaining pages ───────────────────────────

                for page_link in page_links[1:]:  # skip page 1 (index 0)

                    page_num = page_link.get_text(strip=True)

                    data_start = page_link.get("data-start")


                    log.info(f"  Loading pagination page {page_num} (start={data_start})...")

                    

                    # remove popup

                    page.evaluate("""

                    () => {

                        document.querySelectorAll(

                            '.fc-consent-root, .fc-dialog-overlay'

                        ).forEach(el => el.remove());

                    }

                    """)


                    page.click(

                            f"ul.pagination li a[data-start='{data_start}'][data-action='loadBookIndex']",

                            timeout=120000

                        )

                    time.sleep(EXTRA_WAIT_AFTER_PAGE_LOAD)


                    page_chapters = extract_chapters_from_current_page()

                    log.info(f"  Page {page_num}: {len(page_chapters)} chapters")

                    chapters.extend(page_chapters)

        finally:

            browser.close()


    # ── Deduplicate by URL while preserving order ─────────────────────────

    seen = set()

    unique_chapters = []

    for ch in chapters:

        if ch["url"] not in seen:

            seen.add(ch["url"])

            unique_chapters.append(ch)


    log.info(f"  Total unique chapters collected: {len(unique_chapters)}")

    return metadata, unique_chapters



def _fetch_chapter_sync(url: str) -> str:

    """Download a chapter and return its HTML content."""

    soup = _fetch_page_sync(url)

    body = soup.select_one("#bookContentBody")

    ContentCleaner.clean(body)

    return str(body) if body else ""


def _make_safe_filename(text: str) -> str:

    return re.sub(r'[\\/:*?"<>|]', '', text).strip()


def _build_epub_sync(book: dict, chapters: list) -> str:

    """Build EPUB and return output path."""

    try:

        from ebooklib import epub as epub_lib


        metadata = book.get("metadata", {})

        book_url = book["book_url"]


        b = epub_lib.EpubBook()

        b.set_identifier(f"wiki-{int(time.time())}")

        b.set_title(metadata.get("title", "Unknown"))

        b.set_language("vi")

        b.add_author(metadata.get("author", "Không rõ"))


        # Cover image

        css_item = None

        if metadata.get("cover_url"):

            try:

                resp = requests.get(metadata["cover_url"], timeout=15)

                if resp.status_code == 200:

                    b.set_cover("cover.jpg", resp.content)

            except Exception as e:

                log.warning(f"Cover download failed: {e}")


        css_content = """

            body { font-family: Georgia, serif; line-height: 1.8; margin: 2em; color: #222; }

            h1, h2 { font-size: 1.4em; margin-top: 2em; color: #444; }

            p { margin: 0.6em 0; text-indent: 1.5em; }

            .bookContentBody { margin: 1em 0; }

        """

        css_item = epub_lib.EpubItem(

            uid="style_main", file_name="style/main.css",

            media_type="text/css", content=css_content,

        )

        b.add_item(css_item)


        # Cover page

        cover_page = epub_lib.EpubHtml(title="Bìa sách", file_name="cover_page.xhtml", lang="vi")

        cover_page.content = f"""<html><head><link rel="stylesheet" href="style/main.css"/></head>

        <body>

          <div style="text-align:center;margin:2em 0;">

            <h1>{metadata.get('title','')}</h1>

            <img src="cover.jpg" alt="Cover" style="max-width:100%;height:auto;"/>

            <p><a href="{book_url}">{book_url}</a></p>

          </div>

          {metadata.get('cover_info','')}

          {metadata.get('description','')}

        </body></html>"""

        cover_page.add_item(css_item)

        b.add_item(cover_page)


        epub_chapters = []

        spine = ["nav", cover_page]


        for idx, ch in enumerate(chapters):

            if not ch.get("html"):

                continue

            ec = epub_lib.EpubHtml(

                title=ch["title"],

                file_name=f"chap_{idx+1:04d}.xhtml",

                lang="vi",

            )

            ec.content = f"<html><head><link rel='stylesheet' href='style/main.css'/></head><body>{ch['html']}</body></html>"

            ec.add_item(css_item)

            b.add_item(ec)

            epub_chapters.append(ec)

            spine.append(ec)


        b.toc = [cover_page] + epub_chapters

        b.spine = spine

        b.add_item(epub_lib.EpubNcx())

        b.add_item(epub_lib.EpubNav())


        safe_name = _make_safe_filename(metadata.get("title", "book"))

        out_path = str(EPUB_DIR / f"{safe_name}.epub")

        epub_lib.write_epub(out_path, b, {})

        log.info(f"EPUB saved: {out_path}")

        return out_path

    except Exception as e:

        log.error(f"EPUB build error: {e}")

        raise


# ─────────────────────────────────────────────

# MAIN SCRAPING ORCHESTRATOR

# ─────────────────────────────────────────────

async def run_scraping_session():

    """

    Process books in queue order, respecting daily chapter limit.

    Saves progress after each chapter so it can resume tomorrow.

    """

    if _scraping_lock.locked():

        log.info("Scraping session already running, skipping.")

        return


    async with _scraping_lock:

        log.info("=== Starting scraping session ===")

        loop = asyncio.get_event_loop()


        books = queue_books()

        pending = [b for b in books if b["status"] not in ("done", "cancelled")]


        for book in pending:

            url = book["book_url"]

            remaining = daily_remaining()

            if remaining <= 0:

                log.info(f"Daily limit reached. Stopping. Books remaining: {len(pending)}")

                # Mark in-progress as paused

                if book["status"] == "in_progress":

                    update_book(url, {"status": "paused"})

                break


            log.info(f"Processing book: {url} (remaining limit: {remaining})")

            update_book(url, {"status": "in_progress", "error": None})


            try:

                # Load or initialize cache

                cache = load_book_cache(url)


                # Fetch intro if we don't have chapters yet

                if not cache.get("chapters"):

                    log.info(f"  Fetching intro page...")

                    metadata, chapter_list = await loop.run_in_executor(

                        None, _get_intro_data_sync, url

                    )

                    cache["metadata"] = metadata

                    cache["chapters"] = [_chapter_record(ch) for ch in chapter_list]

                    save_book_cache(url, cache)


                    update_book(url, {

                        "title": metadata.get("title"),

                        "author": metadata.get("author"),

                        "cover_url": metadata.get("cover_url"),

                        "total_chapters": len(chapter_list),

                    })


                chapters = cache["chapters"]

                downloaded_count = _downloaded_count(chapters)

                pending_chapters = [ch for ch in chapters if not ch.get("downloaded")]


                log.info(f"  Total: {len(chapters)} | Downloaded: {downloaded_count} | Pending: {len(pending_chapters)}")


                for ch in pending_chapters:

                    if daily_remaining() <= 0:

                        log.info(f"  Daily limit hit mid-book. Progress saved.")

                        update_book(url, {

                            "status": "paused",

                            "downloaded_chapters": _downloaded_count(cache["chapters"]),

                        })

                        break


                    title = ch.get("title") or "(untitled chapter)"

                    chapter_url = ch.get("url")

                    if not chapter_url:

                        log.warning(f"  Skipping malformed chapter entry: {ch}")

                        continue


                    log.info(f"  Downloading: {title}")

                    html = await loop.run_in_executor(None, _fetch_chapter_sync, chapter_url)


                    # Check if content requires login

                    if any(keyword in html for keyword in ["Đăng nhập để xem nội dung", "Đã hết lượt truy cập", "Đăng nhập và xác minh email có thêm lượt truy cập"]):

                        error_msg = "Book requires login to view content"

                        log.error(f"  {error_msg}")

                        update_book(url, {

                            "status": "error",

                            "error": error_msg,

                            "downloaded_chapters": _downloaded_count(cache["chapters"]),

                        })

                        break


                    ch["html"] = html

                    ch["downloaded"] = True


                    save_book_cache(url, cache)

                    daily_increment()


                    update_book(url, {"downloaded_chapters": _downloaded_count(cache["chapters"])})

                    await asyncio.sleep(WAIT_TIME_PER_CHAPTER)


                # EPUB is built on demand by the download endpoint.

                downloaded_count = _downloaded_count(cache["chapters"])

                if downloaded_count:

                    is_complete = all(ch.get("downloaded") for ch in cache["chapters"])

                    update_book(url, {

                        "status": "done" if is_complete else "paused",

                        "downloaded_chapters": downloaded_count,

                    })

                else:

                    update_book(url, {"downloaded_chapters": 0})


            except Exception as e:

                log.error(f"Error processing {url}: {e}")

                update_book(url, {"status": "error", "error": str(e)})

                

            upsert_book_record(book, cache)


        log.info("=== Scraping session complete ===")


# ─────────────────────────────────────────────

# SCHEDULER — fires at 7:00 AM daily

# ─────────────────────────────────────────────

async def scheduler_loop():

    """Runs indefinitely, triggering a scrape session at 7AM each day."""

    log.info("Scheduler started.")

    while True:

        now = datetime.now()

        # Next 7:00 AM

        next_run = now.replace(hour=7, minute=0, second=0, microsecond=0)

        if now >= next_run:

            next_run = next_run.replace(day=next_run.day + 1)

        wait_seconds = (next_run - now).total_seconds()

        log.info(f"Next scheduled run at {next_run.isoformat()} (in {wait_seconds/3600:.1f}h)")

        await asyncio.sleep(wait_seconds)

        await run_scraping_session()


@app.on_event("startup")

async def startup():

    global _scheduler_task

    _scheduler_task = asyncio.create_task(scheduler_loop())

    log.info("App started. Scheduler running.")


# ─────────────────────────────────────────────

# API ROUTES

# ─────────────────────────────────────────────


@app.get("/api/status")

def get_status():

    """Overall status: queue summary + daily limit info."""

    books = queue_books()

    dl = load_daily_limit()

    return {

        "daily": {

            "date": dl["date"],

            "used": dl["count"],

            "limit": MAX_CHAPTERS_PER_DAY,

            "remaining": daily_remaining(),

        },

        "queue_summary": {

            "total": len(books),

            "queued": sum(1 for b in books if b["status"] == "queued"),

            "in_progress": sum(1 for b in books if b["status"] == "in_progress"),

            "paused": sum(1 for b in books if b["status"] == "paused"),

            "done": sum(1 for b in books if b["status"] == "done"),

            "error": sum(1 for b in books if b["status"] == "error"),

        },

        "is_scraping": _scraping_lock.locked(),

    }


@app.get("/api/books")

def get_books():

    """Return full book queue with status."""

    return {"books": queue_books()}


@app.post("/api/books")

def add_book(req: AddBookRequest):

    """Add a book URL to the download queue."""

    url = req.url.strip()

    if not url.startswith("http"):

        raise HTTPException(400, "Invalid URL")

    try:

        add_book_to_queue(url)

    except ValueError as e:

        raise HTTPException(409, str(e))

    return {"ok": True, "url": url}


@app.delete("/api/books/{slug}")

def cancel_book(slug: str):

    """Remove a book from the queue."""

    books = queue_books()

    target = next((b for b in books if unquote(slug_from_url(b["book_url"])) == slug), None)

    if not target:

        raise HTTPException(404, "Book not found")

    remove_book_from_queue(target["book_url"])

    return {"ok": True}


@app.put("/api/books/reorder")

def reorder_books(req: ReorderRequest):

    """Reorder the queue by providing an ordered list of URLs."""

    reorder_queue(req.ordered_urls)

    return {"ok": True}


@app.get("/api/books/{slug}")

def get_book_detail(slug: str):

    """Get detailed info for a single book including cached chapter list."""

    books = queue_books()

    book = next((b for b in books if unquote(slug_from_url(b["book_url"])) == slug), None)

    if not book:

        raise HTTPException(404, "Book not found")


    cache = load_book_cache(book["book_url"])


    return {

        **book,

        "chapters": cache.get("chapters", []),

        "metadata": cache.get("metadata", {}),

    }


@app.get("/api/books/{slug}/refresh-chapters")

def refresh_chapters(slug: str):

    """Refresh the chapter list for a book by re-fetching the intro page."""

    books = queue_books()

    book = next((b for b in books if unquote(slug_from_url(b["book_url"])) == slug), None)

    if not book:

        raise HTTPException(404, "Book not found")


    cache = load_book_cache(book["book_url"])


    try:

        # Call sync function directly

        metadata, chapter_list = _get_updated_data_sync(book["book_url"])


        # Preserve already-downloaded chapters

        old_chapters_map = {ch["url"]: ch for ch in cache.get("chapters", [])}

        new_chapters = []


        for ch in chapter_list:

            if ch["url"] in old_chapters_map:

                # Keep existing chapter with its HTML and downloaded status

                existing = old_chapters_map[ch["url"]]

                existing["title"] = ch.get("title")  # Update title in case it changed

                new_chapters.append(existing)

            else:

                # New chapter, add it

                new_chapters.append(_chapter_record(ch))


        cache["metadata"] = metadata

        cache["chapters"] = new_chapters

        save_book_cache(book["book_url"], cache)

        

        total = len(new_chapters)

        downloaded = sum(ch.get("downloaded") for ch in new_chapters)

        status = "done" if downloaded == total and total > 0 else "paused" if downloaded > 0 else "queued"


        update_book(book["book_url"], {

            "title": metadata.get("title"),

            "author": metadata.get("author"),

            "cover_url": metadata.get("cover_url"),

            "total_chapters": len(new_chapters),

            "status": status

        })


        new_count = len([ch for ch in new_chapters if not ch.get("downloaded")])

        return {

            "ok": True,

            "message": f"Chapter list updated: {len(new_chapters)} total, {new_count} new chapters",

            "total_chapters": len(new_chapters),

            "new_chapters": new_count,

        }

    except Exception as e:

        log.error(f"Error refreshing chapters for {book['book_url']}: {e}")

        raise HTTPException(500, f"Failed to refresh chapters: {str(e)}")


@app.get("/api/books/{slug}/download")

def download_epub(slug: str):

    """Build and download the EPUB file for a completed or partially completed book."""

    books = queue_books()

    book = next((b for b in books if unquote(slug_from_url(b["book_url"])) == slug), None)

    if not book:

        raise HTTPException(404, "Book not found")


    cache = load_book_cache(book["book_url"])

    downloaded_chapters = _downloaded_chapters(cache.get("chapters", []))

    if not downloaded_chapters:

        raise HTTPException(400, "No downloaded chapters to build EPUB")


    epub_path = _build_epub_sync(

        {"book_url": book["book_url"], "metadata": cache.get("metadata", {})},

        downloaded_chapters,

    )

    update_book(book["book_url"], {

        "epub_path": epub_path,

        "downloaded_chapters": _downloaded_count(cache.get("chapters", [])),

    })


    path = Path(epub_path)

    if not path.exists():

        raise HTTPException(404, "EPUB file missing")

    return FileResponse(str(path), media_type="application/epub+zip", filename=path.name)


@app.post("/api/run-now")

async def trigger_now(background_tasks: BackgroundTasks):

    """Manually trigger a scraping session immediately."""

    if _scraping_lock.locked():

        return {"ok": False, "message": "Already running"}

    background_tasks.add_task(run_scraping_session)

    return {"ok": True, "message": "Scraping session started"}


@app.get("/api/daily-limit")

def get_daily_limit():

    dl = load_daily_limit()

    return {

        "date": dl["date"],

        "used": dl["count"],

        "limit": MAX_CHAPTERS_PER_DAY,

        "remaining": daily_remaining(),

    }


if __name__ == "__main__":

    uvicorn.run("main:app", host="0.0.0.0", port=8765, reload=False)
