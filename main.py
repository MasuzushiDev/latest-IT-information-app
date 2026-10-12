"""RSSから記事を集め、日付ごとのJSONに保存して index.json を更新する。

実行: python main.py

出力:
  storage/YYYY-MM-DD.json  その日(JST)に取得した記事
  storage/index.json       保存済みの日付一覧（ブラウザが最初に読む）
"""

import json
import logging
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path

from rss import JST, fetch_all, load_feeds

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
FEEDS_PATH = BASE_DIR / "feeds.json"
STORAGE_DIR = BASE_DIR / "storage"
INDEX_NAME = "index.json"

MAX_AGE_DAYS = 7   # 公開からこの日数を超えた記事は取り込まない
DEDUP_DAYS = 30    # 重複判定のために読み込む過去日数（MAX_AGE_DAYS 以上にすること）

assert DEDUP_DAYS >= MAX_AGE_DAYS

_DATE_FILE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.json$")


# ---------- JSONの読み書き ----------

def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _write_json(path, data):
    """途中で失敗しても壊れたファイルが残らないよう、一時ファイル経由で書き込む。"""
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))  # 容量削減のため圧縮形式
    os.replace(tmp, path)


# ---------- storage の操作 ----------

def list_dates():
    """storage にある日付(YYYY-MM-DD)を新しい順で返す。"""
    return sorted(
        (p.stem for p in STORAGE_DIR.glob("*.json") if _DATE_FILE_RE.match(p.name)),
        reverse=True,
    )


def load_day(date_str):
    return _read_json(STORAGE_DIR / f"{date_str}.json")


def collect_known_ids(today):
    """直近 DEDUP_DAYS 日分の保存済み記事IDを集める。"""
    ids = set()
    for date_str in list_dates():
        if (today - date.fromisoformat(date_str)).days > DEDUP_DAYS:
            break  # 新しい順なので、以降はすべて範囲外
        ids.update(a["id"] for a in load_day(date_str)["articles"])
    return ids


def save_day(date_str, new_articles, now):
    """その日のJSONに記事を追加して保存する（同日に複数回実行しても追記される）。"""
    path = STORAGE_DIR / f"{date_str}.json"
    articles = list(new_articles)
    if path.exists():
        articles += _read_json(path)["articles"]
    # published は全てJST形式なので文字列のまま新しい順に並べられる（日付なしは末尾）
    articles.sort(key=lambda a: a["published"] or "", reverse=True)
    _write_json(path, {"updated": now.isoformat(timespec="seconds"), "articles": articles})


def update_index(now):
    """storage の実ファイルから日付一覧を作り直す。内容が変わらなければ書き込まない。"""
    dates = list_dates()
    path = STORAGE_DIR / INDEX_NAME
    if path.exists() and _read_json(path).get("dates") == dates:
        return
    _write_json(path, {"updated": now.isoformat(timespec="seconds"), "dates": dates})
    logger.info("index.json を更新（%d日分）", len(dates))


# ---------- 記事の絞り込み ----------

def filter_fresh(articles, now):
    """公開日が MAX_AGE_DAYS より古い記事を除く（公開日が不明な記事は残す）。"""
    limit = now - timedelta(days=MAX_AGE_DAYS)
    return [
        a for a in articles
        if not a["published"] or datetime.fromisoformat(a["published"]) >= limit
    ]


def remove_duplicates(articles, known_ids):
    """保存済み記事、および今回取得分の中での重複を除く（先に出た方を残す）。"""
    seen = set(known_ids)
    unique = []
    for a in articles:
        if a["id"] in seen:
            continue
        seen.add(a["id"])
        unique.append(a)
    return unique


# ---------- メイン処理 ----------

def main(now=None):
    now = now or datetime.now(JST)
    today = now.date()
    STORAGE_DIR.mkdir(exist_ok=True)

    fetched = fetch_all(load_feeds(FEEDS_PATH))
    fresh = filter_fresh(fetched, now)
    new_articles = remove_duplicates(fresh, collect_known_ids(today))
    logger.info(
        "取得 %d件 → 期間内 %d件 → 新規 %d件", len(fetched), len(fresh), len(new_articles)
    )

    if new_articles:
        save_day(today.isoformat(), new_articles, now)
    update_index(now)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    main()