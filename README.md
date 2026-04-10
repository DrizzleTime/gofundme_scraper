# GoFundMe Scraper 使用说明

## 项目用途

这个项目用于批量抓取 GoFundMe 某个分类下的筹款项目，并将结果保存到本地数据库和图片目录。

主流程只依赖 3 个脚本：

- `collector.py`：先抓项目列表，写入 `projects` 表
- `scraper.py`：再并发抓项目详情和封面图，写入 `campaigns` 表并下载图片
- `clean.py`：最后清理损坏数据、孤儿数据和无用图片

当前数据库文件和图片目录：

- `gofundme.db`
- `images/`

## 数据结构

数据库里主要有两张表：

- `projects`：保存项目基础信息、项目链接、图片文件名、抓取时间
- `campaigns`：保存项目详情字段，比如标题、金额、描述、更新时间、捐赠数等

两张表通过同一个 `id` 对应同一个项目。

## 环境准备

参考当前仓库和 `配置说明.txt`，建议使用 Python 3.10 及以上。

安装依赖：

```bash
pip install httpx pandas pyperclip opencv-python mediapipe pillow
```

说明：

- `collector.py`、`scraper.py`、`clean.py` 主流程主要依赖 `httpx`
- `exporter.py` 需要 `pandas`
- `detector.py` 需要 `opencv-python` 和 `mediapipe`
- `resizer.py` 需要 `Pillow`

## 运行前先改配置

开始抓取前，先修改 [collector.py](/home/shiyu/Code/gofundme_scraper/collector.py) 里的这两个常量：

- `CATEGORY`
- `CATEGORY_ID`

例如：

```python
CATEGORY = "medical"
CATEGORY_ID = 11
```

`collector.py` 当前默认会抓到 `TARGET_PROJECTS = 7000` 条。

这里的 7000 不是最终目标数量，而是缓冲数量。实际原因很简单：

- GoFundMe 数据里会有损坏页面
- 有些项目抓下来后 `title` 为空
- 有些项目详情页抓不到
- 有些图片记录存在，但图片文件实际缺失

所以实际应该以保留约 5000 条有效数据为目标，先抓 7000 条，再通过 `clean.py` 清理垃圾数据。

## 推荐执行步骤

### 1. 抓项目列表

```bash
python collector.py
```

作用：

- 根据 `CATEGORY` 和 `CATEGORY_ID` 抓取目标分类的项目列表
- 将项目链接写入 `projects` 表
- 默认累计到 7000 条后停止

说明：

- 这个脚本支持同一分类的增量抓取
- 如果当前分类在 `projects` 里已经达到 7000 条，它会直接退出

### 2. 并发抓详情和图片

```bash
python scraper.py --concurrency 10
```

作用：

- 读取 `projects` 表中的项目链接
- 并发请求 GoFundMe GraphQL 接口
- 将详情写入 `campaigns` 表
- 下载封面图到 `images/`
- 同时回写 `projects.image_name`、`projects.content`、`projects.scrape_time`

说明：

- 默认并发是 `10`
- 7000 条数据通常需要十几分钟，实际时间取决于网络和目标站点响应
- 第一次跑完后，`campaigns` 数量通常会少于 `projects`，这是正常现象，因为原始数据里存在无效项目

### 3. 清理垃圾数据

```bash
python clean.py
```

`clean.py` 会执行下面几件事：

- 删除 `campaigns.title` 为空的记录
- 删除 `projects` 中没有对应 `campaigns` 的记录
- 删除图片文件缺失对应的 `projects` 和 `campaigns`
- 删除 `images/` 目录中数据库未引用的文件
- 最终让 `projects` 和 `campaigns` 数量一致

清理完成后，数据库里保留下来的数据才是后续处理和导出的基础数据。

## 一次完整流程

```bash
python collector.py
python scraper.py --concurrency 10
python clean.py
```

推荐理解为：

1. 先抓 7000 条候选项目
2. 再批量抓详情和图片
3. 最后清掉损坏数据
4. 最终保留约 5000 条有效数据

## 切换分类时的注意事项

如果你要切换到新的分类，不建议直接复用旧的 `gofundme.db` 和 `images/`。

原因：

- `collector.py` 只按当前 `CATEGORY` 统计 7000 条
- `scraper.py` 会处理数据库里所有未完成项目，不会只限定当前分类
- `clean.py` 也是全库清理

如果不清理旧数据，不同分类的数据会混在一起。

更直接的做法是，在切换分类前先备份或删除旧的数据库和图片目录内容。

## 其他脚本

下面这些脚本不是主抓取流程必须步骤，属于后处理工具：

- `parser.py`：从 `projects.content` 中用正则提取字段后写入 `campaigns`
- `resizer.py`：缩放 `images/` 中的图片
- `detector.py`：检测图片里的人脸数，并写回 `campaigns.main_picture`
- `exporter.py`：将数据库表导出为 Excel

如果你只关心抓取项目详情，核心只需要执行：

```bash
python collector.py
python scraper.py --concurrency 10
python clean.py
```

## 补充说明

- `db_init.py` 可以创建表，但当前主流程里不是必须步骤，因为 `collector.py` 和 `scraper.py` 已经会自动建表
- 如果你只重跑 `scraper.py`，它会优先处理没有图片或没有 `campaigns` 详情的项目
- `clean.py` 会直接修改数据库并删除图片文件，执行前如果数据重要，先备份
