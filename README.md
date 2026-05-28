# Doc Ingest MarkItDown

Doc Ingest MarkItDown is a local-first multimodal document ingestion pipeline designed to transform various document formats into structured knowledge representations that can be effectively understood, searched, retrieved, and analyzed by AI and large language models (LLMs).

This project supports the automatic processing of documents including PDFs, Word files, PowerPoint presentations, and more, converting them into enriched Markdown formats with comprehensive metadata and chunking. It incorporates vision-based routing to selectively apply OCR and vision models on relevant pages, leveraging local OCR (PaddleOCR) and local vision LLMs (Ollama with llama3.2-vision). Additional functionalities include flowchart and diagram analysis, Mermaid flowchart generation, and a queue-based worker architecture for scalable processing.

The system is optimized for:

- Local-first execution without reliance on cloud APIs
- Compatibility with Apple Silicon hardware
- Multimodal retrieval-augmented generation (RAG)
- Extensibility and long-term maintainability

---

# System Architecture

The overall pipeline is as follows:

```txt
Documents
↓
watch_convert.py
↓
Markdown / metadata / chunking
↓
processed/
↓
vision_router.py
↓
vision_queue/
↓
vision_worker_v2.py
↓
OCR + Vision LLM
↓
Structured multimodal Markdown
```

---

# Project Directory Structure

```txt
DOC_INGEST_MARKITDOWN/
├── .venv/
├── md_inbox/
├── md_output/
├── processed/
├── failed/
├── metadata/
├── chunks/
├── vision_queue/
├── vision_reports/
├── vision_output/
├── vision_ocr/
├── vision_done/
├── vision_failed/
├── watch_convert.py
├── vision_router.py
├── vision_worker.py
├── vision_worker_v2.py
├── run_pipeline.py
└── readme.md
```

---

# Directory Descriptions

## md_inbox/

Input folder for documents to be processed. Supported formats include:

- PDF
- Word
- PowerPoint
- Excel
- TXT
- HTML

The system automatically initiates processing upon file detection.

---

## md_output/

Contains the Markdown files generated from the source documents.

Example:

```txt
paper.pdf
↓
paper.md
```

---

## metadata/

Stores metadata for each processed document, including:

```json
{
  "source_file": "paper.pdf",
  "converted_at": "2026-05-28T...",
  "file_type": ".pdf",
  "markdown_characters": 19483
}
```

---

## chunks/

Contains chunked segments of documents. Current implementation is character-based chunking, with planned enhancements to semantic, heading-aware, and layout-aware chunking.

---

## processed/

Holds the original source files after Markdown conversion. This directory is monitored by `vision_router.py`.

---

## vision_queue/

Stores pages identified by `vision_router.py` as candidates for vision/OCR processing. Contents include image files and associated JSON metadata, e.g.:

```txt
paper_page_005.png
paper_page_005.json
```

---

## vision_reports/

Contains visual analysis reports for entire PDFs, detailing:

- Pages deemed important
- Vision scores
- Reasons for queue inclusion
- Keyword hits

---

## vision_output/

Final analysis results from the Vision LLM, typically structured as Markdown documents:

```md
# Visual Summary

# Important Text

# Diagram / Flowchart Structure

# Mermaid Representation

# RAG Notes
```

---

## vision_ocr/

Raw OCR results from PaddleOCR, including extracted text, confidence scores, and bounding boxes.

---

## vision_done/

Contains queue items that have completed vision analysis.

---

## failed/

Logs errors encountered during the Markdown processing pipeline.

---

## vision_failed/

Logs errors encountered during the vision pipeline, such as OCR failures, Ollama errors, queue parsing issues, or missing images.

---

# Installation Instructions

---

# 1. Create Python Virtual Environment

```bash
python3 -m venv .venv
```

Activate the environment:

```bash
source .venv/bin/activate
```

---

# 2. Install Python Packages

```bash
pip install "markitdown[all]"
pip install watchdog
pip install pymupdf
pip install ollama
pip install paddleocr
pip install paddlepaddle
```

---

# 3. Install Ollama

Official website:

https://ollama.com

After installation, verify with:

```bash
ollama list
```

---

# 4. Download Vision Model

```bash
ollama pull llama3.2-vision
```

This model is used by the Vision Pipeline.

---

# 5. Test PaddleOCR

Start Python interpreter:

```bash
python
```

Within Python:

```python
from paddleocr import PaddleOCR

ocr = PaddleOCR(
    use_angle_cls=True,
    lang='ch'
)

print("PaddleOCR OK")
```

Successful execution indicates correct setup.

---

# Recommended Execution Mode

For typical usage, it is recommended to operate the lightweight pipeline without running the Vision Worker continuously, as the Vision LLM component requires significant computational resources.

Execute the following to start the pipeline:

```bash
python run_pipeline.py
```

This command initiates:

```txt
watch_convert.py
vision_router.py
```

The Vision Worker (`vision_worker_v2.py`) is not started by default, reducing resource consumption.

---

To display the status of directories:

```bash
python run_pipeline.py --status
```

---

# Full Mode Execution

To run the full pipeline, including the Vision Worker, use:

```bash
python run_pipeline.py --full
```

This command starts:

```txt
watch_convert.py
vision_router.py
vision_worker_v2.py
```

Running in full mode is recommended when connected to a power source due to increased resource usage.

---

# Comprehensive Testing Procedure

---

# Step 1

Start the pipeline with status display:

```bash
python run_pipeline.py --status
```

---

# Step 2

Place PDF files into:

```txt
md_inbox/
```

Recommended test documents include those containing:

- Standard text
- Flowcharts
- Tables
- Images
- Scanned pages

---

# Step 3

Verify the Markdown pipeline output:

```txt
md_output/
metadata/
chunks/
processed/
```

---

# Step 4

Verify Vision Router outputs:

```txt
vision_queue/
vision_reports/
```

Pages identified as requiring vision processing are added to the queue, e.g.:

```txt
paper_page_005.png
paper_page_005.json
```

---

# Step 5

Manually start the Vision Worker:

```bash
python vision_worker_v2.py
```

---

# Step 6

Verify Vision processing results are generated in:

```txt
vision_output/
vision_ocr/
vision_done/
```

---

# Vision Router Architecture

The `vision_router.py` component does not perform OCR itself. Its primary function is to determine which document pages warrant computationally intensive vision analysis.

The router evaluates multiple factors including:

- Text length
- Image ratio
- Presence of vector graphics
- Flowchart-related keywords
- Diagram-related keywords

Based on these criteria, it computes a vision score for each page. Only pages exceeding a predefined threshold are enqueued for vision processing. This selective routing optimizes resource utilization by focusing on pages with substantive visual content.

---

# Rationale for Selective OCR Processing

Performing OCR on all pages indiscriminately is inefficient due to:

- High processing time
- Significant computational resource consumption
- Limited value on pages containing only logos or decorative elements

Therefore, the system adopts a selective approach to OCR, prioritizing pages based on content relevance.

---

# Queue-Based Architecture Justification

The use of a queue-based architecture provides several operational advantages:

- Increased system stability and reduced crash incidence
- Support for interruptible and resumable processing
- Enhanced debugging capabilities
- Facilitation of manual review processes
- Support for parallel processing
- Scalability for future extensions

This architecture aligns with industry best practices for production-level systems.

---

# Current System Capabilities

The system currently supports:

- Local document ingestion
- PDF to Markdown conversion
- Document chunking
- Metadata extraction
- Flowchart-based routing
- OCR processing
- Vision-based reasoning
- Mermaid diagram generation
- Local multimodal analysis

---

# Future Roadmap

Key planned developments include:

---

## 1. merge_pipeline.py

Integrate Markdown content, Vision Analysis, and OCR results into a unified multimodal document representation.

---

## 2. Semantic Chunking

Enhance chunking methods to include:

- Semantic splitting
- Heading-aware splitting
- Layout-aware splitting

---

## 3. Embedding Pipeline

Integrate embedding models such as:

- bge-m3
- nomic-embed-text

---

## 4. Vector Database Integration

Evaluate and potentially incorporate vector databases like:

- ChromaDB
- Qdrant

---

## 5. Retrieval System

Implement retrieval functionality, for example:

```bash
python ask.py "What are the contraindications?"
```

---

# Operational Considerations

---

## Vision Worker Resource Usage

The `llama3.2-vision` model represents the most computationally intensive component of the system. It is recommended to operate this component only when necessary and preferably when connected to external power.

---

## Apple Silicon Compatibility

The system is primarily developed and tested on Apple Silicon hardware, including M-series MacBooks.

---

## Local-First Design

The architecture emphasizes local execution to minimize reliance on cloud APIs, ensuring that OCR, Vision, Embedding, and Retrieval components operate entirely on local hardware.

---

# Project Summary

Doc Ingest MarkItDown is a comprehensive local multimodal knowledge ingestion system designed to convert diverse document formats into structured, machine-interpretable knowledge representations. It extends beyond simple PDF-to-Markdown conversion by integrating advanced vision analysis, OCR, and chunking techniques to enable sophisticated search, retrieval, and analysis capabilities. The system is engineered for extensibility, local execution, and efficient resource utilization, making it suitable for deployment in environments with constrained cloud access or privacy requirements.
