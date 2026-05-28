from pathlib import Path
from datetime import datetime
import json
import shutil
import time
import traceback

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


BASE_DIR = Path(__file__).parent.resolve()
VISION_QUEUE_DIR = BASE_DIR / "vision_queue"
VISION_OUTPUT_DIR = BASE_DIR / "vision_output"
VISION_DONE_DIR = BASE_DIR / "vision_done"
VISION_FAILED_DIR = BASE_DIR / "vision_failed"

for folder in [
    VISION_QUEUE_DIR,
    VISION_OUTPUT_DIR,
    VISION_DONE_DIR,
    VISION_FAILED_DIR,
]:
    folder.mkdir(exist_ok=True)


VISION_EXTRACTION_PROMPT = """You are analyzing a document page image.

Your goal is to extract useful information for a RAG / LLM knowledge system.

Please produce a structured Markdown report with these sections:

# Visual Summary
Briefly describe what this page visually contains.

# Important Text
Extract important visible text from the image. Preserve headings, labels, decision boxes, and table headers when possible.

# Diagram / Flowchart Structure
If there is a diagram, flowchart, pathway, decision tree, chart, or table, explain its structure clearly.

For flowcharts, include:
- start point
- decision nodes
- arrows / branches
- outcomes
- yes/no or positive/negative paths

# Mermaid Representation
If the page contains a flowchart or pathway, create a Mermaid flowchart.
If not applicable, write: Not applicable.

# RAG Notes
Write 3-8 concise bullet points that would be useful for retrieval.
"""


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def wait_until_file_is_stable(path: Path, checks: int = 3, delay: float = 1.0) -> bool:
    last_size = -1

    for _ in range(checks):
        if not path.exists():
            return False

        current_size = path.stat().st_size

        if current_size == last_size:
            return True

        last_size = current_size
        time.sleep(delay)

    return True


def safe_path(path: Path) -> Path:
    if not path.exists():
        return path

    return path.with_name(f"{path.stem}_{timestamp()}{path.suffix}")


def safe_move(path: Path, target_dir: Path) -> Path:
    target_path = safe_path(target_dir / path.name)
    shutil.move(str(path), str(target_path))
    return target_path


def load_queue_metadata(metadata_path: Path) -> dict:
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def build_manual_review_markdown(queue_payload: dict) -> str:
    source_document = queue_payload.get("source_document", "unknown")
    page = queue_payload.get("page", "unknown")
    page_image = queue_payload.get("page_image", "unknown")
    analysis = queue_payload.get("analysis", {})

    reasons = analysis.get("reasons", [])
    keyword_hits = analysis.get("keyword_hits", [])

    reasons_text = "\n".join(f"- {reason}" for reason in reasons) or "- None"
    keywords_text = "\n".join(f"- {keyword}" for keyword in keyword_hits) or "- None"

    return f"""---
source_document: "{source_document}"
page: {page}
page_image: "{page_image}"
processed_at: "{datetime.now().isoformat(timespec='seconds')}"
status: "manual_review_needed"
---

# Vision Review Needed

This page was selected by `vision_router.py` as likely useful for vision analysis.

## Source

- Document: `{source_document}`
- Page: `{page}`
- Image file: `{page_image}`

## Why This Page Was Queued

{reasons_text}

## Keyword Hits

{keywords_text}

## Router Analysis

```json
{json.dumps(analysis, indent=2, ensure_ascii=False)}
```

## Suggested Vision Prompt

```text
{VISION_EXTRACTION_PROMPT.strip()}
```

## Placeholder Output

Paste or generate the model's visual analysis below this section.

### Visual Summary


### Important Text


### Diagram / Flowchart Structure


### Mermaid Representation


### RAG Notes


"""


def process_queue_item(metadata_path: Path):
    if metadata_path.suffix.lower() != ".json":
        return

    print(f"處理 vision queue：{metadata_path.name}")

    if not wait_until_file_is_stable(metadata_path):
        print(f"Queue metadata 尚未準備好：{metadata_path.name}")
        return

    try:
        queue_payload = load_queue_metadata(metadata_path)
        image_name = queue_payload.get("page_image")

        if not image_name:
            raise ValueError("Queue metadata 缺少 page_image 欄位")

        image_path = VISION_QUEUE_DIR / image_name

        if not image_path.exists():
            raise FileNotFoundError(f"找不到頁面圖片：{image_path}")

        if not wait_until_file_is_stable(image_path):
            print(f"頁面圖片尚未準備好：{image_path.name}")
            return

        source_document = queue_payload.get("source_document", "unknown_document")
        page = queue_payload.get("page", "unknown_page")
        output_stem = f"{Path(source_document).stem}_page_{int(page):03d}_vision"

        output_path = safe_path(VISION_OUTPUT_DIR / f"{output_stem}.md")
        output_markdown = build_manual_review_markdown(queue_payload)
        output_path.write_text(output_markdown, encoding="utf-8")

        done_metadata_path = safe_move(metadata_path, VISION_DONE_DIR)
        done_image_path = safe_move(image_path, VISION_DONE_DIR)

        print(f"Vision placeholder 已輸出：{output_path.name}")
        print(f"已移動 queue metadata：{done_metadata_path.name}")
        print(f"已移動 queue image：{done_image_path.name}")

    except Exception:
        error_path = safe_path(VISION_FAILED_DIR / f"{metadata_path.stem}_worker_error.txt")
        error_path.write_text(traceback.format_exc(), encoding="utf-8")

        try:
            safe_move(metadata_path, VISION_FAILED_DIR)
        except Exception:
            pass

        print(f"Vision worker 失敗：{metadata_path.name}，錯誤已寫入 vision_failed/")


class VisionQueueHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return

        process_queue_item(Path(event.src_path))

    def on_moved(self, event):
        if event.is_directory:
            return

        process_queue_item(Path(event.dest_path))


if __name__ == "__main__":
    print("開始監控 vision_queue/。")
    print(f"Vision output 輸出位置：{VISION_OUTPUT_DIR}")
    print(f"Vision done 位置：{VISION_DONE_DIR}")

    existing_metadata_files = [
        p for p in VISION_QUEUE_DIR.iterdir()
        if p.is_file() and p.suffix.lower() == ".json"
    ]

    if existing_metadata_files:
        print(f"發現 {len(existing_metadata_files)} 個既有 queue item，開始處理...")

        for metadata_file in existing_metadata_files:
            process_queue_item(metadata_file)

    observer = Observer()
    observer.schedule(VisionQueueHandler(), str(VISION_QUEUE_DIR), recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("停止 vision worker。")
        observer.stop()

    observer.join()