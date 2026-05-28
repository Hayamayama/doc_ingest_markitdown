from pathlib import Path
import argparse
import signal
import subprocess
import sys
import time


BASE_DIR = Path(__file__).parent.resolve()

LIGHTWEIGHT_SCRIPTS = [
    "watch_convert.py",
    "vision_router.py",
]

FULL_SCRIPTS = [
    "watch_convert.py",
    "vision_router.py",
    "vision_worker_v2.py",
]

processes: list[tuple[str, subprocess.Popen]] = []


def script_exists(script_name: str) -> bool:
    return (BASE_DIR / script_name).exists()


def start_script(script_name: str):
    script_path = BASE_DIR / script_name

    if not script_path.exists():
        print(f"找不到 script：{script_name}")
        return

    print(f"啟動：{script_name}")

    process = subprocess.Popen(
        [sys.executable, str(script_path)],
        cwd=str(BASE_DIR),
    )

    processes.append((script_name, process))


def stop_all_processes():
    print("\n正在停止 pipeline...")

    for script_name, process in processes:
        if process.poll() is None:
            print(f"停止：{script_name}")
            process.terminate()

    time.sleep(1)

    for script_name, process in processes:
        if process.poll() is None:
            print(f"強制停止：{script_name}")
            process.kill()

    print("Pipeline 已停止。")


def handle_shutdown_signal(signum, frame):
    stop_all_processes()
    sys.exit(0)


def print_status():
    folders = {
        "md_inbox": BASE_DIR / "md_inbox",
        "md_output": BASE_DIR / "md_output",
        "processed": BASE_DIR / "processed",
        "vision_queue": BASE_DIR / "vision_queue",
        "vision_output": BASE_DIR / "vision_output",
        "vision_done": BASE_DIR / "vision_done",
        "failed": BASE_DIR / "failed",
        "vision_failed": BASE_DIR / "vision_failed",
    }

    print("\n目前資料夾狀態：")

    for name, folder in folders.items():
        if not folder.exists():
            print(f"- {name}: 不存在")
            continue

        file_count = len([p for p in folder.iterdir() if p.is_file()])
        print(f"- {name}: {file_count} files")


def monitor_processes():
    while True:
        for script_name, process in processes:
            return_code = process.poll()

            if return_code is not None:
                print(f"\n警告：{script_name} 已停止，exit code: {return_code}")
                print("為了避免狀態混亂，請 Ctrl + C 停止整個 pipeline 後再重開。")

        time.sleep(2)


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run the document ingestion pipeline from one terminal."
    )

    parser.add_argument(
        "--full",
        action="store_true",
        help="Also start vision_worker_v2.py. This may consume much more power.",
    )

    parser.add_argument(
        "--status",
        action="store_true",
        help="Print folder status before starting the pipeline.",
    )

    return parser.parse_args()


def main():
    args = parse_args()

    signal.signal(signal.SIGINT, handle_shutdown_signal)
    signal.signal(signal.SIGTERM, handle_shutdown_signal)

    scripts = FULL_SCRIPTS if args.full else LIGHTWEIGHT_SCRIPTS

    print("啟動 document ingestion pipeline")
    print(f"專案位置：{BASE_DIR}")

    if args.full:
        print("模式：FULL，會啟動 vision_worker_v2.py，耗電會明顯增加。")
    else:
        print("模式：LIGHT，只啟動 watch_convert.py + vision_router.py。")
        print("需要 OCR / Vision 分析時，再另外手動跑 vision_worker_v2.py。")

    if args.status:
        print_status()

    missing_scripts = [script for script in scripts if not script_exists(script)]

    if missing_scripts:
        print("\n以下 script 不存在，請先確認檔案名稱：")
        for script in missing_scripts:
            print(f"- {script}")
        sys.exit(1)

    print("\n開始啟動 scripts...")

    for script in scripts:
        start_script(script)

    print("\nPipeline 已啟動。按 Ctrl + C 可以一次停止全部。")

    try:
        monitor_processes()
    finally:
        stop_all_processes()


if __name__ == "__main__":
    main()