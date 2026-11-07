"""Bound Docker CLI output in host memory and terminate the client on timeout."""

import subprocess
import threading
import time


class DockerProcessError(RuntimeError):
    pass


def run_bounded(cmd: list[str], *, input_text: str = "", timeout: float = 10,
                max_output_bytes: int = 262144) -> subprocess.CompletedProcess:
    try:
        process = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as exc:
        raise DockerProcessError("could not start Docker CLI") from exc
    buffers = [bytearray(), bytearray()]
    lock = threading.Lock()
    overflow = threading.Event()
    io_failed = threading.Event()

    def read_stream(stream, index):
        try:
            while chunk := stream.read(8192):
                with lock:
                    remaining = max_output_bytes - sum(map(len, buffers))
                    buffers[index].extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        overflow.set()
        except (OSError, ValueError):
            io_failed.set()
        finally:
            stream.close()

    def write_input():
        try:
            process.stdin.write(input_text.encode("utf-8"))
            process.stdin.flush()
        except BrokenPipeError:
            pass
        except (OSError, ValueError):
            io_failed.set()
        finally:
            process.stdin.close()

    workers = [threading.Thread(target=read_stream, args=(process.stdout, 0), daemon=True),
               threading.Thread(target=read_stream, args=(process.stderr, 1), daemon=True),
               threading.Thread(target=write_input, daemon=True)]
    for worker in workers:
        worker.start()
    deadline = time.monotonic() + timeout
    try:
        while True:
            if overflow.is_set():
                raise DockerProcessError("Docker command exceeded its output byte limit")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DockerProcessError("Docker command timed out")
            try:
                process.wait(timeout=min(0.05, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        for worker in workers:
            worker.join(timeout=2)
    if any(worker.is_alive() for worker in workers) or io_failed.is_set():
        raise DockerProcessError("Docker command I/O did not complete")
    if overflow.is_set():
        raise DockerProcessError("Docker command exceeded its output byte limit")
    return subprocess.CompletedProcess(cmd, process.returncode,
        buffers[0].decode("utf-8", errors="replace"), buffers[1].decode("utf-8", errors="replace"))
