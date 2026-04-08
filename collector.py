import json
import sqlite3
import time
from urllib.parse import quote, urlencode

import requests

DB_NAME = "gofundme.db"
CATEGORY = "medical"
CATEGORY_ID = 11
CREATED_AFTER = 1759826389
INDEX_NAME = "prod_funds_feed_replica_1"
TARGET_PROJECTS = 6000
HITS_PER_PAGE = 100
REQUEST_INTERVAL = 0.5
USER_TOKEN = "25d5d979-6272-4527-a53d-8e62cdeaf5ba"
API_MAX_RESULTS = 1000

ALGOLIA_URL = (
    "https://e7phe9bb38-dsn.algolia.net/1/indexes/*/queries"
    "?x-algolia-agent=Algolia%20for%20JavaScript%20(4.17.0)"
    "%3B%20Browser%20(lite)"
    "%3B%20instantsearch.js%20(4.90.0)"
    "%3B%20react%20(18.3.1)"
    "%3B%20react-instantsearch%20(7.26.1)"
    "%3B%20react-instantsearch-core%20(7.26.1)"
    "%3B%20next.js%20(14.2.25)"
    "%3B%20JS%20Helper%20(3.28.0)"
    "&x-algolia-api-key=2a43f30c25e7719436f10fed6d788170"
    "&x-algolia-application-id=E7PHE9BB38"
)

HEADERS = {
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Connection": "keep-alive",
    "Origin": "https://www.gofundme.com",
    "Referer": "https://www.gofundme.com/",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0"
    ),
    "content-type": "application/x-www-form-urlencoded",
}

ATTRIBUTES_TO_RETRIEVE = [
    "balance",
    "bene_name",
    "charity_name",
    "country",
    "currencycode",
    "funddescription",
    "fundname",
    "goal_progress",
    "goalamount",
    "last_donation_at",
    "locationtext",
    "objectID",
    "projecttype",
    "thumb_img_url",
    "url",
    "username",
]


def ensure_projects_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY,
            category TEXT,
            url TEXT UNIQUE,
            image_name TEXT,
            content TEXT,
            scrape_time TEXT
        )
        """
    )


def count_projects(cursor):
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM projects
        WHERE category = ?
        """,
        (CATEGORY,),
    )
    return cursor.fetchone()[0]


def build_filters(window_start, window_end):
    return (
        f"((category_id={CATEGORY_ID})) "
        "AND turn_off_donations=0 "
        "AND NOT campaign_tags:greylisted "
        f"AND created_at>{window_start - 1} "
        f"AND created_at<{window_end}"
    )


def build_params(page, window_start, window_end):
    params = {
        "analyticsTags": json.dumps(["page:discover"], separators=(",", ":")),
        "attributesToRetrieve": json.dumps(
            ATTRIBUTES_TO_RETRIEVE,
            separators=(",", ":"),
        ),
        "clickAnalytics": "true",
        "exactOnSingleWordQuery": "word",
        "filters": build_filters(window_start, window_end),
        "highlightPostTag": "__/ais-highlight__",
        "highlightPreTag": "__ais-highlight__",
        "hitsPerPage": str(HITS_PER_PAGE),
        "optionalFacetFilters": "(country:US<score=3>, user_language_locale:en_US<score=2>)",
        "page": str(page),
        "query": "",
        "userToken": USER_TOKEN,
    }
    return urlencode(params, quote_via=quote)


def fetch_page(session, page, window_start, window_end):
    payload = {
        "requests": [
            {
                "indexName": INDEX_NAME,
                "params": build_params(page, window_start, window_end),
            }
        ]
    }

    response = session.post(
        ALGOLIA_URL,
        headers=HEADERS,
        data=json.dumps(payload, separators=(",", ":")),
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    return data["results"][0]


def build_full_url(url_or_slug):
    if url_or_slug.startswith("http://") or url_or_slug.startswith("https://"):
        return url_or_slug
    return f"https://www.gofundme.com/f/{url_or_slug.lstrip('/')}"


def save_projects(cursor, hits, remaining_needed):
    inserted = 0
    skipped = 0

    for hit in hits:
        if remaining_needed is not None and inserted >= remaining_needed:
            break

        project_id = int(hit["objectID"])
        project_url = build_full_url(hit["url"])

        cursor.execute(
            """
            INSERT OR IGNORE INTO projects (id, category, url)
            VALUES (?, ?, ?)
            """,
            (project_id, CATEGORY, project_url),
        )

        if cursor.rowcount == 1:
            inserted += 1
        else:
            skipped += 1

    return inserted, skipped


def split_window(window_start, window_end):
    midpoint = (window_start + window_end) // 2
    if midpoint <= window_start or midpoint >= window_end:
        return None
    return (window_start, midpoint), (midpoint, window_end)


def should_split(result, window_start, window_end):
    nb_hits = result.get("nbHits", 0)
    return nb_hits > API_MAX_RESULTS and (window_end - window_start) > 1


def main():
    session = requests.Session()
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    ensure_projects_table(cursor)
    conn.commit()

    existing_count = count_projects(cursor)
    if existing_count >= TARGET_PROJECTS:
        print(f"{CATEGORY} 已有 {existing_count} 条，无需继续抓取")
        conn.close()
        session.close()
        return

    current_count = existing_count
    total_inserted = 0
    total_skipped = 0
    initial_start = CREATED_AFTER + 1
    initial_end = int(time.time()) + 1
    windows = [(initial_start, initial_end)]

    try:
        while windows and current_count < TARGET_PROJECTS:
            window_start, window_end = windows.pop()
            result = fetch_page(session, 0, window_start, window_end)
            hits = result.get("hits", [])

            if not hits:
                continue

            if should_split(result, window_start, window_end):
                split_result = split_window(window_start, window_end)

                if split_result is not None:
                    older_window, newer_window = split_result
                    windows.append(older_window)
                    windows.append(newer_window)
                    print(
                        f"拆分窗口 {window_start}-{window_end}，"
                        f"约 {result.get('nbHits', 0)} 条"
                    )
                    time.sleep(REQUEST_INTERVAL)
                    continue

                print(
                    f"窗口 {window_start}-{window_end} 无法继续拆分，"
                    "直接抓取当前可访问结果"
                )

            total_pages = result.get("nbPages", 0)
            print(
                f"抓取窗口 {window_start}-{window_end}，"
                f"约 {result.get('nbHits', 0)} 条，{total_pages} 页"
            )

            for page in range(total_pages):
                if current_count >= TARGET_PROJECTS:
                    break

                page_result = result if page == 0 else fetch_page(
                    session,
                    page,
                    window_start,
                    window_end,
                )
                page_hits = page_result.get("hits", [])

                if not page_hits:
                    break

                remaining_needed = TARGET_PROJECTS - current_count
                inserted, skipped = save_projects(cursor, page_hits, remaining_needed)
                conn.commit()

                current_count += inserted
                total_inserted += inserted
                total_skipped += skipped

                print(
                    f"窗口 {window_start}-{window_end} 第 {page + 1} / {total_pages} 页，"
                    f"本页 {len(page_hits)} 条，新增 {inserted} 条，跳过 {skipped} 条，"
                    f"当前 {current_count} / {TARGET_PROJECTS}"
                )

                if current_count >= TARGET_PROJECTS:
                    break

                if page + 1 < total_pages:
                    time.sleep(REQUEST_INTERVAL)
    finally:
        session.close()
        conn.close()

    print(
        f"完成，共新增 {total_inserted} 条，"
        f"跳过 {total_skipped} 条，"
        f"当前总数 {current_count} 条"
    )


if __name__ == "__main__":
    main()
