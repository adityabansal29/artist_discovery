"""Shared Claude CLI runner used by Web/X collection and findings synthesis."""

import fcntl
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from config import OUTPUTS


def run_phase(prompt: str, run_dir: Path, logger=None, phase: str = "phase") -> int:
    """Run one isolated Claude phase with phase-specific logs and a global lock."""
    claude = shutil.which("claude")
    if not claude:
        raise SystemExit("Claude Code CLI not found. Install/login before running research.")
    debug_path = run_dir / f"{phase}_claude_debug.log"
    progress_path = run_dir / "progress.log"
    command = [claude, "-p", prompt, "--output-format", "text", "--safe-mode",
               "--no-session-persistence", "--permission-mode", "bypassPermissions",
               "--debug-file", str(debug_path)]
    with progress_path.open("a", encoding="utf-8") as progress:
        progress.write(f"Claude {phase}: started\n")
    lock_path = OUTPUTS / ".claude_research.lock"
    with lock_path.open("w", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            if logger:
                logger("Claude: another research run is already active", "failed")
            return 125
        process = subprocess.Popen(command, cwd=run_dir, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
                                   text=True, env=os.environ.copy())
        debug_stop = threading.Event()

        def mirror_debug() -> None:
            position = 0
            while process.poll() is None or not debug_stop.is_set():
                try:
                    content = debug_path.read_text(encoding="utf-8", errors="replace")
                except FileNotFoundError:
                    content = ""
                if len(content) > position:
                    print(f"[{phase}-claude-debug] " + content[position:].replace("\n", f"\n[{phase}-claude-debug] "), end="", flush=True)
                    position = len(content)
                if debug_stop.is_set():
                    break
                time.sleep(0.25)

        debug_thread = threading.Thread(target=mirror_debug, daemon=True)
        debug_thread.start()
        try:
            process.communicate(timeout=600)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            if logger:
                logger(f"Claude {phase}: timed out after 10 minutes", "failed")
            return 124
        finally:
            debug_stop.set()
            debug_thread.join(timeout=2)
        fcntl.flock(lock, fcntl.LOCK_UN)
    with progress_path.open("a", encoding="utf-8") as progress:
        progress.write(f"Claude {phase}: finished returncode={process.returncode}\n")
    return process.returncode
