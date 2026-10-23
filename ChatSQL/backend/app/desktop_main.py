import os
import socket
import threading
import time
import webbrowser

import uvicorn

from app.core.seed import default_desktop_data_root, initialize_data_root


def main() -> None:
    data_root = default_desktop_data_root()
    try:
        _log(data_root, "desktop_start")
        os.environ.setdefault("BANKNL2SQL_LITE_DATA_ROOT", str(data_root))
        initialize_data_root(data_root)
        _log(data_root, "seed_ready")

        host = "127.0.0.1"
        port = _free_port(8000)
        url = f"http://{host}:{port}"
        _log(data_root, f"serve {url}")
        from app.main import app as fastapi_app

        _log(data_root, "app_loaded")
        threading.Thread(target=_open_browser, args=(url,), daemon=True).start()
        uvicorn.run(fastapi_app, host=host, port=port, reload=False, log_level="info", log_config=None)
        _log(data_root, "server_stopped")
    except BaseException as exc:
        _log(data_root, f"error {type(exc).__name__}: {exc}")
        raise


def _free_port(start: int) -> int:
    for port in range(start, start + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
    raise RuntimeError("No free local port found for ChatSQL.")


def _open_browser(url: str) -> None:
    time.sleep(1.2)
    webbrowser.open(url)


def _log(data_root, message: str) -> None:
    log_path = data_root.parent / "desktop.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as file:
        file.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")


if __name__ == "__main__":
    main()
