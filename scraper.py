import argparse
import asyncio
import os
import re
import sqlite3
from datetime import datetime
from html import unescape
from urllib.parse import urlparse

import httpx

DB_NAME = "gofundme.db"
IMAGE_DIR = "images"
GRAPHQL_URL = "https://graphql.gofundme.com/graphql"
REQUEST_TIMEOUT = 30
DEFAULT_CONCURRENCY = 5

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


def parse_args():
    parser = argparse.ArgumentParser(description="抓取 GoFundMe 项目详情")
    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help=f"并发数，默认 {DEFAULT_CONCURRENCY}",
    )
    args = parser.parse_args()

    if args.concurrency < 1:
        parser.error("--concurrency 必须大于等于 1")

    return args


async def fetch_fundraiser(client, slug):
    payload = {
        "operationName": "GetFundraiser",
        "variables": {"slug": slug},
        "query": GRAPHQL_QUERY,
    }

    response = await client.post(
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


def html_to_text(html_text):
    if html_text is None:
        return None

    text = re.sub(r"(?i)<br\s*/?>", "\n", html_text)
    text = re.sub(r"(?i)</(div|p|li|h[1-6])\s*>", "\n", text)
    text = re.sub(r"(?i)<li\s*>", "- ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = unescape(text).replace("\xa0", " ")
    text = text.replace("\r", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def pick_image_url(fundraiser):
    fundraiser_photo = fundraiser.get("fundraiserPhoto") or {}
    return fundraiser_photo.get("url") or fundraiser.get("fundraiserImageUrl")


def build_image_name(project_id, image_url, scrape_time):
    extension = os.path.splitext(urlparse(image_url).path)[1].lower()
    if extension not in {".jpg", ".jpeg", ".png", ".webp"}:
        extension = ".jpg"
    return f"{project_id}_{scrape_time}{extension}"


async def download_image(client, image_url, project_id, scrape_time):
    response = await client.get(image_url, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    image_name = build_image_name(project_id, image_url, scrape_time)
    image_path = os.path.join(IMAGE_DIR, image_name)

    with open(image_path, "wb") as file_obj:
        file_obj.write(response.content)

    return image_name


def insert_campaign(cursor, project_id, category, fundraiser, description_text):
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
            description_text,
        ),
    )


def update_campaign(cursor, project_id, category, fundraiser, description_text):
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
            description_text,
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


async def process_project(client, semaphore, row):
    project_id, category, url, image_name, campaign_id = row
    scrape_time = datetime.now().strftime("%Y%m%d%H%M%S")

    try:
        slug = extract_slug(url)
        print(f"处理 {project_id}: {slug}")

        async with semaphore:
            fundraiser = await fetch_fundraiser(client, slug)
            description_text = html_to_text(fundraiser.get("description"))

            current_image_name = image_name
            image_download_error = None
            image_downloaded = False

            if not current_image_name:
                image_url = pick_image_url(fundraiser)
                if image_url:
                    try:
                        current_image_name = await download_image(
                            client,
                            image_url,
                            project_id,
                            scrape_time,
                        )
                        image_downloaded = True
                    except Exception as exc:
                        image_download_error = f"图片下载失败: {exc}"
                else:
                    image_download_error = "未找到图片地址"

            return {
                "project_id": project_id,
                "category": category,
                "campaign_id": campaign_id,
                "fundraiser": fundraiser,
                "description_text": description_text,
                "image_name": current_image_name,
                "scrape_time": scrape_time,
                "image_downloaded": image_downloaded,
                "image_download_error": image_download_error,
                "error": None,
            }
    except Exception as exc:
        return {
            "project_id": project_id,
            "category": category,
            "campaign_id": campaign_id,
            "fundraiser": None,
            "description_text": None,
            "image_name": image_name,
            "scrape_time": scrape_time,
            "image_downloaded": False,
            "image_download_error": None,
            "error": str(exc),
        }


async def async_main(concurrency):
    os.makedirs(IMAGE_DIR, exist_ok=True)

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
        semaphore = asyncio.Semaphore(concurrency)
        limits = httpx.Limits(
            max_connections=concurrency,
            max_keepalive_connections=concurrency,
        )

        async with httpx.AsyncClient(
            follow_redirects=True,
            limits=limits,
        ) as client:
            tasks = [
                asyncio.create_task(process_project(client, semaphore, row))
                for row in pending_rows
            ]

            for task in asyncio.as_completed(tasks):
                result = await task
                project_id = result["project_id"]

                if result["error"]:
                    failed_projects += 1
                    print(f"{project_id} 处理失败: {result['error']}")
                    continue

                try:
                    if result["campaign_id"] is None:
                        insert_campaign(
                            cursor,
                            project_id,
                            result["category"],
                            result["fundraiser"],
                            result["description_text"],
                        )
                        inserted_campaigns += 1
                    else:
                        update_campaign(
                            cursor,
                            project_id,
                            result["category"],
                            result["fundraiser"],
                            result["description_text"],
                        )
                        updated_campaigns += 1

                    if result["image_downloaded"]:
                        downloaded_images += 1
                        print(f"  图片已下载: {result['image_name']}")
                    elif result["image_download_error"]:
                        print(f"  {result['image_download_error']}")

                    save_project_snapshot(
                        cursor,
                        project_id,
                        result["image_name"],
                        result["description_text"],
                        result["scrape_time"],
                    )

                    conn.commit()
                    print(f"  已写入数据库: {project_id}")
                except Exception as exc:
                    failed_projects += 1
                    conn.rollback()
                    print(f"{project_id} 写入失败: {exc}")
    finally:
        conn.close()

    print(
        "完成，"
        f"新增 campaigns {inserted_campaigns} 条，"
        f"更新 campaigns {updated_campaigns} 条，"
        f"下载图片 {downloaded_images} 张，"
        f"失败 {failed_projects} 条"
    )


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(async_main(args.concurrency))
