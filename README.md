# X.com Media Downloader

A Python script to download media (images and videos) from X.com (Twitter) user accounts in their original quality.

## Features

- Download all media from a specific X.com user
- Option to start downloading from a specific date
- Downloads media in original quality
- Skips downloading files smaller than 128KB (based on Content-Length header)
- Supports private accounts with auth token
- Checkpoint system: Tracks the last downloaded tweet ID and date per user to efficiently resume downloads
- Command-line interface
- Support for .env file configuration
- Preview media URLs without downloading
- Support for different timeline types (media, tweets, with_replies)
- Option to limit downloads to the N most recent posts
- Organizes downloads into user-specific subdirectories

## Installation

1. Clone this repository
2. Install the required dependencies:
```bash
pip install -r requirements.txt
```

## Usage

Basic usage (fetches all media, resumes from checkpoint if available):
```bash
python x_image_dl.py username
```

Download to a specific directory:
```bash
python x_image_dl.py username --output ./my_downloads
```

Download media from a specific date onwards:
```bash
python x_image_dl.py username --date 2024-01-01
```

Force redownload (ignores checkpoint for fetching, attempts to re-download all files including existing ones):
```bash
python x_image_dl.py username --redownload
```

Download from a private account:
```bash
python x_image_dl.py username --auth-token YOUR_AUTH_TOKEN
```

Preview media URLs without downloading:
```bash
python x_image_dl.py username --preview
```

### Timeline Types

You can specify different timeline types to fetch:

```bash
# Download media timeline (default)
python x_image_dl.py username --timeline media

# Download tweets timeline
python x_image_dl.py username --timeline tweets

# Download timeline with replies
python x_image_dl.py username --timeline with_replies
```

### Limit Number of Posts

You can limit the download to the N most recent posts using `--limit`:

```bash
# Fetch only the latest 100 posts
python x_image_dl.py username --limit 100
```

This fetches the 100 most recent items from the specified timeline and then stops.

You can combine `--limit` with other options:

```bash
# Preview media from the latest 50 posts since 2024-01-01
python x_image_dl.py username --preview --date 2024-01-01 --limit 50

# Download media from the latest 200 posts to a specific directory
python x_image_dl.py username --output ./my_downloads --limit 200
```

### Using .env File

You can store your auth token in a `.env` file to avoid passing it as a command-line argument:

1. Copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

2. Edit `.env` and add your auth token:
```
AUTH_TOKEN=your_auth_token_here
```

The script will automatically use the auth token from the `.env` file if no `--auth-token` argument is provided.

### Getting the Auth Token

To download from private accounts, you'll need an auth token:

1. Log in to X.com in your browser
2. Open Developer Tools (F12)
3. Go to Application > Cookies > twitter.com
4. Find the `auth_token` cookie and copy its value

## Arguments

- `username`: X.com username (without @)
- `--output`, `-o`: Output directory for downloaded media (default: ./downloads)
- `--date`, `-d`: Start date in YYYY-MM-DD format (fetch media from this date onwards)
- `--auth-token`: X.com auth token for private accounts (overrides .env file if provided)
- `--preview`, `-p`: Preview media URLs without downloading
- `--timeline`, `-t`: Timeline type to fetch (choices: media, tweets, with_replies, default: media)
- `--limit`, `-l`: Limit fetching to the N most recent posts. Default 0 fetches all.
- `--redownload`: Ignore checkpoint when fetching metadata and attempt to download all files, even if they exist.

## Notes

- The script uses gallery-dl under the hood.
- Media is saved with filenames in the format: YYYY-MM-DD_tweetID_index.extension.
- Downloads are organized into user-specific subdirectories (e.g., `./downloads/username/`).
- Checkpoint files are stored in the `.checkpoints` directory (relative to where the script is run). Each file (`<username>.json`) contains the `last_downloaded_id`, `last_downloaded_date` (ISO format), and `last_updated_timestamp`.
- The checkpoint file is updated at the end of each run to reflect the latest activity.
- By default, files reported by the server as smaller than 128KB (via Content-Length header) are skipped.
- Retweets and replies are excluded by default when fetching the `media` timeline.
- Command-line auth token takes precedence over .env file.
- Preview mode shows media type (Image/Video) and date for each media item.
- If `--limit` is used with `--date`, the script first fetches the last N posts and then filters them by date. 