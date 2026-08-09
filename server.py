import argparse
import asyncio
import os
import random
from contextlib import asynccontextmanager
from typing import Literal, Optional
from urllib.parse import urlsplit

from fastmcp import FastMCP

from camoufox.async_api import AsyncCamoufox
from DrissionPage import ChromiumPage, ChromiumOptions

from config import get_config

_cfg = get_config()
PROXIES_FILE = _cfg.proxy.file


def parse_proxy(url: str) -> dict:
    parts = urlsplit(url)
    return {
        "server": f"{parts.scheme}://{parts.hostname}:{parts.port}",
        "username": parts.username or "",
        "password": parts.password or "",
    }


class ProxyManager:
    def __init__(self):
        self.proxies: list[str] = []
        self.enabled: bool = False
        self.current: Optional[str] = None

    def load(self, path: str = PROXIES_FILE) -> None:
        try:
            with open(path, encoding="utf-8") as fh:
                self.proxies = [ln.strip() for ln in fh if ln.strip()]
        except OSError:
            self.proxies = []

    def pick(self, url: Optional[str] = None) -> str:
        if url:
            self.current = url
        elif self.proxies:
            self.current = random.choice(self.proxies)
        return self.current or ""

    def spec(self) -> Optional[dict]:
        if not self.enabled or not self.current:
            return None
        return parse_proxy(self.current)


class BrowserManager:
    def __init__(self, cfg=None):
        global _cfg
        self.cfg = cfg or _cfg
        self.active_engine: Literal["camoufox", "drissionpage"] = (
            "camoufox" if self.cfg.camoufox_browser.enabled else "drissionpage"
        )
        self.drission_enabled: bool = self.cfg.drissionpage_browser.enabled
        self.proxy = ProxyManager()
        self.proxy.load()

        self.camoufox_cm = None
        self.camoufox_browser = None
        self.camoufox_page = None
        self.browser_use_session = None
        self.browser_use_headless: bool = self.cfg.browser_use.headless
        self.drission_page: Optional[ChromiumPage] = None

    async def init_camoufox(self):
        if not self.camoufox_page:
            fb = self.cfg.camoufox_browser
            launch = {
                "headless": fb.headless,
                "geoip": fb.geoip,
                "humanize": fb.humanize,
                "locale": fb.locale,
                "args": fb.args,
                **fb.options,
            }
            launch = {k: v for k, v in launch.items() if v not in (None, "")}
            if self.proxy.spec():
                launch["proxy"] = self.proxy.spec()
            self.camoufox_cm = AsyncCamoufox(**launch)
            self.camoufox_browser = await self.camoufox_cm.__aenter__()
            self.camoufox_page = await self.camoufox_browser.new_page()

    def init_drissionpage(self):
        if not self.drission_page:
            dp = self.cfg.drissionpage_browser
            co = ChromiumOptions()
            co.set_headless(dp.headless)
            if dp.browser_path:
                co.set_browser_path(dp.browser_path)
            if dp.user_data_dir:
                co.set_user_data_path(dp.user_data_dir)
            if dp.local_port:
                co.set_local_port(int(dp.local_port))
            for arg in dp.args:
                co.set_argument(arg)
            if self.proxy.spec():
                co.set_proxy(self.proxy.current)
            self.drission_page = ChromiumPage(co)

    async def init_browser_use(self, headless: bool = True):
        from browser_use.browser.profile import ProxySettings
        from browser_use.browser.session import BrowserSession

        if self.browser_use_session and self.browser_use_headless != headless:
            await self.browser_use_session.stop()
            self.browser_use_session = None
        if not self.browser_use_session:
            proxy = ProxySettings(**self.proxy.spec()) if self.proxy.spec() else None
            self.browser_use_session = BrowserSession(headless=headless, proxy=proxy, is_local=True)
            self.browser_use_headless = headless
            await self.browser_use_session.start()

    async def close_all(self):
        if self.camoufox_cm:
            await self.camoufox_cm.__aexit__(None, None, None)
            self.camoufox_cm = None
            self.camoufox_browser = None
            self.camoufox_page = None
        if self.browser_use_session:
            await self.browser_use_session.stop()
            self.browser_use_session = None
        if self.drission_page:
            self.drission_page.quit()
            self.drission_page = None


browser_mgr = BrowserManager()


@asynccontextmanager
async def lifespan(server: FastMCP):
    yield
    await browser_mgr.close_all()


mcp = FastMCP("Multi-Browser Automation Server", lifespan=lifespan)


def build_llm():
    from browser_use.llm.models import ChatOpenAI

    from config import load_llm_credentials

    base_url, api_key, model = load_llm_credentials(browser_mgr.cfg)
    if not model:
        model = browser_mgr.cfg.browser_use.model
    if base_url and not base_url.endswith("/v1"):
        base_url = base_url.rstrip("/") + "/v1"
    if not api_key:
        raise RuntimeError(
            "Browser Use cần LLM. Đặt OPENAI_API_KEY hoặc NINEROUTER_KEY/NINEROUTER_URL (và BROWSER_USE_MODEL nếu cần), "
            "hoặc cấu hình credential block trong config.kdl."
        )
    return ChatOpenAI(model=model, api_key=api_key, base_url=base_url)


@mcp.tool()
async def set_active_engine(engine: Literal["camoufox", "drissionpage"]) -> str:
    """Đổi engine browser hiện tại để thực thi tác vụ duyệt web cấp thấp.

    Args:
        engine: 'camoufox' hoặc 'drissionpage'
    """
    if engine == "drissionpage" and not browser_mgr.drission_enabled:
        return "Lỗi: DrissionPage hiện đang bị tắt. Hãy gọi tool `enable_drissionpage(True)` trước."
    browser_mgr.active_engine = engine
    return f"Đã chuyển engine hoạt động sang: {engine}"


@mcp.tool()
async def enable_drissionpage(enable: bool) -> str:
    """Bật hoặc tắt khả năng sử dụng DrissionPage (mặc định là Tắt)."""
    browser_mgr.drission_enabled = enable
    if not enable and browser_mgr.active_engine == "drissionpage":
        browser_mgr.active_engine = "camoufox"
        if browser_mgr.drission_page:
            browser_mgr.drission_page.quit()
            browser_mgr.drission_page = None
        return "Đã tắt DrissionPage. Tự động chuyển active engine về Camoufox."
    status = "Bật" if enable else "Tắt"
    return f"Đã {status} tính năng DrissionPage."


@mcp.tool()
async def set_proxy(enable: bool, proxy: Optional[str] = None) -> str:
    """Bật/tắt sử dụng proxy datacenter (mặc định là TẮT).

    Khi bật và không truyền `proxy`, server chọn ngẫu nhiên một proxy từ proxies.txt.
    Nếu browser đang chạy, nó sẽ được đóng để lần truy cập sau khởi động lại với proxy mới.

    Args:
        enable: True để dùng proxy, False để tắt (truy cập trực tiếp).
        proxy: URL proxy tuỳ chọn, ví dụ http://user:pass@host:port. Bỏ trống để lấy ngẫu nhiên từ proxies.txt.
    """
    if enable:
        chosen = browser_mgr.proxy.pick(proxy)
        if not chosen:
            return "Lỗi: Không tìm thấy proxy trong proxies.txt và không truyền `proxy`."
        browser_mgr.proxy.enabled = True
        if browser_mgr.camoufox_cm or browser_mgr.drission_page or browser_mgr.browser_use_session:
            await browser_mgr.close_all()
        return f"Đã bật proxy: {chosen}"
    browser_mgr.proxy.enabled = False
    if browser_mgr.camoufox_cm or browser_mgr.drission_page or browser_mgr.browser_use_session:
        await browser_mgr.close_all()
    return "Đã tắt proxy. Browser sẽ truy cập trực tiếp."


@mcp.tool()
async def get_proxy_status() -> str:
    """Xem trạng thái proxy hiện tại."""
    if not browser_mgr.proxy.enabled:
        return f"Proxy: TẮT. Pool có {len(browser_mgr.proxy.proxies)} proxy."
    return f"Proxy: BẬT. Đang dùng: {browser_mgr.proxy.current or 'chưa chọn'} (pool {len(browser_mgr.proxy.proxies)})."


@mcp.tool()
async def navigate(url: str) -> str:
    """Mở một trang web theo URL truyền vào."""
    engine = browser_mgr.active_engine
    try:
        if engine == "camoufox":
            await browser_mgr.init_camoufox()
            await browser_mgr.camoufox_page.goto(url)
            title = await browser_mgr.camoufox_page.title()
            return f"[Camoufox] Đã truy cập thành công {url}. Tiêu đề: {title}"
        elif engine == "drissionpage":
            if not browser_mgr.drission_enabled:
                return "DrissionPage chưa được bật."
            loop = asyncio.get_event_loop()

            def _drission_nav():
                browser_mgr.init_drissionpage()
                browser_mgr.drission_page.get(url)
                return browser_mgr.drission_page.title

            title = await loop.run_in_executor(None, _drission_nav)
            return f"[DrissionPage] Đã truy cập thành công {url}. Tiêu đề: {title}"
    except Exception as e:
        return f"Lỗi khi truy cập {url} với {engine}: {str(e)}"


@mcp.tool()
async def get_page_source() -> str:
    """Lấy toàn bộ HTML nội dung của trang hiện tại (đã cắt bớt)."""
    engine = browser_mgr.active_engine
    if engine == "camoufox":
        if not browser_mgr.camoufox_page:
            return "Camoufox chưa khởi tạo trang nào."
        content = await browser_mgr.camoufox_page.content()
        return content[:2000] + "\n... (đã cắt bớt nội dung)"
    elif engine == "drissionpage":
        if not browser_mgr.drission_page:
            return "DrissionPage chưa khởi tạo trang nào."
        content = browser_mgr.drission_page.html
        return content[:2000] + "\n... (đã cắt bớt nội dung)"


@mcp.tool()
async def click_element(selector: str) -> str:
    """Click vào một phần tử trên trang dựa theo CSS Selector hoặc Xpath.

    Args:
        selector: CSS Selector (Camoufox/DrissionPage) hoặc Xpath
    """
    engine = browser_mgr.active_engine
    try:
        if engine == "camoufox":
            if not browser_mgr.camoufox_page:
                return "Trang chưa mở."
            await browser_mgr.camoufox_page.click(selector)
            return f"[Camoufox] Đã click vào element: {selector}"
        elif engine == "drissionpage":
            if not browser_mgr.drission_page:
                return "Trang chưa mở."
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: browser_mgr.drission_page.ele(selector).click())
            return f"[DrissionPage] Đã click vào element: {selector}"
    except Exception as e:
        return f"Lỗi click element: {str(e)}"


@mcp.tool()
async def run_browser_use(task: str, max_steps: int = 25, headless: Optional[bool] = None) -> str:
    """Chạy một tác vụ tự động bằng AI agent (browser-use).

    Agent điều khiển trình duyệt Chromium để hoàn thành tác vụ phức tạp nhiều bước
    (đăng nhập, điền form, thu thập dữ liệu...). Cần LLM: cấu hình qua credential
    block trong config.kdl (method config/dotenv/env).

    Args:
        task: Mô tả tác vụ cần thực hiện bằng ngôn ngữ tự nhiên.
        max_steps: Số bước tối đa agent được phép thực hiện.
        headless: True để chạy ẩn, False để hiện cửa sổ browser (mặc định lấy từ config).
    """
    try:
        if headless is None:
            headless = browser_mgr.cfg.browser_use.headless
        await browser_mgr.init_browser_use(headless=headless)
        from browser_use import Agent

        agent = Agent(task=task, llm=build_llm(), browser_session=browser_mgr.browser_use_session)
        history = await agent.run(max_steps=max_steps)
        return history.final_result() or "Agent đã hoàn thành nhưng không có kết quả văn bản."
    except Exception as e:
        return f"Lỗi khi chạy Browser Use: {str(e)}"


@mcp.tool()
async def close_browser() -> str:
    """Đóng tất cả các trình duyệt đang mở."""
    await browser_mgr.close_all()
    return "Đã đóng tất cả các trình duyệt thành công."


def main():
    parser = argparse.ArgumentParser(description="Multi-browser automation MCP server (FastMCP).")
    parser.add_argument("--host", default=_cfg.server.host)
    parser.add_argument("--port", type=int, default=_cfg.server.port)
    parser.add_argument(
        "--transport", choices=["sse", "http", "streamable-http", "stdio"], default=_cfg.server.transport
    )
    args = parser.parse_args()
    if args.transport == "stdio":
        mcp.run(transport="stdio")
    else:
        mcp.run(transport=args.transport, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
