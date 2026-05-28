from pathlib import Path
from datetime import datetime
import base64
import json
import shutil
import subprocess
import time
import traceback
from typing import Any

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


BASE_DIR = Path(__file__).parent.resolve()
VISION_QUEUE_DIR = BASE_DIR / "vision_queue"
VISION_OUTPUT_DIR = BASE_DIR / "vision_output"
VISION_DONE_DIR = BASE_DIR / "vision_done"
VISION_FAILED_DIR = BASE_DIR / "vision_failed"
VISION_OCR_DIR = BASE_DIR / "vision_ocr"

OLLAMA_MODEL = "llama3.2-vision"

for folder in [
    VISION_QUEUE_DIR,
    VISION_OUTPUT_DIR,
    VISION_DONE_DIR,
    VISION_FAILED_DIR,
    VISION_OCR_DIR,
]:
    folder.mkdir(exist_ok=True)


VISION_EXTRACTION_PROMPT = """You are analyzing a document page image for a RAG / LLM knowledge system.

The page may contain text, tables, diagrams, medical figures, clinical pathways, or flowcharts.

Your job is not only to describe the image, but to convert visual information into structured, searchable Markdown.

Return your answer in this exact Markdown structure:

# Visual Summary
Briefly describe what this page visually contains.

# Important Text
Extract important visible text. Preserve headings, labels, decision boxes, captions, table headers, and clinically meaningful terms.

# Diagram / Flowchart Structure
If there is a diagram, flowchart, pathway, decision tree, chart, or table, explain the structure clearly.

For flowcharts, include:
- start point
- process nodes
- decision nodes
- arrows / branches
- outcomes
- yes/no, positive/negative, included/excluded paths if visible

If there is no diagram or flowchart, write: Not applicable.

# Mermaid Representation
If the page contains a flowchart or pathway, create a Mermaid flowchart.
If not applicable, write: Not applicable.

# RAG Notes
Write 3-8 concise bullet points useful for retrieval.
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


def load_queue_metadata(metadata_path: Path) -> dict[str, Any]:
    return json.loads(metadata_path.read_text(encoding="utf-8"))


def encode_image_base64(image_path: Path) -> str:
    return base64.b64encode(image_path.read_bytes()).decode("utf-8")


def run_paddleocr_if_available(image_path: Path) -> dict[str, Any]:
    """
    Optional local OCR layer.

    This function tries to use PaddleOCR if it is installed.
    If PaddleOCR is not installed or fails, the worker still continues with vision LLM only.
    """
    try:
        from paddleocr import PaddleOCR  # type: ignore
    except Exception as exc:
        return {
            "available": False,
            "engine": "paddleocr",
            "error": f"PaddleOCR not available: {exc}",
            "items": [],
            "plain_text": "",
        }

    try:
        ocr = PaddleOCR(
            use_angle_cls=True,
            lang="ch",
            show_log=False,
        )

        raw_result = ocr.ocr(str(image_path), cls=True)

        items = []
        plain_text_lines = []

        if raw_result:
            for page_result in raw_result:
                if not page_result:
                    continue

                for line in page_result:
                    box = line[0]
                    text = line[1][0]
                    confidence = float(line[1][1])

                    item = {
                        "text": text,
                        "confidence": round(confidence, 4),
                        "box": box,
                    }

                    items.append(item)
                    plain_text_lines.append(text)

        return {
            "available": True,
            "engine": "paddleocr",
            "items": items,
            "plain_text": "\n".join(plain_text_lines),
        }

    except Exception as exc:
        return {
            "available": False,
            "engine": "paddleocr",
            "error": str(exc),
            "items": [],
            "plain_text": "",
        }


def check_ollama_available() -> bool:
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def call_ollama_vision(image_path: Path, ocr_text: str = "") -> str:
    """
    Calls local Ollama vision model through the Python ollama package.
    Requires:
        pip install ollama
        ollama pull llama3.2-vision
    """
    try:
        import ollama  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "Python package `ollama` is not installed. Run: pip install ollama"
        ) from exc

    if not check_ollama_available():
        raise RuntimeError(
            "Ollama is not available. Make sure the Ollama app/server is running."
        )

    prompt = VISION_EXTRACTION_PROMPT

    if ocr_text.strip():
        prompt += (
            "\n\nThe OCR engine extracted the following text from the image. "
            "Use it as a hint, but verify against the image and preserve visual structure.\n\n"
            "# OCR Text Hint\n"
            f"{ocr_text.strip()}\n"
        )

    response = ollama.chat(
        model=OLLAMA_MODEL,
        messages=[
            {
                "role": "user",
                "content": prompt,
                "images": [str(image_path)],
            }
        ],
    )

    message = response.get("message", {})
    content = message.get("content", "")

    if not content.strip():
        raise RuntimeError("Ollama returned an empty response.")

    return content


def build_output_markdown(
    queue_payload: dict[str, Any],
    image_path: Path,
    ocr_payload: dict[str, Any],
    vision_markdown: str,
) -> str:
    source_document = queue_payload.get("source_document", "unknown")
    page = queue_payload.get("page", "unknown")
    analysis = queue_payload.get("analysis", {})

    return f"""---
source_document: "{source_document}"
page: {page}
page_image: "{image_path.name}"
processed_at: "{datetime.now().isoformat(timespec='seconds')}"
status: "vision_processed"
vision_model: "{OLLAMA_MODEL}"
ocr_engine: "paddleocr"
ocr_available: {str(bool(ocr_payload.get('available'))).lower()}
---

# Vision Analysis

{vision_markdown.strip()}

---

# Worker Metadata

## Router Analysis

```json
{json.dumps(analysis, indent=2, ensure_ascii=False)}
```

## OCR Plain Text

```text
{ocr_payload.get('plain_text', '').strip()}
```
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
        page = int(queue_payload.get("page", 0))
        output_stem = f"{Path(source_document).stem}_page_{page:03d}_vision"

        print("開始 local OCR...")
        ocr_payload = run_paddleocr_if_available(image_path)

        ocr_output_path = safe_path(VISION_OCR_DIR / f"{output_stem}_ocr.json")
        ocr_output_path.write_text(
            json.dumps(ocr_payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        if ocr_payload.get("available"):
            print(f"OCR 完成，偵測到 {len(ocr_payload.get('items', []))} 個文字項目")
        else:
            print("OCR 不可用或失敗，改用 vision model 直接分析圖片")

        print(f"開始呼叫 Ollama vision model：{OLLAMA_MODEL}")
        vision_markdown = call_ollama_vision(
            image_path=image_path,
            ocr_text=ocr_payload.get("plain_text", ""),
        )

        output_path = safe_path(VISION_OUTPUT_DIR / f"{output_stem}.md")
        output_markdown = build_output_markdown(
            queue_payload=queue_payload,
            image_path=image_path,
            ocr_payload=ocr_payload,
            vision_markdown=vision_markdown,
        )
        output_path.write_text(output_markdown, encoding="utf-8")

        done_metadata_path = safe_move(metadata_path, VISION_DONE_DIR)
        done_image_path = safe_move(image_path, VISION_DONE_DIR)

        print(f"Vision analysis 已輸出：{output_path.name}")
        print(f"OCR JSON 已輸出：{ocr_output_path.name}")
        print(f"已移動 queue metadata：{done_metadata_path.name}")
        print(f"已移動 queue image：{done_image_path.name}")

    except Exception:
        error_path = safe_path(VISION_FAILED_DIR / f"{metadata_path.stem}_worker_v2_error.txt")
        error_path.write_text(traceback.format_exc(), encoding="utf-8")

        try:
            safe_move(metadata_path, VISION_FAILED_DIR)
        except Exception:
            pass

        print(f"Vision worker v2 失敗：{metadata_path.name}，錯誤已寫入 vision_failed/")


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
    print(f"Vision OCR 輸出位置：{VISION_OCR_DIR}")
    print(f"Vision done 位置：{VISION_DONE_DIR}")
    print(f"使用 Ollama vision model：{OLLAMA_MODEL}")

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
        print("停止 vision worker v2。")
        observer.stop()

    observer.join()