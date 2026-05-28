from pathlib import Path
from datetime import datetime
import json
import time
import traceback

import fitz  # PyMuPDF
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler


BASE_DIR = Path(__file__).parent.resolve()
PROCESSED_DIR = BASE_DIR / "processed"
VISION_QUEUE_DIR = BASE_DIR / "vision_queue"
VISION_REPORT_DIR = BASE_DIR / "vision_reports"
VISION_FAILED_DIR = BASE_DIR / "vision_failed"

PDF_EXTENSIONS = {".pdf"}

FLOWCHART_KEYWORDS = [
    "flowchart",
    "flow chart",
    "algorithm",
    "pathway",
    "workflow",
    "decision tree",
    "figure",
    "fig.",
    "diagram",
    "流程",
    "流程圖",
    "演算法",
    "路徑",
    "圖",
    "圖表",
    "決策",
]

for folder in [
    PROCESSED_DIR,
    VISION_QUEUE_DIR,
    VISION_REPORT_DIR,
    VISION_FAILED_DIR,
]:
    folder.mkdir(exist_ok=True)


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


def contains_flowchart_keywords(text: str) -> list[str]:
    lowered = text.lower()

    return [keyword for keyword in FLOWCHART_KEYWORDS if keyword.lower() in lowered]


def analyze_page(page: fitz.Page) -> dict:
    text = page.get_text("text") or ""
    drawings = page.get_drawings()
    images = page.get_images(full=True)

    page_area = page.rect.width * page.rect.height

    image_area = 0.0
    for image in images:
        xref = image[0]
        rects = page.get_image_rects(xref)
        for rect in rects:
            image_area += rect.width * rect.height

    image_area_ratio = image_area / page_area if page_area else 0

    keyword_hits = contains_flowchart_keywords(text)

    score = 0
    reasons = []

    if len(text.strip()) < 300:
        score += 2
        reasons.append("low_text_length")

    if image_area_ratio >= 0.25:
        score += 2
        reasons.append("large_image_area")

    if len(drawings) >= 20:
        score += 2
        reasons.append("many_vector_drawings")

    if keyword_hits:
        score += 2
        reasons.append("diagram_or_flowchart_keywords")

    if len(images) >= 3:
        score += 1
        reasons.append("multiple_images")

    vision_needed = score >= 3

    return {
        "text_length": len(text.strip()),
        "image_count": len(images),
        "drawing_count": len(drawings),
        "image_area_ratio": round(image_area_ratio, 4),
        "keyword_hits": keyword_hits,
        "vision_score": score,
        "vision_needed": vision_needed,
        "reasons": reasons,
    }


def render_page_to_png(page: fitz.Page, output_path: Path, zoom: float = 2.0):
    matrix = fitz.Matrix(zoom, zoom)
    pixmap = page.get_pixmap(matrix=matrix, alpha=False)
    pixmap.save(str(output_path))


def route_pdf(pdf_path: Path):
    if pdf_path.suffix.lower() not in PDF_EXTENSIONS:
        print(f"略過非 PDF：{pdf_path.name}")
        return

    print(f"開始分析 PDF 視覺需求：{pdf_path.name}")

    if not wait_until_file_is_stable(pdf_path):
        print(f"檔案尚未準備好：{pdf_path.name}")
        return

    report = {
        "source_document": pdf_path.name,
        "source_path": str(pdf_path),
        "analyzed_at": datetime.now().isoformat(timespec="seconds"),
        "pages": [],
        "queued_pages": [],
    }

    try:
        document = fitz.open(pdf_path)

        for index, page in enumerate(document):
            page_number = index + 1
            analysis = analyze_page(page)

            page_report = {
                "page": page_number,
                **analysis,
            }

            report["pages"].append(page_report)

            if analysis["vision_needed"]:
                base_name = f"{pdf_path.stem}_page_{page_number:03d}"
                image_path = safe_path(VISION_QUEUE_DIR / f"{base_name}.png")
                json_path = safe_path(VISION_QUEUE_DIR / f"{base_name}.json")

                render_page_to_png(page, image_path)

                queue_payload = {
                    "source_document": pdf_path.name,
                    "source_path": str(pdf_path),
                    "page": page_number,
                    "page_image": image_path.name,
                    "queued_at": datetime.now().isoformat(timespec="seconds"),
                    "analysis": analysis,
                    "suggested_task": "vision_summary_and_flowchart_extraction",
                }

                json_path.write_text(
                    json.dumps(queue_payload, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )

                report["queued_pages"].append(
                    {
                        "page": page_number,
                        "image": image_path.name,
                        "metadata": json_path.name,
                        "reasons": analysis["reasons"],
                        "vision_score": analysis["vision_score"],
                    }
                )

        document.close()

        report_path = safe_path(VISION_REPORT_DIR / f"{pdf_path.stem}_vision_report.json")
        report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        print(
            f"分析完成：{pdf_path.name}，送入 vision_queue 的頁數：{len(report['queued_pages'])}"
        )

    except Exception:
        error_path = safe_path(VISION_FAILED_DIR / f"{pdf_path.stem}_vision_error.txt")
        error_path.write_text(traceback.format_exc(), encoding="utf-8")
        print(f"視覺分析失敗：{pdf_path.name}，錯誤已寫入 vision_failed/")


class ProcessedPdfHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.is_directory:
            return

        route_pdf(Path(event.src_path))

    def on_moved(self, event):
        if event.is_directory:
            return

        route_pdf(Path(event.dest_path))


if __name__ == "__main__":
    print("開始監控 processed/ 裡的 PDF，判斷哪些頁需要 Vision。")
    print(f"Vision queue 輸出位置：{VISION_QUEUE_DIR}")
    print(f"Vision report 輸出位置：{VISION_REPORT_DIR}")

    existing_pdfs = [
        p for p in PROCESSED_DIR.iterdir()
        if p.is_file() and p.suffix.lower() in PDF_EXTENSIONS
    ]

    if existing_pdfs:
        print(f"發現 {len(existing_pdfs)} 個既有 PDF，開始批次分析...")

        for pdf_file in existing_pdfs:
            route_pdf(pdf_file)

    observer = Observer()
    observer.schedule(ProcessedPdfHandler(), str(PROCESSED_DIR), recursive=False)
    observer.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("停止 vision router。")
        observer.stop()

    observer.join()