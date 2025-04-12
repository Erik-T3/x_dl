# X Media Downloader

A Python script to download media (images and videos) from X (Twitter) using [gallery_dl](https://github.com/mikf/gallery-dl).

## Features

- Download media from any X username
- Organizes downloads into user-specific subfolder
- Resumes where it left off (checkpoint)
- Optional: limit posts, start from a date, preview media
- Command-line interface


## Installation

1. Clone this repository
2. Install the required dependencies:
```bash
pip install -r requirements.txt
```

This script requires the following Python packages:

- [`gallery_dl`](https://github.com/mikf/gallery-dl) – Media extractor (licensed under [GPLv2](https://www.gnu.org/licenses/old-licenses/gpl-2.0.html))
- [`requests`](https://pypi.org/project/requests/)
- [`python-dotenv`](https://pypi.org/project/python-dotenv/)

## Usage

Basic usage (fetches all media, resumes from checkpoint if available):
```bash
python x_dl.py username
```

Download to a specific directory:
```bash
python x_dl.py username --output ./my_downloads
```

Download media from a specific date onwards:
```bash
python x_dl.py username --date 2025-01-01
```

Force redownload (ignores checkpoint for fetching, attempts to re-download all files including existing ones):
```bash
python x_dl.py username --redownload
```

Download from a private account:
```bash
python x_dl.py username --auth-token YOUR_AUTH_TOKEN
```

Preview media URLs without downloading:
```bash
python x_dl.py username --preview
```

### Limit Number of Posts

You can limit the download to the N most recent posts using `--limit`:

```bash
# Fetch only the latest 100 posts
python x_dl.py username --limit 100
```

This fetches the 100 most recent items from the specified timeline and then stops.

You can combine `--limit` with other options:

```bash
# Preview media from the latest 50 posts since 2024-01-01
python x_dl.py username --preview --date 2024-01-01 --limit 50

# Download media from the latest 200 posts to a specific directory
python x_dl.py username --output ./my_downloads --limit 200
```

## 🔒 Auth Token (Cookie)

You can store your token in a `.env` file instead of passing it every time:

1. Copy the example:
```bash
cp .env.example .env
```

2. Add your token:
```
AUTH_TOKEN=your_token_here
```

How to get your token:
- Log in to X.com
- Open Developer Tools → Application → Cookies → `auth_token`

---

## 🛠️ Options

If you need more control:

```bash
python x_image_dl.py username [options]

**Options:**
- `username`: X username
- `--output`, `-o`: Output directory for downloaded files (default: ./downloads)
- `--date`, `-d`: Start date in YYYY-MM-DD format (from this date onwards)
- `--auth-token`: auth token (overrides .env file if provided)
- `--preview`, `-p`: Preview URLs without downloading (dry-run)
- `--timeline`, `-t`: Timeline type to fetch (choices: media, tweets, with_replies, default: media)
- `--limit`, `-l`: Limit fetching to the N most recent posts. Default 0 fetches all.
- `--redownload`: Ignore checkpoint when fetching metadata and attempt to download all files.

## Notes

- The script uses [gallery_dl](https://github.com/mikf/gallery-dl) under the hood.
- By default, files smaller than 128KB are skipped.
- Command-line auth token takes precedence over .env file.
- If `--limit` is used with `--date`, the script first fetches the last N posts and then filters them by date. 



