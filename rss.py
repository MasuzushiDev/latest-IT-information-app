"""RSS/Atom フィードの取得と、記事データへの整形を担当するモジュール。"""

import hashlib
import json
import logging
import re
import urllib.request
from datetime import datetime, timedelta, timezone
from html import unescape
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser

logger = logging.getLogger(__name__)

JST = timezone(timedelta(hours=9))
USER_AGENT = "Mozilla/5.0 (compatible; PersonalAINewsBot/0.1)"
TIMEOUT_SEC = 15          # 1フィードあたりの通信タイムアウト
MAX_ITEMS_PER_FEED = 30   # 1フィードから取り込む最大件数
MAX_DESC_LEN = 200        # フィード付属の概要文を切り詰める長さ

_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"\s+")


def load_feeds(path="feeds.json"):
    """feeds.json を読み込み、enabled が true のフィードだけ返す。"""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    return [feed for feed in data.get("feeds", []) if feed.get("enabled", True)]


def _download(url):
    """フィードを取得して bytes で返す（タイムアウトとUser-Agent付き）。"""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as res:
        return res.read()


def _clean_text(raw, max_len=None):
    """HTMLタグを除去し、空白を整え、必要なら max_len で切り詰める。"""
    text = unescape(_TAG_RE.sub(" ", raw or ""))
    text = _SPACE_RE.sub(" ", text).strip()
    if max_len and len(text) > max_len:
        text = text[:max_len].rstrip() + "…"
    return text


def normalize_url(url):
    """重複判定を安定させるため、追跡用パラメータ(utm_*)とフラグメントを除去する。"""
    parts = urlsplit(url.strip())
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_")
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


def _parse_date(entry):
    """記事の公開日時を JST の ISO 8601 文字列で返す。取得できなければ None。"""
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            dt = datetime(*t[:6], tzinfo=timezone.utc)
            return dt.astimezone(JST).isoformat(timespec="seconds")
    return None


def fetch_feed(feed):
    """1つのフィードから記事のリストを取得する。失敗時は空リストを返す。"""
    name, url = feed["name"], feed["url"]
    try:
        parsed = feedparser.parse(_download(url))
    except Exception as e:  # 通信エラー等。1件の失敗で全体を止めない
        logger.warning("取得失敗: %s (%s): %s", name, url, e)
        return []

    if parsed.bozo and not parsed.entries:
        logger.warning("解析失敗: %s (%s): %s", name, url, parsed.get("bozo_exception"))
        return []

    articles = []
    for entry in parsed.entries[:MAX_ITEMS_PER_FEED]:
        link = entry.get("link")
        title = _clean_text(entry.get("title"))
        if not link or not title:
            continue
        link = normalize_url(link)
        articles.append(
            {
                "id": hashlib.sha1(link.encode("utf-8")).hexdigest()[:12],
                "title": title,
                "url": link,
                "source": name,
                "category": feed.get("category", ""),
                "published": _parse_date(entry),
                "description": _clean_text(entry.get("summary"), MAX_DESC_LEN),
            }
        )
    logger.info("%s: %d件", name, len(articles))
    return articles


def fetch_all(feeds):
    """全フィードから記事を取得し、1つのリストにまとめて返す。"""
    articles = []
    for feed in feeds:
        articles.extend(fetch_feed(feed))
    return articles


if __name__ == "__main__":
    # 単体確認用: python rss.py
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    feeds = load_feeds(Path(__file__).with_name("feeds.json"))
    result = fetch_all(feeds)
    print(f"合計 {len(result)} 件")
    for a in result[:5]:
        print(f'{a["published"]} | {a["source"]} | {a["title"]}\n  {a["url"]}')