import os
import sqlite3

DB_NAME = "gofundme.db"
IMAGE_DIR = "images"


def count_rows(cursor, table_name):
    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
    return cursor.fetchone()[0]


def count_empty_title_campaigns(cursor):
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM campaigns
        WHERE title IS NULL OR TRIM(title) = ''
        """
    )
    return cursor.fetchone()[0]


def count_orphan_projects(cursor):
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM projects
        WHERE id NOT IN (SELECT id FROM campaigns)
        """
    )
    return cursor.fetchone()[0]


def get_referenced_image_names(cursor):
    cursor.execute(
        """
        SELECT image_name
        FROM projects
        WHERE COALESCE(TRIM(image_name), '') <> ''
        """
    )
    return {row[0] for row in cursor.fetchall()}


def get_missing_image_records(cursor, image_dir):
    disk_image_names = get_disk_image_names(image_dir)
    cursor.execute(
        """
        SELECT id, image_name
        FROM projects
        WHERE COALESCE(TRIM(image_name), '') <> ''
        ORDER BY id
        """
    )

    missing_records = []
    for project_id, image_name in cursor.fetchall():
        if image_name not in disk_image_names:
            missing_records.append((project_id, image_name))

    return missing_records


def get_disk_image_names(image_dir):
    if not os.path.isdir(image_dir):
        return set()

    image_names = set()
    for name in os.listdir(image_dir):
        path = os.path.join(image_dir, name)
        if os.path.isfile(path):
            image_names.add(name)
    return image_names


def cleanup_database(cursor):
    cursor.execute(
        """
        DELETE FROM campaigns
        WHERE title IS NULL OR TRIM(title) = ''
        """
    )
    deleted_campaigns = cursor.rowcount

    cursor.execute(
        """
        DELETE FROM projects
        WHERE id NOT IN (SELECT id FROM campaigns)
        """
    )
    deleted_projects = cursor.rowcount

    return deleted_campaigns, deleted_projects


def delete_missing_image_records(cursor, missing_records):
    if not missing_records:
        return 0, 0

    project_ids = [project_id for project_id, _ in missing_records]
    placeholders = ", ".join("?" for _ in project_ids)

    cursor.execute(
        f"""
        DELETE FROM campaigns
        WHERE id IN ({placeholders})
        """,
        project_ids,
    )
    deleted_campaigns = cursor.rowcount

    cursor.execute(
        f"""
        DELETE FROM projects
        WHERE id IN ({placeholders})
        """,
        project_ids,
    )
    deleted_projects = cursor.rowcount

    return deleted_campaigns, deleted_projects


def cleanup_images(image_dir, keep_image_names):
    disk_image_names = get_disk_image_names(image_dir)
    extra_image_names = disk_image_names - keep_image_names
    missing_image_names = keep_image_names - disk_image_names

    deleted_files = 0
    failed_files = []

    for image_name in sorted(extra_image_names):
        image_path = os.path.join(image_dir, image_name)
        try:
            os.remove(image_path)
            deleted_files += 1
        except OSError as exc:
            failed_files.append((image_name, str(exc)))

    return {
        "disk_files_before": len(disk_image_names),
        "disk_files_after": len(disk_image_names) - deleted_files,
        "deleted_files": deleted_files,
        "missing_image_names": sorted(missing_image_names),
        "failed_files": failed_files,
    }


def main():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    before_projects = count_rows(cursor, "projects")
    before_campaigns = count_rows(cursor, "campaigns")
    before_empty_titles = count_empty_title_campaigns(cursor)
    before_orphan_projects = count_orphan_projects(cursor)
    before_missing_image_records = get_missing_image_records(cursor, IMAGE_DIR)

    try:
        deleted_campaigns, deleted_projects = cleanup_database(cursor)
        deleted_missing_campaigns, deleted_missing_projects = (
            delete_missing_image_records(cursor, before_missing_image_records)
        )
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise

    after_projects = count_rows(cursor, "projects")
    after_campaigns = count_rows(cursor, "campaigns")
    keep_image_names = get_referenced_image_names(cursor)
    image_cleanup_result = cleanup_images(IMAGE_DIR, keep_image_names)

    conn.close()

    print(f"campaigns 清理前: {before_campaigns}")
    print(f"projects 清理前: {before_projects}")
    print(f"空 title campaigns: {before_empty_titles}")
    print(f"孤儿 projects: {before_orphan_projects}")
    print(f"缺失图片记录数: {len(before_missing_image_records)}")
    print(f"已删除 campaigns: {deleted_campaigns}")
    print(f"已删除 projects: {deleted_projects}")
    print(f"因缺失图片删除 campaigns: {deleted_missing_campaigns}")
    print(f"因缺失图片删除 projects: {deleted_missing_projects}")
    print(f"campaigns 清理后: {after_campaigns}")
    print(f"projects 清理后: {after_projects}")
    print(f"数据库引用图片数: {len(keep_image_names)}")
    print(f"images 清理前文件数: {image_cleanup_result['disk_files_before']}")
    print(f"已删除图片文件数: {image_cleanup_result['deleted_files']}")
    print(f"images 清理后文件数: {image_cleanup_result['disk_files_after']}")

    missing_image_names = image_cleanup_result["missing_image_names"]
    if missing_image_names:
        print(f"数据库中存在但磁盘缺失的图片: {len(missing_image_names)}")
        for image_name in missing_image_names:
            print(f"  缺失: {image_name}")
    else:
        print("数据库引用图片都存在于 images 目录")

    failed_files = image_cleanup_result["failed_files"]
    if failed_files:
        print(f"删除失败的图片文件: {len(failed_files)}")
        for image_name, error_message in failed_files:
            print(f"  删除失败: {image_name} -> {error_message}")
    else:
        print("图片清理完成，没有删除失败的文件")


if __name__ == "__main__":
    main()
