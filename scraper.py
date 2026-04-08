import os
import sqlite3
import time
from datetime import datetime
from urllib.parse import urlparse

import requests

DB_NAME = "gofundme.db"
IMAGE_DIR = "images"
GRAPHQL_URL = "https://graphql.gofundme.com/graphql"
REQUEST_INTERVAL = 0.3
REQUEST_TIMEOUT = 30

GRAPHQL_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": "https://www.gofundme.com",
    "Referer": "https://www.gofundme.com/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/146.0.0.0 Safari/537.36"
    ),
    "graphql-client-name": "SSR Frontend Client",
    "graphql-client-version": "1.0.0",
}

GRAPHQL_QUERY = """
query GetFundraiser($slug: ID!) {
  fundraiser(slug: $slug) {
    id
    title
    commentCount
    createdAt
    donationCount
    updateCount
    description(excerpt: false)
    currentAmount {
      amount
      currencyCode
    }
    goalAmount {
      amount
      currencyCode
    }
    donations(last: 20, order: CREATED_AT) {
      edges {
        node {
          id
        }
      }
    }
    fundraiserPhoto {
      url
    }
    fundraiserImageUrl
  }
}
""".strip()


def ensure_tables(cursor):
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

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS campaigns (
            id INTEGER PRIMARY KEY,
            category TEXT,
            title TEXT,
            words_of_support TEXT,
            time TEXT,
            recent_donations TEXT,
            goal TEXT,
            progress TEXT,
            amount TEXT,
            number_of_donations TEXT,
            updates TEXT,
            description TEXT,
            main_picture TEXT
        )
        """
    )


def get_pending_projects(cursor):
    cursor.execute(
        """
        SELECT
            p.id,
            p.category,
            p.url,
            p.image_name,
            c.id AS campaign_id
        FROM projects p
        LEFT JOIN campaigns c
            ON c.id = p.id
        WHERE COALESCE(p.image_name, '') = ''
           OR c.id IS NULL
        ORDER BY p.id
        """
    )
    return cursor.fetchall()


def extract_slug(url):
    parsed = urlparse(url)
    path = parsed.path.strip("/")

    if not path:
        raise ValueError(f"无法从 URL 提取 slug: {url}")

    return path.split("/")[-1]


def fetch_fundraiser(session, slug):
    payload = {
        "operationName": "GetFundraiser",
        "variables": {"slug": slug},
        "query": GRAPHQL_QUERY,
    }

    response = session.post(
        GRAPHQL_URL,
        headers=GRAPHQL_HEADERS,
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()

    payload = response.json()
    errors = payload.get("errors")
    if errors:
        raise ValueError(f"GraphQL 返回 errors: {errors}")

    fundraiser = payload.get("data", {}).get("fundraiser")
    if fundraiser is None:
        raise ValueError("fundraiser 为空")

    return fundraiser


def stringify_number(value):
    if value is None:
        return None

    if isinstance(value, float) and value.is_integer():
        return str(int(value))

    return str(value)


def money_amount_text(money):
    if not money:
        return None

    return stringify_number(money.get("amount"))


def calculate_progress_text(current_money, goal_money):
    if not current_money or not goal_money:
        return None

    current_amount = current_money.get("amount")
    goal_amount = goal_money.get("amount")

    if current_amount is None or goal_amount in (None, 0):
        return None

    progress = float(current_amount) * 100 / float(goal_amount)
    if progress.is_integer():
        return f"{int(progress)}%"

    return f"{progress:.2f}%"


def count_recent_donations(fundraiser):
    donations = fundraiser.get("donations") or {}
    edges = donations.get("edges") or []
    return len(edges)


def pick_image_url(fundraiser):
    fundraiser_photo = fundraiser.get("fundraiserPhoto") or {}
    return fundraiser_photo.get("url") or fundraiser.get("fundraiserImageUrl")


def build_image_name(project_id, image_url, scrape_time):
    extension = os.path.splitext(urlparse(image_url).path)[1].lower()
    if extension not in {".jpg", ".jpeg", ".png", ".webp"}:
        extension = ".jpg"
    return f"{project_id}_{scrape_time}{extension}"


def download_image(session, image_url, project_id, scrape_time):
    response = session.get(image_url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    image_name = build_image_name(project_id, image_url, scrape_time)
    image_path = os.path.join(IMAGE_DIR, image_name)

    with open(image_path, "wb") as file_obj:
        file_obj.write(response.content)

    return image_name


def insert_campaign(cursor, project_id, category, fundraiser):
    cursor.execute(
        """
        INSERT INTO campaigns (
            id,
            category,
            title,
            words_of_support,
            time,
            recent_donations,
            goal,
            progress,
            amount,
            number_of_donations,
            updates,
            description
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            project_id,
            category,
            fundraiser.get("title"),
            stringify_number(fundraiser.get("commentCount")),
            fundraiser.get("createdAt"),
            stringify_number(count_recent_donations(fundraiser)),
            money_amount_text(fundraiser.get("goalAmount")),
            calculate_progress_text(
                fundraiser.get("currentAmount"),
                fundraiser.get("goalAmount"),
            ),
            money_amount_text(fundraiser.get("currentAmount")),
            stringify_number(fundraiser.get("donationCount")),
            stringify_number(fundraiser.get("updateCount")),
            fundraiser.get("description"),
        ),
    )


def update_campaign(cursor, project_id, category, fundraiser):
    cursor.execute(
        """
        UPDATE campaigns
        SET category = ?,
            title = ?,
            words_of_support = ?,
            time = ?,
            recent_donations = ?,
            goal = ?,
            progress = ?,
            amount = ?,
            number_of_donations = ?,
            updates = ?,
            description = ?
        WHERE id = ?
        """,
        (
            category,
            fundraiser.get("title"),
            stringify_number(fundraiser.get("commentCount")),
            fundraiser.get("createdAt"),
            stringify_number(count_recent_donations(fundraiser)),
            money_amount_text(fundraiser.get("goalAmount")),
            calculate_progress_text(
                fundraiser.get("currentAmount"),
                fundraiser.get("goalAmount"),
            ),
            money_amount_text(fundraiser.get("currentAmount")),
            stringify_number(fundraiser.get("donationCount")),
            stringify_number(fundraiser.get("updateCount")),
            fundraiser.get("description"),
            project_id,
        ),
    )


def save_project_snapshot(cursor, project_id, image_name, description, scrape_time):
    cursor.execute(
        """
        UPDATE projects
        SET image_name = ?,
            content = ?,
            scrape_time = ?
        WHERE id = ?
        """,
        (
            image_name,
            description,
            scrape_time,
            project_id,
        ),
    )


def main():
    os.makedirs(IMAGE_DIR, exist_ok=True)

    session = requests.Session()
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    ensure_tables(cursor)
    conn.commit()

    pending_rows = get_pending_projects(cursor)
    print(f"待处理项目数: {len(pending_rows)}")

    inserted_campaigns = 0
    updated_campaigns = 0
    downloaded_images = 0
    failed_projects = 0

    try:
        for project_id, category, url, image_name, campaign_id in pending_rows:
            slug = extract_slug(url)
            scrape_time = datetime.now().strftime("%Y%m%d%H%M%S")

            print(f"处理 {project_id}: {slug}")

            try:
                fundraiser = fetch_fundraiser(session, slug)

                if campaign_id is None:
                    insert_campaign(cursor, project_id, category, fundraiser)
                    inserted_campaigns += 1
                else:
                    update_campaign(cursor, project_id, category, fundraiser)
                    updated_campaigns += 1

                current_image_name = image_name
                if not current_image_name:
                    image_url = pick_image_url(fundraiser)
                    if image_url:
                        try:
                            current_image_name = download_image(
                                session,
                                image_url,
                                project_id,
                                scrape_time,
                            )
                            downloaded_images += 1
                            print(f"  图片已下载: {current_image_name}")
                        except Exception as exc:
                            print(f"  图片下载失败: {exc}")
                    else:
                        print("  未找到图片地址")

                save_project_snapshot(
                    cursor,
                    project_id,
                    current_image_name,
                    fundraiser.get("description"),
                    scrape_time,
                )

                conn.commit()
                print("  已写入数据库")

            except Exception as exc:
                failed_projects += 1
                conn.rollback()
                print(f"  处理失败: {exc}")

            time.sleep(REQUEST_INTERVAL)
    finally:
        session.close()
        conn.close()

    print(
        "完成，"
        f"新增 campaigns {inserted_campaigns} 条，"
        f"更新 campaigns {updated_campaigns} 条，"
        f"下载图片 {downloaded_images} 张，"
        f"失败 {failed_projects} 条"
    )


if __name__ == "__main__":
    main()
