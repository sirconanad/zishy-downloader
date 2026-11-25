# zishy-downloader

Python downloader for paid Zishy (https://www.zishy.com) galleries.

Downloads the gallery zip from `https://www.zishy.com/galzip/NUMBER`, saves the
album page and its description, extracts the photos into a dated folder, and
downloads the bonus video when present.

Works against Zishy's current Cloud frontend (Akamai Connected Cloud) by
impersonating a real browser TLS/HTTP2 fingerprint, and logs in fresh with your
account instead of relying on stale cookie files.

## Requirements

- Python 3.8+
- [curl_cffi](https://github.com/lexiforest/curl_cffi) (browser TLS impersonation)
- [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) + lxml
- A paid Zishy subscription

## Installation

```bash
git clone git@github.com:sirconanad/zishy-downloader.git
cd zishy-downloader
python3 -m pip install --upgrade curl_cffi beautifulsoup4 lxml
```

## Configuration

Create a `.env` file in the script directory with your login:

```bash
ZISHY_EMAIL=you@example.com
ZISHY_PASSWORD=your-password
```

`.env` is git-ignored and never committed. Alternatively, export the same
variables in your environment or pass `--email` / `--password` on the command
line.

## Usage

By gallery number (downloads the zip first):

```bash
./zishy.py 2804
```

From an already-downloaded zip file:

```bash
./zishy.py ./<account-id>2804-marie-gaudin-texas-tittlemouse-1.zip
```

### Options

| Option | Description |
| ------ | ----------- |
| `--email` / `--password` | Override credentials (default: `$ZISHY_EMAIL` / `$ZISHY_PASSWORD` or `.env`) |
| `--output_dir DIR` | Download directory (default: script directory) |
| `--cookies FILE` | Cookie file path (default: `.zishy_cookies.txt` next to the script) |
| `--no-video` | Skip bonus video download |

## Output

For gallery `2804`, the script produces:

```
2804 Marie Gaudin Texas Tittlemouse 1 (2026-11-23)/   # extracted photos
2804-marie-gaudin-texas-tittlemouse-1.html            # album page
2804-marie-gaudin-texas-tittlemouse-1.txt             # description
2804-marie-gaudin-texas-tittlemouse-1.zip             # gallery archive
```

If the gallery has a bonus video, it is saved as `<album-id>-<basename>.mp4`
(for example `2800-jamila_sedano_pastel.mp4`).

The account-id prefix on downloaded zip files is stripped automatically. The
session is saved to the cookie file and reused; if the session expires, the
script logs in again automatically.
