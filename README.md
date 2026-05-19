# Book Scraper App

FastAPI app for scraping Wikicv books, caching chapters, and building EPUB files on download.

## Install

From the project root:

```bash
cd App
python -m venv venv
```

Activate the environment.

Windows PowerShell:

```powershell
.\venv\Scripts\Activate.ps1
```

Linux/macOS:

```bash
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

On Linux VPS, also install Playwright system dependencies:

```bash
python -m playwright install-deps
```

## Run Locally

From the `App` folder:

```bash
uvicorn main:app --host 127.0.0.1 --port 8765
```

Open:

```text
http://127.0.0.1:8765
```

API status:

```text
http://127.0.0.1:8765/api/status
```

## App Files

```text
main.py                 FastAPI backend
book_scraper_app.html   Web UI
requirements.txt        Python dependencies
config.json             App config
book_cache/             Per-book JSON cache
epubs/                  Generated EPUB files
logs/                   Scraper logs
```

## Download EPUB

The app does not build EPUB automatically after scraping.

EPUB is built when clicking `Download EPUB` in the web UI, or by calling:

```text
GET /api/books/{slug}/download
```

At least one chapter must be downloaded before EPUB can be built.

## VPS Run With Systemd

Example service file:

```ini
[Unit]
Description=Book Scraper FastAPI App
After=network.target

[Service]
User=www-data
Group=www-data
WorkingDirectory=/home/ubuntu/wiki
Environment="PATH=/home/ubuntu/wiki/venv/bin"
ExecStart=/home/ubuntu/wiki/venv/bin/uvicorn main:app --host 127.0.0.1 --port 8765
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable book-scraper
sudo systemctl start book-scraper
sudo systemctl status book-scraper
```

 
Screen multiple terminal for continous running comands example:
```bash
screen -ls
screen -S ollama-chat
screen -r 71695

To detach: Ctrl + A -> Ctrl + D
```



To Start the chromium for fetch 
```bash
 xvfb-run -a python main.py
```


For html file running :
```bash
cd /home/ubuntu/wiki
python3 -m http.server 8888
```
Then to confirm:
```bash
curl http://127.0.0.1:8888
```

## Nginx Reverse Proxy

Use a separate subdomain, for example:

```text
books.example.com
```

Example Nginx config:

```nginx
server {
    listen 80;
    server_name books.example.com;

    location / {
        root /home/ubuntu/wiki;
        index book_scraper_app.html;
        try_files $uri /book_scraper_app.html;
    }

    location /api/ {
        proxy_pass http://127.0.0.1:8765/api/;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300;
    }
}
```

Reload Nginx:

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## Cloudflare

Create an `A` record:

```text
Name: books
Value: VPS public IP
Proxy: Proxied or DNS only
```

Then access:

```text
https://books.example.com
```

