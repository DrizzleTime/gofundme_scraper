import os
import sqlite3
import cv2
import mediapipe as mp

DB_NAME = "gofundme.db"
IMAGE_DIR = "images"

# ======================
# 初始化 MediaPipe
# ======================
mp_face_detection = mp.solutions.face_detection
face_detector = mp_face_detection.FaceDetection(
    model_selection=1,   # 1 = 远距离（多人更好）
    min_detection_confidence=0.5
)

# ======================
# 检测人脸数量
# ======================
def count_faces(image_path):
    try:
        img = cv2.imread(image_path)

        if img is None:
            return 0

        # BGR → RGB（MediaPipe必须）
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

        results = face_detector.process(img_rgb)

        if results.detections:
            return len(results.detections)
        else:
            return 0

    except Exception as e:
        print("❌ 图像处理错误:", e)
        return 0


# ======================
# 主逻辑
# ======================
def main():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT p.id, p.image_name
        FROM projects p
        WHERE p.image_name IS NOT NULL
          AND EXISTS (
              SELECT 1
              FROM campaigns c
              WHERE c.id = p.id
                AND c.main_picture IS NULL
          )
    """)

    rows = cursor.fetchall()
    print(f"处理 {len(rows)} 张图片")

    for pid, image_name in rows:
        image_path = os.path.join(IMAGE_DIR, image_name)

        if not os.path.exists(image_path):
            print(f"⚠️ 图片不存在: {image_path}")
            continue

        face_count = count_faces(image_path)

        print(f"ID={pid}, 人脸数={face_count}")

        # 写入 campaigns 表
        cursor.execute("""
        UPDATE campaigns
        SET main_picture = ?
        WHERE id = ?
        """, (str(face_count), pid))

        conn.commit()

    conn.close()
    print("🎉 detector完成")


if __name__ == "__main__":
    main()
