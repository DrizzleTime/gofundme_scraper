import os
from PIL import Image

MAX_WIDTH = 720
MAX_HEIGHT = 405

IMAGE_DIR = "images"

def resize_image(path):
    try:
        with Image.open(path) as img:
            width, height = img.size
            original_mode = img.mode

            # 如果是 RGBA / LA / P（带透明），先转 RGB
            if img.mode in ("RGBA", "LA", "P"):
                # 用白色背景合成
                background = Image.new("RGB", img.size, (255, 255, 255))
                background.paste(img, mask=img.split()[-1] if img.mode != "P" else None)
                img = background

            # 判断是否需要缩放
            if width <= MAX_WIDTH and height <= MAX_HEIGHT:
                # 即使不缩放，也确保能正确保存
                img.save(path, format="JPEG", quality=95)
                return

            # 计算缩放比例
            scale = min(MAX_WIDTH / width, MAX_HEIGHT / height)
            new_width = int(width * scale)
            new_height = int(height * scale)

            # 缩放
            img = img.resize((new_width, new_height), Image.LANCZOS)

            # 覆盖保存（强制 JPEG）
            img.save(path, format="JPEG", quality=95)

            print(f"已处理: {path} ({width}x{height} → {new_width}x{new_height}, {original_mode}→RGB)")

    except Exception as e:
        print(f"处理失败: {path}, 错误: {e}")


def main():
    for filename in os.listdir(IMAGE_DIR):
        path = os.path.join(IMAGE_DIR, filename)

        if not os.path.isfile(path):
            continue

        if filename.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            resize_image(path)

    print("✅ resizer完成")

if __name__ == "__main__":
    main()
