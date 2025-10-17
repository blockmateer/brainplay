# real_time_ws_capture.py
# pip install selenium requests websocket-client

import json
import time
import threading
import requests
from websocket import WebSocketApp
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

REMOTE_DEBUGGING_PORT = 9222  # pick any free port; ensure uniqueness if parallel runs
HOTKEY = '5EyNLzPaMVHC9771hY9yaKDvYpjhKB2vPc9nAyoULe7xXi2u'

active_room_listeners = set()
room_lock = threading.Lock()

def start_browser(chrome_driver_path=None, headless=False):
    opts = Options()
    # Important: enable remote debugging so we can attach to DevTools
    opts.add_argument(f"--remote-debugging-port={REMOTE_DEBUGGING_PORT}")
    opts.add_argument("--no-first-run")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-default-browser-check")
    opts.add_argument("--headless=new")
    opts.add_argument("--remote-allow-origins=http://127.0.0.1:9222")
    # use a fresh temp profile if needed to avoid "profile in use" errors
    # opts.add_argument(f"--user-data-dir=/tmp/selenium-profile-{int(time.time())}")

    if chrome_driver_path:
        driver = webdriver.Chrome(executable_path=chrome_driver_path, options=opts)
    else:
        driver = webdriver.Chrome(options=opts)
    return driver

def get_devtools_ws_url():
    # The browser exposes a JSON list of debuggable pages at /json
    url = f"http://127.0.0.1:{REMOTE_DEBUGGING_PORT}/json"
    for _ in range(10):
        try:
            r = requests.get(url, timeout=1)
            j = r.json()
            # choose the first page or the page with "type":"page"
            for entry in j:
                if entry.get("type") in (None, "page", "other"):
                    ws = entry.get("webSocketDebuggerUrl")
                    if ws:
                        return ws
        except Exception:
            time.sleep(0.2)
    raise RuntimeError("Could not get DevTools websocket URL from browser")

def open_new_tab(driver, url):
    driver.execute_script(f"window.open('{url}', '_blank');")
    # switch to the new tab
    driver.switch_to.window(driver.window_handles[-1])
    time.sleep(0.5)  # allow tab to load

def start_room_listener(driver, room_id):
    room_url = f"https://play.shiftlayer.ai/room/{room_id}"
    open_new_tab(driver, room_url)

    # Get the DevTools websocket for this new tab
    stop_event = Event()
    ws_url = get_devtools_ws_url()  # your existing function
    print(f"[ROOM {room_id}] DevTools WS URL:", ws_url)

    # Start the listener thread
    threading.Thread(target=cdp_listen, args=(ws_url, stop_event, driver), daemon=True).start()


def cdp_listen(ws_url, stop_event, driver):
    """
    Connect to CDP websocket and print Network.webSocketFrame* events in real time.
    """
    # We'll need to send a few commands to enable Network events
    next_id = {"v": 1}
    def make_id():
        i = next_id["v"]
        next_id["v"] += 1
        return i

    def on_open(ws):
        # enable Network domain so we get websocket events
        msg = {"id": make_id(), "method": "Network.enable", "params": {}}
        ws.send(json.dumps(msg))
        # optionally enable Page as well
        ws.send(json.dumps({"id": make_id(), "method": "Page.enable"}))
        print("[CDP] Subscribed to Network events")

    def on_message(ws, message):
        try:
            m = json.loads(message)
        except Exception:
            return
        # CDP events don't have "id" (or have different shape); the field "method" signals an event
        method = m.get("method")
        if method == "Network.webSocketFrameReceived":
            params = m.get("params", {})
            response = params.get("response", {})
            payload = response.get("payloadData")
            op = response.get("opcode")  # optional
            url = params.get("requestId")
            if payload.startswith("42"):
                data = json.loads(payload[2:])
                event_type = data[0]
                event_data = data[1]
                print(event_type)
                if event_type == "updateRoomList":
                    for room in event_data:
                        room_id = room['_id']
                        participants = room['participants']
                        is_correct = False
                        for participant in participants:
                            if participant['hotKey'] == HOTKEY:
                                is_correct = True
                                break
                        if room_id and is_correct:
                            with room_lock:
                                if room_id not in active_room_listeners:
                                    active_room_listeners.add(room_id)
                                    threading.Thread(
                                        target=start_room_listener, 
                                        args=(driver, room_id), 
                                        daemon=True
                                    ).start()
                if event_type == "gameStateUpdated":
                    data = {'card': event_data['gameState']['cards'], 'timestamp': time.time()}
                    with open(HOTKEY[:4] + "_" + event_data['gameState']['validatorKey'], "w") as f:
                        f.write(json.dumps(data))
                    stop_event.set()
        elif method == "Network.webSocketFrameSent":
            params = m.get("params", {})
            response = params.get("response", {})
            payload = response.get("payloadData")
            op = response.get("opcode")
        # optionally other useful events:
        elif method == "Network.webSocketCreated":
            params = m.get("params", {})
            print(f"[WS CREATED] {params}")
        elif method == "Network.webSocketClosed":
            params = m.get("params", {})
            print(f"[WS CLOSED] {params}")

    def on_error(ws, error):
        print("[CDP ERROR]", error)

    def on_close(ws, code, reason):
        print("[CDP CLOSED]", code, reason)

    ws_app = WebSocketApp(ws_url,
                          on_open=on_open,
                          on_message=on_message,
                          on_error=on_error,
                          on_close=on_close)

    # run_forever blocks; run in a thread and stop on stop_event
    def run():
        # small ping interval to keep connection alive
        ws_app.run_forever(ping_interval=10, ping_timeout=5)

    t = threading.Thread(target=run, daemon=True)
    t.start()

    try:
        while not stop_event.is_set():
            time.sleep(0.1)
    finally:
        try:
            ws_app.close()
        except Exception:
            pass

if __name__ == "__main__":
    import argparse
    from threading import Event

    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="https://play.shiftlayer.ai/room", help="page to open")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--chromedriver", default=None)
    args = parser.parse_args()

    stop_event = Event()
    driver = None
    try:
        driver = start_browser(chrome_driver_path=args.chromedriver, headless=args.headless)
        # give the browser a moment to start and expose the DevTools endpoint
        time.sleep(0.5)
        ws_url = get_devtools_ws_url()
        print("DevTools websocket URL:", ws_url)

        listener_thread = threading.Thread(target=cdp_listen, args=(ws_url, stop_event, driver), daemon=True)
        listener_thread.start()

        # navigate to the page (do this after starting listener so we don't miss early frames)
        driver.get(args.url)
        print("Opened:", args.url)

        # keep the script running while you watch messages. Ctrl+C to quit.
        while True:
            time.sleep(0.5)

    except KeyboardInterrupt:
        print("Interrupted by user — stopping")
    except Exception as e:
        print("Error:", e)
    finally:
        stop_event.set()
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
