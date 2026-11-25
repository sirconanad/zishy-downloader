#!/usr/bin/env python3
"""
Zishy Downloader (Python)
Downloads an album zip from https://www.zishy.com/galzip/NUMBER,
saves the gallery page HTML + description, extracts the zip into
'<ID> <Title> (<YYYY-MM-DD>)', and downloads the bonus video(s).
Requires a paid subscription (logs in with ZISHY_EMAIL / ZISHY_PASSWORD).

Usage:
    ./zishy.py 2804
    ./zishy.py /path/to/<account-id>2804-marie-gaudin-texas-tittlemouse-1.zip
"""

import argparse
import datetime
import html
import os
import re
import sys
import zipfile
from pathlib import Path
from urllib.parse import unquote

from bs4 import BeautifulSoup
from curl_cffi import requests as crequests

BASE = "https://www.zishy.com"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DIR = SCRIPT_DIR
DEFAULT_COOKIE = os.path.join(SCRIPT_DIR, ".zishy_cookies.txt")

VIDEO_RE = re.compile(r"\.(mp4|mov|webm|m4v)(\?[^\s\"'>]*)?$", re.I)


def _load_dotenv(path: str) -> dict:
    result = {}
    try:
        for line in Path(path).read_text(errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            result[key.strip()] = value.strip().strip("'\"")
    except OSError:
        pass
    return result


DOTENV = _load_dotenv(os.path.join(SCRIPT_DIR, ".env"))


class ZishyError(Exception):
    pass


class Zishy:
    def __init__(self, session_cookie: str, download_dir: str):
        self.session = crequests.Session(impersonate="chrome", timeout=60)
        self.session.headers.update({"User-Agent": USER_AGENT,
                                     "Accept-Language": "en-US,en;q=0.9"})
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.user_id = None
        if session_cookie and Path(session_cookie).exists():
            self._load_cookie_file(session_cookie)

    def _load_cookie_file(self, path: str):
        try:
            for line in Path(path).read_text(errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split("\t")
                if len(parts) < 7:
                    continue
                domain, _include, _path, _secure, _expires, name, value = parts[:7]
                self.session.cookies.set(name, value, domain=domain, path=_path)
            self._derive_user_id()
        except OSError:
            pass

    def _derive_user_id(self):
        cred = (self.session.cookies.get("zishy_credentials_v2", domain="www.zishy.com")
                or self.session.cookies.get("user_credentials", domain="www.zishy.com"))
        if cred:
            m = re.search(r"::(\d+)\s*$", unquote(cred))
            if m:
                self.user_id = m.group(1)

    def save_cookie_file(self, path: str):
        Path(os.path.dirname(path)).mkdir(parents=True, exist_ok=True)
        lines = ["# Netscape HTTP Cookie File"]
        for cookie in self.session.cookies.jar:
            domain = cookie.domain or "www.zishy.com"
            flag = "TRUE" if domain.startswith(".") else "FALSE"
            secure = "TRUE" if cookie.secure else "FALSE"
            expires = str(int(cookie.expires)) if cookie.expires else "0"
            lines.append(f"{domain}\t{flag}\t{cookie.path}\t{secure}\t{expires}\t{cookie.name}\t{cookie.value}")
        Path(path).write_text("\n".join(lines) + "\n")

    def login(self, email: str, password: str):
        login_page = self.session.get(f"{BASE}/login")
        login_page.raise_for_status()
        soup = BeautifulSoup(login_page.text, "lxml")
        token = soup.find("meta", attrs={"name": "csrf-token"})
        if not token:
            raise ZishyError("could not find login form")
        resp = self.session.post(
            f"{BASE}/authenticate",
            data={
                "utf8": "\u2713",
                "authenticity_token": token["content"],
                "user_session[email]": email,
                "user_session[password]": password,
                "commit": "Sign In",
            },
            allow_redirects=True,
        )
        final_path = resp.url.split("?")[0]
        if final_path.rstrip("/").endswith("/login") or "Sign In" in resp.text[:2000]:
            raise ZishyError("login failed: check ZISHY_EMAIL / ZISHY_PASSWORD")
        self._derive_user_id()
        if not self.user_id:
            raise ZishyError("login succeeded but no user id found in cookies")

    def ensure_logged_in(self, email: str, password: str):
        probe = self.session.get(f"{BASE}/galzip/0", allow_redirects=False)
        if probe.status_code in (301, 302) and "/login" in probe.headers.get("Location", ""):
            print("* session expired or missing - logging in")
            self.login(email, password)

    def _strip_user_prefix(self, name: str) -> str:
        if self.user_id and name.startswith(self.user_id):
            name = name[len(self.user_id):]
        return name

    def download_zip(self, gallery: str) -> str:
        print(f"* downloading zip for gallery {gallery}")
        resp = self.session.get(f"{BASE}/galzip/{gallery}", stream=True,
                                headers={"Referer": f"{BASE}/albums"})
        resp.raise_for_status()
        if resp.status_code in (301, 302) or "/login" in resp.url:
            raise ZishyError("zip download requires login")
        cd = resp.headers.get("Content-Disposition", "")
        m = re.search(r'filename\*?=(?:"([^"]+)"|([^;]+))', cd)
        remote_name = m.group(1) or m.group(2) if m else f"{gallery}.zip"
        remote_name = os.path.basename(unquote(remote_name.strip()))
        album = self._strip_user_prefix(Path(remote_name).with_suffix("").name)
        if not album:
            album = gallery
        dest = self.download_dir / f"{album}.zip"
        tmp = dest.with_suffix(".zip.part")
        with open(tmp, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 16):
                fh.write(chunk)
        tmp.rename(dest)
        print(f"* saved {dest.name} ({dest.stat().st_size:,} bytes)")
        return album

    def process_zip(self, zip_path: str) -> str:
        path = Path(zip_path)
        if not path.exists():
            raise ZishyError(f"zip not found: {zip_path}")
        album = self._strip_user_prefix(path.with_suffix("").name)
        if not album:
            album = path.stem
        dest = self.download_dir / f"{album}.zip"
        if path.absolute() != dest.absolute():
            if dest.exists():
                path.unlink()
            else:
                os.replace(path, dest)
        return album

    def fetch_album_page(self, album: str) -> str:
        print(f"* downloading album page {album}")
        resp = self.session.get(f"{BASE}/albums/{album}", headers={"Referer": f"{BASE}/"})
        resp.raise_for_status()
        path = self.download_dir / f"{album}.html"
        path.write_text(resp.text, encoding="utf-8")
        return resp.text

    @staticmethod
    def _extract_intro_stats(soup: BeautifulSoup):
        title = None
        h1 = soup.find("h1")
        if h1:
            title = h1.get_text(strip=True)
        if not title:
            for span in soup.find_all("span"):
                style = (span.get("style") or "").lower()
                if "font-weight:bold" in style and "font-size:40px" in style:
                    title = span.get_text(strip=True)
                    break

        raw_date = None
        p_med = soup.find("p", class_="med")
        if p_med:
            m = re.search(r"([A-Z][a-z]{2})\s+(\d{1,2}),\s*(\d{4})", p_med.get_text())
            if m:
                month = datetime.datetime.strptime(m.group(1), "%b").month
                raw_date = datetime.date(int(m.group(3)), month, int(m.group(2)))
        if not raw_date:
            for span in soup.find_all("span"):
                style = (span.get("style") or "").lower()
                if "font-size:20px" in style:
                    m = re.search(r"([A-Z][a-z]{2})\s+(\d{1,2}),\s*(\d{4})",
                                  span.get_text())
                    if m:
                        month = datetime.datetime.strptime(m.group(1), "%b").month
                        raw_date = datetime.date(int(m.group(3)), month, int(m.group(2)))
                    break

        desc = soup.find("div", id="descrip")
        description = desc.get_text("\n", strip=True) if desc else None
        return title, raw_date, description

    @staticmethod
    def _video_urls(soup: BeautifulSoup) -> list:
        urls = []
        for tag in soup.find_all("source"):
            if tag.get("src"):
                urls.append(tag.get("src"))
        for tag in soup.find_all(["a", "video"], href=True):
            urls.append(tag.get("href"))
        urls = [u for u in urls if u]
        seen, result = set(), []
        for u in urls:
            path = u.split("?")[0].rstrip("/")
            if ("/uploads/files/" in u or "/videos/" in path + "/"
                    or VIDEO_RE.search(u)):
                abs_url = u if u.startswith("http") else BASE + u
                if abs_url not in seen:
                    seen.add(abs_url)
                    result.append(abs_url)
        return result

    def save_metadata(self, album: str, title, raw_date, description):
        if description:
            (self.download_dir / f"{album}.txt").write_text(description + "\n", encoding="utf-8")

    def extract_zip(self, album: str, title, raw_date) -> str:
        zip_path = self.download_dir / f"{album}.zip"
        folder_name = f"{album.split('-')[0] or ''} {html.unescape(title or album)}"
        if raw_date:
            folder_name += f" ({raw_date.isoformat()})"
        target = self.download_dir / folder_name
        if target.exists() and any(target.iterdir()):
            print(f"* target dir already exists, skipping extraction: {target}")
            return str(target)
        print(f"* extracting zip to {folder_name}")
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(target)
        return str(target)

    def _filename_from_response(self, resp, fallback: str) -> str:
        cd = resp.headers.get("Content-Disposition", "")
        m = re.search(r'filename\*?=(?:"([^"]+)"|([^;]+))', cd)
        if m:
            return os.path.basename(unquote((m.group(1) or m.group(2)).strip()))
        return os.path.basename(fallback)

    def download_videos(self, album: str, video_urls: list):
        album_id = album.split("-")[0]
        for url in video_urls:
            print(f"* downloading video {url}")
            resp = self.session.get(url, headers={"Referer": f"{BASE}/albums/{album}"},
                                    stream=True, allow_redirects=True)
            resp.raise_for_status()
            basename = self._filename_from_response(resp, url.split("?")[0])
            dest = self.download_dir / f"{album_id}-{basename}"
            if dest.exists():
                print(f"* video already present, skipping: {dest.name}")
                continue
            with open(dest, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    fh.write(chunk)
            print(f"* saved {dest.name} ({dest.stat().st_size:,} bytes)")


def main():
    ap = argparse.ArgumentParser(description="Zishy gallery downloader")
    ap.add_argument("target", help="gallery number (e.g. 2804) or path to an existing zip")
    ap.add_argument("--email", default=os.environ.get("ZISHY_EMAIL") or DOTENV.get("ZISHY_EMAIL"),
                    help="zishy account email (default: $ZISHY_EMAIL or .env)")
    ap.add_argument("--password", default=os.environ.get("ZISHY_PASSWORD") or DOTENV.get("ZISHY_PASSWORD"),
                    help="zishy account password (default: $ZISHY_PASSWORD or .env)")
    ap.add_argument("--output_dir", default=DEFAULT_DIR,
                    help=f"download directory (default: directory of this script)")
    ap.add_argument("--cookies", default=DEFAULT_COOKIE,
                    help=f"cookie file path (default: {DEFAULT_COOKIE})")
    ap.add_argument("--no-video", action="store_true", help="skip video download")
    args = ap.parse_args()

    if not args.email or not args.password:
        print("ZISHY_EMAIL / ZISHY_PASSWORD (env, .env or --email/--password) are required",
              file=sys.stderr)
        sys.exit(2)

    z = Zishy(args.cookies, args.output_dir)
    try:
        z.ensure_logged_in(args.email, args.password)
    except ZishyError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    z.save_cookie_file(args.cookies)

    target = args.target
    if Path(target).exists() and zipfile.is_zipfile(target):
        album = z.process_zip(target)
    else:
        album = z.download_zip(target)

    content = z.fetch_album_page(album)
    soup = BeautifulSoup(content, "lxml")
    title, raw_date, description = z._extract_intro_stats(soup)
    z.save_metadata(album, title, raw_date, description)

    folder = z.extract_zip(album, title, raw_date)
    print(f"* album: {title or album}")
    print(f"* date: {raw_date.isoformat() if raw_date else 'unknown'}")
    print(f"* extracted to: {folder}")

    if not args.no_video:
        videos = z._video_urls(soup)
        if videos:
            z.download_videos(album, videos)
        else:
            print("* no video found on this album page")

    print("* done")


if __name__ == "__main__":
    main()
