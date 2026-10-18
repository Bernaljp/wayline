"""A headless Chromium driven over the DevTools protocol on a pipe, for the tests that need a page to run.

The dashboard's front end is JavaScript, and what ticket 74 asks of it (math that renders, a sanitizer
that holds, a dialog that a poll leaves open, a zoom that rewraps at phone width, no request leaving
the machine) is only observable in a browser. This drives one with nothing but the standard library:
`--remote-debugging-pipe` makes Chromium read protocol commands from file descriptor 3 and write its
answers and events to descriptor 4, each message JSON ended by a NUL byte.

`find_chromium()` names the binary or None, so a machine without one skips those tests rather than
failing them: `WAYLINE_CHROMIUM` first, then Playwright's cached headless shell, then a Chromium or a
Chrome on `PATH` (GitHub's Ubuntu runners carry `google-chrome`).
"""

import fcntl
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

DEADLINE_S = 30

# The keys the tests press: `key` to its physical `code` and Windows virtual key code, which is what
# makes Chromium treat a dispatched Escape as a close request rather than as a bare event.
KEYS = {
    "Escape": ("Escape", 27),
    "+": ("Equal", 187),
    "=": ("Equal", 187),
    "-": ("Minus", 189),
    "0": ("Digit0", 48),
}


def find_chromium():
    named = os.environ.get("WAYLINE_CHROMIUM")
    if named:
        return named if Path(named).is_file() else None
    cache = Path.home() / ".cache" / "ms-playwright"
    for pattern in ("chromium_headless_shell-*/chrome-headless-shell-linux64/chrome-headless-shell",
                    "chromium-*/chrome-linux64/chrome", "chromium-*/chrome-linux/chrome"):
        found = sorted(cache.glob(pattern))
        if found:
            return str(found[-1])
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        path = shutil.which(name)
        if path:
            return path
    return None


class BrowserError(RuntimeError):
    """A protocol command the browser refused, or a page script that threw."""


class Browser:
    """One headless browser process; `page()` opens a tab in it."""

    def __init__(self, binary):
        self.profile = tempfile.mkdtemp(prefix="wayline-chromium-")
        to_browser_r, self._to_browser = os.pipe()
        self._from_browser, from_browser_w = os.pipe()

        def descriptors():
            # The two ends the browser wants as 3 and 4, copied high first so neither copy can
            # overwrite the other's source; the close of inherited descriptors spares 3 and 4.
            high_r = fcntl.fcntl(to_browser_r, fcntl.F_DUPFD, 10)
            high_w = fcntl.fcntl(from_browser_w, fcntl.F_DUPFD, 10)
            os.dup2(high_r, 3)
            os.dup2(high_w, 4)

        self.process = subprocess.Popen(
            [binary, "--headless=new", "--remote-debugging-pipe", "--no-sandbox", "--no-first-run",
             "--no-default-browser-check", "--disable-gpu", "--disable-extensions",
             "--disable-background-networking", "--disable-component-update", "--disable-sync",
             "--user-data-dir=%s" % self.profile, "about:blank"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            pass_fds=(3, 4, to_browser_r, from_browser_w), preexec_fn=descriptors, close_fds=True,
        )
        os.close(to_browser_r)
        os.close(from_browser_w)
        self._next = 0
        self._replies = {}
        self.events = []
        self._lock = threading.Condition()
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self):
        buffer = b""
        while True:
            try:
                chunk = os.read(self._from_browser, 1 << 16)
            except OSError:
                chunk = b""
            if not chunk:
                with self._lock:
                    self._replies[None] = "closed"
                    self._lock.notify_all()
                return
            buffer += chunk
            while b"\0" in buffer:
                raw, buffer = buffer.split(b"\0", 1)
                message = json.loads(raw)
                with self._lock:
                    if "id" in message:
                        self._replies[message["id"]] = message
                    else:
                        self.events.append(message)
                    self._lock.notify_all()

    def send(self, method, params=None, session=None):
        with self._lock:
            self._next += 1
            number = self._next
        message = {"id": number, "method": method, "params": params or {}}
        if session:
            message["sessionId"] = session
        os.write(self._to_browser, json.dumps(message).encode("utf-8") + b"\0")
        deadline = time.monotonic() + DEADLINE_S
        with self._lock:
            while number not in self._replies:
                if None in self._replies:
                    raise BrowserError("the browser closed its pipe during %s" % method)
                left = deadline - time.monotonic()
                if left <= 0:
                    raise BrowserError("no answer to %s in %ss" % (method, DEADLINE_S))
                self._lock.wait(left)
            reply = self._replies.pop(number)
        if "error" in reply:
            raise BrowserError("%s: %s" % (method, reply["error"]))
        return reply.get("result", {})

    def page(self):
        target = self.send("Target.createTarget", {"url": "about:blank"})["targetId"]
        session = self.send("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        return Page(self, target, session)

    def close(self):
        try:
            self.send("Browser.close")
        except BrowserError:
            pass
        try:
            self.process.wait(10)
        except subprocess.TimeoutExpired:  # pragma: no cover - a browser that will not close
            self.process.kill()
            self.process.wait(10)
        for fd in (self._to_browser, self._from_browser):
            try:
                os.close(fd)
            except OSError:
                pass
        shutil.rmtree(self.profile, ignore_errors=True)


class Page:
    """One tab: navigate it, run a script in it, press a key in it, and read what it requested."""

    def __init__(self, browser, target, session):
        self.browser = browser
        self.target = target
        self.session = session
        for domain in ("Page.enable", "Runtime.enable", "Network.enable"):
            self.send(domain)

    def send(self, method, params=None):
        return self.browser.send(method, params, self.session)

    def _mine(self):
        return [event for event in list(self.browser.events) if event.get("sessionId") == self.session]

    def goto(self, url):
        self.send("Page.navigate", {"url": url})
        self.wait_for("document.readyState === 'complete' && location.href !== 'about:blank'")

    def evaluate(self, expression):
        """The value of `expression` (awaited if it is a promise), or BrowserError if it threw."""
        result = self.send("Runtime.evaluate", {"expression": expression, "awaitPromise": True, "returnByValue": True})
        if "exceptionDetails" in result:
            details = result["exceptionDetails"]
            text = details.get("exception", {}).get("description") or details.get("text")
            raise BrowserError("the page threw: %s" % text)
        return result["result"].get("value")

    def wait_for(self, condition, timeout=DEADLINE_S):
        """Evaluate `condition` until it is truthy; waiting on the page, not on a fixed sleep."""
        deadline = time.monotonic() + timeout
        while True:
            value = self.evaluate("Boolean(%s)" % condition)
            if value:
                return
            if time.monotonic() > deadline:
                raise BrowserError("still false after %ss: %s" % (timeout, condition))
            time.sleep(0.05)

    def press(self, key, code=None):
        """A real key press, as the keyboard sends it, on whatever has focus."""
        known = KEYS.get(key, (code or key, ord(key.upper()) if len(key) == 1 else 0))
        base = {"key": key, "code": known[0], "windowsVirtualKeyCode": known[1], "nativeVirtualKeyCode": known[1]}
        if len(key) == 1:
            self.send("Input.dispatchKeyEvent", dict(base, type="keyDown", text=key, unmodifiedText=key))
        else:
            self.send("Input.dispatchKeyEvent", dict(base, type="rawKeyDown"))
        self.send("Input.dispatchKeyEvent", dict(base, type="keyUp"))

    def click(self, element):
        """A real mouse click at the middle of the element the expression `element` names."""
        x, y = self.evaluate("""(() => {
          const node = %s;
          node.scrollIntoView({ block: 'center' });
          const box = node.getBoundingClientRect();
          // The input lands in the visual viewport, which a page wider than the screen moves off
          // the layout viewport the box is measured in.
          const view = window.visualViewport || { offsetLeft: 0, offsetTop: 0 };
          return [box.left + box.width / 2 - view.offsetLeft, box.top + box.height / 2 - view.offsetTop];
        })()""" % element)
        for kind in ("mousePressed", "mouseReleased"):
            self.send("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left", "clickCount": 1})

    def width(self, width, height, mobile=False):
        self.send("Emulation.setDeviceMetricsOverride", {
            "width": width, "height": height, "deviceScaleFactor": 2 if mobile else 1, "mobile": mobile,
        })

    def requests(self):
        """Every URL this tab asked for, in order."""
        return [event["params"]["request"]["url"] for event in self._mine() if event.get("method") == "Network.requestWillBeSent"]

    def responses(self):
        """`{url: status}` of every response this tab received."""
        return {event["params"]["response"]["url"]: event["params"]["response"]["status"]
                for event in self._mine() if event.get("method") == "Network.responseReceived"}

    def console_errors(self):
        return [event["params"] for event in self._mine() if event.get("method") == "Runtime.exceptionThrown"]

    def close(self):
        try:
            self.browser.send("Target.closeTarget", {"targetId": self.target})
        except BrowserError:
            pass
