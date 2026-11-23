"""Throwaway probe for issue 02: do Apollo and ContactOut work in the Dedicated profile under automation?

Usage (from the repo root, venv active):
    python .scratch/job-driven-outreach/probe_extensions.py strict  <linkedin-profile-url>
    python .scratch/job-driven-outreach/probe_extensions.py relaxed <linkedin-profile-url>

strict  = today's filter (LinkedIn only) but with extensions enabled: shows what the filter blocks.
relaxed = proposed filter: subresources to apollo.io / contactout.com / chrome-extension:// allowed,
          top-level navigation still LinkedIn-only.
open    = NO filter at all (requests only observed), Playwright's default flags otherwise.
bare    = NO filter and none of Playwright's default Chrome flags (no --enable-automation).
open/bare are diagnosis-only: stay on LinkedIn while using them.
sidepanel = relaxed filter + a localhost DevTools port; clicks Apollo's in-page launcher, then
          reports whether Apollo's side panel opened and whether Playwright can reach/read it.

Every non-LinkedIn request is appended to .scratch/job-driven-outreach/probe-<mode>-requests.log
(URL truncated at the path, no query string, so revealed emails don't end up in the log).
The script then opens the Playwright Inspector (page.pause()) so you can click around and use
"Pick locator" on the extension panels. Close the Inspector / press Resume to exit.
"""

from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from linkreach.browser import guard_profile_dir, host_allowed
from linkreach.config import resolve_profile_dir

HERE = Path(__file__).parent
EXTENSION_HOST_SUFFIXES = ("apollo.io", "contactout.com")


def ext_allowed(url: str) -> bool:
    parts = urlsplit(url)
    if parts.scheme == "chrome-extension":
        return True
    host = (parts.hostname or "").lower().rstrip(".")
    return any(host == s or host.endswith("." + s) for s in EXTENSION_HOST_SUFFIXES)


EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
PHONE_RE = re.compile(r"\+?\d[\d ().-]{6,}\d")


def redact(text: str) -> str:
    return PHONE_RE.sub("<phone>", EMAIL_RE.sub("<email>", text))


def dump_frames(page) -> Path:
    """Save every iframe's attributes and every extension frame's HTML (emails/phones redacted)
    to ~/.linkreach/probe/, outside the repo. Run this while the panels show the state you want."""
    out = Path.home() / ".linkreach" / "probe" / datetime.now().strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True, exist_ok=True)
    lines = []
    iframes = page.locator("iframe")
    for i in range(iframes.count()):
        el = iframes.nth(i)
        attrs = {a: el.get_attribute(a) for a in ("id", "name", "class", "title", "src", "style")}
        lines.append(f"iframe[{i}] " + " ".join(f'{k}="{redact(v)}"' for k, v in attrs.items() if v))
    (out / "iframes.txt").write_text("\n".join(lines), encoding="utf-8")
    for i, fr in enumerate(page.frames):
        if fr == page.main_frame or not (ext_allowed(fr.url)):
            continue
        host = urlsplit(fr.url).hostname or "ext"
        try:
            html = fr.content()
        except Exception as exc:
            html = f"<!-- could not read: {type(exc).__name__} -->"
        (out / f"frame{i}-{host}.html").write_text(f"<!-- {fr.url.split('?')[0]} -->\n" + redact(html), encoding="utf-8")
    print(f"Saved iframe list and extension-frame HTML (emails/phones redacted) to {out}")
    return out


APOLLO_ID = "alhgpfoeiimagjlnfekdhkjlkiomcapa"
APOLLO_LAUNCHER = '[data-cy="apollo-opener-icon-new"] button[aria-label="Toggle Apollo side panel"]'


def click_apollo_launcher(page) -> None:
    """Click Apollo's in-page launcher (inside an open shadow root) the way linkreach would."""
    loc = page.locator(APOLLO_LAUNCHER).first
    try:
        loc.wait_for(state="visible", timeout=15000)
        loc.click(timeout=5000)
        print("Clicked Apollo's in-page launcher.")
    except Exception as exc:
        print(f"Couldn't click Apollo's launcher: {type(exc).__name__}: {str(exc)[:200]}")


def inspect_side_panel(pw, ctx, profile_dir: Path, out: Path | None) -> None:
    """Find Apollo's side panel via Playwright and via the DevTools target list; dump its HTML if reachable."""
    import json
    import urllib.request

    report = ["Playwright ctx.pages:"] + [f"  {p.url.split('?')[0]}" for p in ctx.pages]
    try:
        port = (profile_dir / "DevToolsActivePort").read_text().splitlines()[0].strip()
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=5) as r:  # nosec B310: localhost
            targets = json.load(r)
        report.append("DevTools targets:")
        report += [f"  {t.get('type')}\t{t.get('url', '').split('?')[0]}" for t in targets]
    except Exception as exc:
        port = None
        report.append(f"DevTools target list unavailable: {type(exc).__name__}")

    panel_pages = [p for p in ctx.pages if APOLLO_ID in p.url]
    if not panel_pages and port:
        try:
            browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            report.append("Pages seen via connect_over_cdp:")
            for c in browser.contexts:
                for p in c.pages:
                    report.append(f"  {p.url.split('?')[0]}")
                    if APOLLO_ID in p.url:
                        panel_pages.append(p)
        except Exception as exc:
            report.append(f"connect_over_cdp failed: {type(exc).__name__}: {str(exc)[:200]}")

    report.append(f"Apollo extension pages reachable from Playwright: {len(panel_pages)}")
    if out is not None:
        for n, p in enumerate(panel_pages):
            for i, fr in enumerate(p.frames):
                try:
                    html = fr.content()
                except Exception as exc:
                    html = f"<!-- could not read: {type(exc).__name__} -->"
                (out / f"apollo-panel{n}-frame{i}.html").write_text(
                    f"<!-- {fr.url.split('?')[0]} -->\n" + redact(html), encoding="utf-8"
                )
        (out / "side-panel-report.txt").write_text("\n".join(report), encoding="utf-8")
    print("\n".join(report))


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in {"strict", "relaxed", "open", "bare", "sidepanel"}:
        print(__doc__)
        return 2
    mode, profile_url = sys.argv[1], sys.argv[2]
    if not host_allowed(profile_url):
        print("Profile URL must be on linkedin.com")
        return 2

    profile_dir = resolve_profile_dir("~/.linkreach/chrome-profile")
    guard_profile_dir(profile_dir)
    log_path = HERE / f"probe-{mode}-requests.log"
    log = log_path.open("w", encoding="utf-8")
    console_log = (HERE / f"probe-{mode}-console.log").open("w", encoding="utf-8")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            channel="chrome",
            headless=False,
            viewport=None if mode == "bare" else {"width": 1280, "height": 900},
            # bare: drop ALL of Playwright's default Chrome flags (incl. --enable-automation)
            ignore_default_args=True if mode == "bare" else ["--disable-extensions"],
            chromium_sandbox=True,  # Playwright adds --no-sandbox unless this is set
            # sidepanel: localhost-only DevTools port (random) so we can list targets Playwright hides
            args=["--remote-debugging-port=0"] if mode == "sidepanel" else [],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        def on_console(msg):
            text = msg.text
            if msg.type in {"error", "warning"} or "apollo" in text.lower():
                console_log.write(f"{msg.type}\t{redact(text)[:300]}\n")
                console_log.flush()

        page.on("console", on_console)

        def observe(request):  # open/bare: no filter, just record non-LinkedIn requests
            url = request.url
            if host_allowed(url) or url.startswith("chrome-extension://invalid"):
                return
            p = urlsplit(url)
            log.write(f"SEEN\t-\t{request.resource_type}\t{p.scheme}://{p.hostname or ''}{p.path[:60]}\n")
            log.flush()

        def route(r, request):
            url = request.url
            if host_allowed(url):
                r.continue_()
                return
            try:
                is_top = request.is_navigation_request() and request.frame == page.main_frame
            except Exception:
                is_top = False
            p = urlsplit(url)
            short = f"{p.scheme}://{p.hostname or ''}{p.path[:60]}"
            allow = mode in {"relaxed", "sidepanel"} and ext_allowed(url) and not is_top
            log.write(f"{'ALLOW' if allow else 'BLOCK'}\t{'TOP' if is_top else 'sub'}\t{request.resource_type}\t{short}\n")
            log.flush()
            r.continue_() if allow else r.abort()

        if mode in {"strict", "relaxed", "sidepanel"}:
            ctx.route("**/*", route)
        else:
            ctx.on("request", observe)

        exts = [w.url for w in ctx.service_workers] + [p.url for p in ctx.background_pages]
        print("Extension workers seen at launch:", exts or "none yet (may appear after the page loads)")

        page.goto(profile_url, wait_until="domcontentloaded", timeout=45000)
        print(f"Opened {page.url}\nLogging non-LinkedIn requests to {log_path}")
        if mode == "sidepanel":
            click_apollo_launcher(page)
            page.wait_for_timeout(5000)
            inspect_side_panel(pw, ctx, profile_dir, None)
        print("Inspector opening. Set the panels to a state, then press Resume to snapshot it.")
        try:
            while True:
                page.pause()
                out = dump_frames(page)
                if mode == "sidepanel":
                    inspect_side_panel(pw, ctx, profile_dir, out)
                if input("Snapshot another state? Type y + Enter, then press Resume when ready; Enter alone to finish: ").strip().lower() != "y":
                    break
            exts = [w.url for w in ctx.service_workers] + [p.url for p in ctx.background_pages]
            print("Extension workers seen at exit:", exts or "none")
            ctx.close()
        except Exception as exc:  # you closed the browser window first: fine
            print(f"Browser already closed ({type(exc).__name__}).")
    log.close()
    console_log.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
