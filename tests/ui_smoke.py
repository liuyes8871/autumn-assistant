from pathlib import Path
import re
from urllib.parse import quote

from playwright.sync_api import expect, sync_playwright


BASE = "http://127.0.0.1:4173/"
FILE_ENTRY = Path("apps/web/index.html").resolve().as_uri()
ARTIFACTS = Path("artifacts")


def wait_for_vignette(page) -> None:
    """Wait for the route's hero art to settle before taking a screenshot.

    Hash navigation is handled inside the SPA, so Playwright's network-idle
    state can be reached before the newly mounted image fires ``load``. The
    component intentionally has a CSS fallback; accepting either settled
    state keeps screenshots deterministic without weakening the image
    loading contract.
    """
    page.wait_for_function(
        """() => {
          const art = document.querySelector('.vignette-art');
          return Boolean(art && (
            art.classList.contains('has-vignette-image') ||
            art.classList.contains('is-image-fallback')
          ));
        }""",
        timeout=5000,
    )


def main() -> None:
    with sync_playwright() as playwright:
        executable = Path(playwright.chromium.executable_path)
        if not executable.exists():
            candidates = sorted(Path.home().joinpath("AppData", "Local", "ms-playwright").glob("chromium-*/chrome-win*/chrome.exe"))
            if not candidates:
                raise RuntimeError("No local Chromium executable found; install Playwright browsers to run the UI smoke test.")
            executable = candidates[-1]
        browser = playwright.chromium.launch(headless=True, executable_path=str(executable))

        # Regression check for the original blank-screen report: opening the
        # source entry directly must land on the self-contained build.
        file_context = browser.new_context(viewport={"width": 1440, "height": 1000})
        file_page = file_context.new_page()
        file_page.goto(FILE_ENTRY, wait_until="domcontentloaded")
        file_page.wait_for_timeout(900)
        assert "/dist/index.html" in file_page.url
        # The local fallback catalog applies the same public audience gate as
        # the generated directory; four technical demo fixtures are hidden.
        expect(file_page.locator(".job-card")).to_have_count(12)
        file_context.close()

        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        page = context.new_page()
        page.goto(f"{BASE}#jobs", wait_until="networkidle")
        expect(page.get_by_role("heading", name="岗位", exact=True)).to_be_visible()
        wait_for_vignette(page)
        # The desktop masthead has one canonical settings entry.  A previous
        # pass rendered a second trigger on the right, which made the header
        # ambiguous and also changed its horizontal rhythm.
        expect(page.get_by_role("navigation", name="主导航").get_by_role("link", name="设置", exact=True)).to_have_count(1)
        expect(page.get_by_role("button", name="先看看岗位")).to_be_visible()
        page.get_by_role("button", name="先看看岗位").click()
        assert "—" not in page.locator("body").inner_text()
        assert page.locator(".section-kicker").count() == 0
        assert page.locator(".job-card").count() > 0
        expect(page.locator("select")).to_have_count(0)
        assert page.locator(".company-logo").count() >= 1
        # The brand seal is the single vermilion point in the boat mark.  Keep
        # both the image and fallback mark circular rather than letting a
        # square marker regress into the header.
        seal = page.locator(".brand-mark-image-seal, .brand-mark-seal").first
        expect(seal).to_be_visible()
        assert seal.evaluate("e => getComputedStyle(e).borderRadius") == "50%"
        # The Today rail was intentionally removed. Its three date meanings
        # remain as hero metrics, while the catalogue starts immediately below.
        expect(page.locator(".today-launch")).to_have_count(0)
        for label in ("今日开放校招", "今日发布岗位", "今日首次收录"):
            expect(page.get_by_text(label, exact=True).first).to_be_visible()
        # The desktop layout keeps the filter rail visible. Tablet/mobile
        # layouts move the same controls into a sheet behind this toggle.
        if page.locator(".filter-toggle").is_visible():
            page.locator(".filter-toggle").click()
        filter_panel = page.locator(".filter-panel")
        expect(filter_panel).to_be_visible()
        # Let the 220ms sheet entrance finish before measuring its fixed
        # geometry; otherwise the opening transform can report a transient
        # left edge while the panel is still sliding in.
        page.wait_for_timeout(260)
        assert filter_panel.evaluate("e => getComputedStyle(e).position") == "fixed"
        # The backdrop is only a click-to-dismiss interaction layer.  A prior
        # visual pass painted it with a translucent fill and blur, which made
        # the entire workbench look like a detached grey rectangle whenever
        # the filter sheet opened.  Keep the desktop contract explicit.
        filter_backdrop = page.locator(".filter-backdrop")
        expect(filter_backdrop).to_be_visible()
        backdrop_style = filter_backdrop.evaluate(
            """e => {
              const style = getComputedStyle(e);
              return {
                backgroundColor: style.backgroundColor,
                backgroundImage: style.backgroundImage,
                backdropFilter: style.backdropFilter,
                webkitBackdropFilter: style.webkitBackdropFilter,
              };
            }"""
        )
        assert backdrop_style["backgroundColor"] in {"rgba(0, 0, 0, 0)", "transparent"}
        assert backdrop_style["backgroundImage"] == "none"
        assert backdrop_style["backdropFilter"] == "none"
        # Chromium reports the prefixed declaration as ``null`` when the
        # property is unsupported; that is equivalent to no blur here.
        assert backdrop_style["webkitBackdropFilter"] in {None, "", "none"}
        initial_panel_box = filter_panel.bounding_box()
        assert initial_panel_box is not None
        panel_shape = filter_panel.evaluate(
            "e => ({ borderRadius: getComputedStyle(e).borderRadius, left: e.getBoundingClientRect().left })"
        )
        assert panel_shape["borderRadius"] == "18px"
        assert panel_shape["left"] > 0
        page.evaluate("window.scrollTo(0, 600)")
        page.wait_for_timeout(120)
        scrolled_panel_box = filter_panel.bounding_box()
        assert scrolled_panel_box is not None
        # The sheet is anchored to the viewport below the expanded masthead:
        # scrolling the catalogue must not carry it along or change its top.
        assert abs(scrolled_panel_box["y"] - initial_panel_box["y"]) < 2
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(120)
        restored_panel_box = filter_panel.bounding_box()
        assert restored_panel_box is not None
        assert abs(restored_panel_box["y"] - initial_panel_box["y"]) < 2
        page.get_by_role("button", name="选择省份").click()
        province_options = page.locator('.multi-select-option[role="option"]')
        if province_options.count() > 0:
            province_options.first.click()
            assert "全部省份" not in page.get_by_role("button", name="选择省份").inner_text()
        page.get_by_role("button", name="选择岗位类别").click()
        role_options = page.locator('.multi-select-option[role="option"]')
        if role_options.count() > 0:
            role_options.first.click()
            assert "全部类别" not in page.get_by_role("button", name="选择岗位类别").inner_text()
        page.keyboard.press("Escape")
        assert page.locator(".job-card").count() > 0
        page.get_by_role("button", name="清除筛选").click()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")

        # Company entries are a separate directory surface: searching a
        # company name can reveal an entry-only row even when no job has been
        # synchronised yet, while the explicit "only synced" toggle hides it.
        # ``type=search`` exposes the native ``searchbox`` role in Chromium;
        # keep the locator aligned with the semantic control rather than
        # weakening the input back to a plain text field.
        search = page.get_by_role("searchbox", name="搜索公司、岗位、城市或技能")
        search.fill("360")
        page.wait_for_timeout(180)
        expect(page.locator(".company-entry-row")).to_have_count(1)
        page.get_by_role("button", name="仅看已同步岗位").click()
        expect(page.locator(".company-entry-row")).to_have_count(0)
        page.get_by_role("button", name="包含仅入口公司").click()
        search.fill("")
        page.wait_for_timeout(180)
        page.evaluate("window.scrollTo(0, 0)")
        # Keep these artifacts to the requested viewport. A full-page capture
        # of a long virtualized catalogue can exceed Chromium's bitmap limit
        # and is not useful for responsive visual review.
        page.screenshot(path=str(ARTIFACTS / "jobs-1440.png"), full_page=False)

        first_card = page.locator(".job-card").first
        first_title = first_card.locator("h3").inner_text()
        first_href_id = first_card.get_attribute("data-job-id")
        first_card.click()
        dialog = page.locator('[role="dialog"]').first
        expect(dialog.get_by_role("heading", name=first_title)).to_be_visible()
        dialog.locator(".interest-button.suitable").click()
        dialog.get_by_role("button", name="去官网投递").click()
        expect(dialog.get_by_text("投递完成了吗？")).to_be_visible()
        dialog.get_by_role("button", name="暂不登记").click()
        dialog.get_by_role("combobox", name="投递阶段").click()
        page.get_by_role("option", name="已投递").click()
        page.get_by_role("button", name="关闭岗位详情").click()
        expect(page.locator(".job-modal")).to_have_count(0)
        page.wait_for_timeout(150)
        expect(page.locator(".job-modal")).to_have_count(0)

        if first_href_id:
            page.goto(f"{BASE}#jobs/{quote(first_href_id, safe='')}", wait_until="networkidle")
            expect(page.locator('.job-modal').get_by_role("heading", name=first_title)).to_be_visible()
            page.get_by_role("button", name="关闭岗位详情").click()

        page.goto(f"{BASE}#progress", wait_until="networkidle")
        expect(page.get_by_role("heading", name="进度", exact=True)).to_be_visible()
        wait_for_vignette(page)
        expect(page.get_by_text("总投递")).to_be_visible()
        expect(page.locator(".progress-card")).to_have_count(1)
        page.reload(wait_until="networkidle")
        expect(page.locator(".progress-card")).to_have_count(1)

        page.goto(f"{BASE}#schedule", wait_until="networkidle")
        expect(page.get_by_role("heading", name="日程", exact=True)).to_be_visible()
        wait_for_vignette(page)
        page.get_by_role("button", name="未来 7 天").last.click()
        expect(page.get_by_role("heading", name="未来 7 天")).to_be_visible()

        page.goto(f"{BASE}#settings", wait_until="networkidle")
        expect(page.get_by_role("heading", name="设置", exact=True)).to_be_visible()
        wait_for_vignette(page)
        expect(page.get_by_text("采集节奏")).to_be_visible()
        page.screenshot(path=str(ARTIFACTS / "settings-1440.png"), full_page=False)

        for width in (768, 1024):
            mid = browser.new_context(viewport={"width": width, "height": 900})
            mid_page = mid.new_page()
            mid_page.goto(f"{BASE}#jobs", wait_until="networkidle")
            wait_for_vignette(mid_page)
            if mid_page.get_by_role("button", name="先看看岗位").is_visible():
                mid_page.get_by_role("button", name="先看看岗位").click()
            assert mid_page.locator(".job-card").count() > 0
            assert mid_page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            mid_page.screenshot(path=str(ARTIFACTS / f"jobs-{width}.png"), full_page=False)
            mid.close()

        mobile = browser.new_context(viewport={"width": 375, "height": 812})
        mobile_page = mobile.new_page()
        mobile_page.goto(f"{BASE}#jobs", wait_until="networkidle")
        wait_for_vignette(mobile_page)
        if mobile_page.get_by_role("button", name="先看看岗位").is_visible():
            mobile_page.get_by_role("button", name="先看看岗位").click()
        expect(mobile_page.locator(".mobile-nav")).to_be_visible()
        assert mobile_page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        mobile_page.screenshot(path=str(ARTIFACTS / "jobs-375.png"), full_page=False)
        mobile.close()
        context.close()
        browser.close()


if __name__ == "__main__":
    main()
