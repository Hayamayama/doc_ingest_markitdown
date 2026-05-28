from pathlib import Path
import shutil
import time
import traceback
from datetime import datetime
import json

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from markitdown import MarkItDown


BASE_DIR = Path(__file__).parent.resolve()

INBOX_DIR = BASE_DIR / "md_inbox"
OUTPUT_DIR = BASE_DIR / "md_output"
PROCESSED_DIR = BASE_DIR / "processed"
FAILED_DIR = BASE_DIR / "failed"
METADATA_DIR = BASE_DIR / "metadata"
CHUNK_DIR = BASE_DIR / "chunks"

SUPPORTED_EXTENSIONS = {
    ".pdf", ".docx", ".pptx", ".xlsx",
    ".html", ".htm", ".csv", ".json", ".xml",
    ".txt", ".md",
    ".jpg", ".jpeg", ".png",
    ".mp3", ".wav", ".m4a",
    ".zip",
}

for folder in [
    INBOX_DIR,
    OUTPUT_DIR,
    PROCESSED_DIR,
    FAILED_DIR,
    METADATA_DIR,
    CHUNK_DIR,
]:
    folder.mkdir(exist_ok=True)


def timestamp():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def wait_until_file_is_stable(path: Path, checks: int = 3, delay: float = 1.0):
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


def safe_output_path(original_path: Path) -> Path:
    output_path = OUTPUT_DIR / f"{original_path.stem}.md"

    if not output_path.exists():
        return output_path

    return OUTPUT_DIR / f"{original_path.stem}_{timestamp()}.md"


def safe_move(path: Path, target_dir: Path):
    target_path = target_dir / path.name

    if target_path.exists():
        target_path = target_dir / f"{path.stem}_{timestamp()}{path.suffix}"

    shutil.move(str(path), str(target_path))


def save_metadata(original_path: Path, output_path: Path, markdown_text: str):
    metadata = {
        "source_file": original_path.name,
        "source_path": str(original_path),
        "output_markdown": output_path.name,
        "converted_at": datetime.now().isoformat(timespec="seconds"),
        "file_type": original_path.suffix.lower(),
        "markdown_characters": len(markdown_text),
        "status": "success",
    }

    metadata_path = METADATA_DIR / f"{original_path.stem}.json"

    if metadata_path.exists():
        metadata_path = (
            METADATA_DIR / f"{original_path.stem}_{timestamp()}.json"
        )

    metadata_path.write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )



def chunk_markdown(markdown_text: str, chunk_size: int = 1200):
    chunks = []

    current_chunk = ""

    for line in markdown_text.splitlines():
        if len(current_chunk) + len(line) > chunk_size:
            chunks.append(current_chunk.strip())
            current_chunk = ""

        current_chunk += line + "\n"

    if current_chunk.strip():
        chunks.append(current_chunk.strip())

    return chunks


def convert_file(path: Path):
    if path.name.startswith("."):
        return

    if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        print(f"略過不支援格式：{path.name}")
        return

    print(f"偵測到新檔案：{path.name}")

    if not wait_until_file_is_stable(path):
        print(f"檔案不存在或尚未準備好：{path.name}")
        return

    md = MarkItDown()
    output_path = safe_output_path(path)

    try:
        result = md.convert(str(path))

        header = f"""---
source_file: "{path.name}"
converted_at: "{datetime.now().isoformat(timespec="seconds")}"
---

"""

        markdown_text = header + result.text_content

        output_path.write_text(markdown_text, encoding="utf-8")

        save_metadata(path, output_path, markdown_text)

        chunks = chunk_markdown(markdown_text)

        chunk_output_path = CHUNK_DIR / f"{path.stem}_chunks.json"

        if chunk_output_path.exists():
            chunk_output_path = (
                CHUNK_DIR / f"{path.stem}_{timestamp()}_chunks.json"
            )

        chunk_payload = {
            "source_file": path.name,
            "chunk_count": len(chunks),
            "chunks": chunks,
        }

        chunk_output_path.write_text(
            json.dumps(chunk_payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        safe_move(path, PROCESSED_DIR)

        print(f"轉換成功：{output_path.name}")
        print(f"Chunk 數量：{len(chunks)}")

    except Exception:
        error_log = FAILED_DIR / f"{path.stem}_{timestamp()}_error.txt"
        error_log.write_text(traceback.format_exc(), encoding="utf-8")

        safe_move(path, FAILED_DIR)
        print(f"轉換失敗：{path.name}，已移到 failed/")


class InboxHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return

        convert_file(Path(event.src_path))

    def on_moved(self, event):
        if event.is_directory:
            return

        convert_file(Path(event.dest_path))


if __name__ == "__main__":
    print("開始監控 md_inbox/")
    print(f"Markdown 輸出位置：{OUTPUT_DIR}")
    print(f"Metadata 輸出位置：{METADATA_DIR}")
    print(f"Chunk 輸出位置：{CHUNK_DIR}")

    existing_files = [
        p for p in INBOX_DIR.iterdir()
        if p.is_file()
    ]

    if existing_files:
        print(f"發現 {len(existing_files)} 個既有檔案，開始批次處理...")

        for existing_file in existing_files:
            convert_file(existing_file)

    observer = Observer()
    observer.schedule(InboxHandler(), str(INBOX_DIR), recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("停止監控。")
        observer.stop()

    observer.join()