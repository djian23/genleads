import logging
import random
import re
import urllib.parse
from collections.abc import AsyncGenerator

from playwright.async_api import async_playwright

from app.config import settings

logger = logging.getLogger(__name__)

# Google Maps CSS selectors (centralized for easy maintenance)
SELECTORS = {
    "feed": 'div[role="feed"]',
    "listing_link": "a.hfpxzc",
    "name": "h1.DUwDvf",
    "rating": 'div.F7nice span[aria-hidden="true"]',
    "reviews_aria": "div.F7nice span[aria-label]",
    "address": 'button[data-item-id="address"]',
    "phone": 'button[data-item-id*="phone"]',
    "website": 'a[data-item-id="authority"]',
}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)


def build_search_url(business_type: str, location: str) -> str:
    query = f"{business_type} {location}"
    encoded = urllib.parse.quote(query)
    return f"https://www.google.com/maps/search/{encoded}/"


async def _dismiss_cookie_consent(page) -> None:
    """Dismiss the Google cookie consent banner if it appears."""
    for text in ["Tout accepter", "Accept all", "Accepter tout"]:
        try:
            btn = page.locator("button", has_text=text)
            if await btn.count() > 0:
                await btn.first.click()
                await page.wait_for_timeout(1500)
                return
        except Exception:
            continue


async def _random_delay(page) -> None:
    """Wait a random amount of time to appear human-like."""
    delay = random.randint(
        int(settings.SCRAPE_DELAY_MIN * 1000),
        int(settings.SCRAPE_DELAY_MAX * 1000),
    )
    await page.wait_for_timeout(delay)


async def _scroll_and_collect_urls(page, max_results: int) -> list[str]:
    """Scroll the Google Maps results feed and collect listing URLs."""
    await page.wait_for_selector(SELECTORS["feed"], timeout=15000)

    previous_count = 0
    for _ in range(settings.MAX_SCROLL_COUNT):
        listings = page.locator(SELECTORS["listing_link"])
        current_count = await listings.count()

        if current_count >= max_results:
            break

        # Check for end-of-list markers
        for end_text in [
            "Vous avez atteint la fin",
            "You've reached the end",
        ]:
            end_marker = page.locator("p.fontBodyMedium span", has_text=end_text)
            if await end_marker.count() > 0:
                logger.info("Reached end of results list")
                break
        else:
            # No end marker found, check if we're stuck
            if current_count == previous_count and current_count > 0:
                logger.info("No new results loaded, stopping scroll")
                break

            previous_count = current_count

            # Scroll the feed down
            feed = page.locator(SELECTORS["feed"])
            await feed.evaluate("el => el.scrollTop = el.scrollHeight")
            await _random_delay(page)
            continue

        # End marker was found (break in the for loop)
        break

    # Collect URLs
    listings = page.locator(SELECTORS["listing_link"])
    count = min(await listings.count(), max_results)
    urls = []
    for i in range(count):
        href = await listings.nth(i).get_attribute("href")
        if href:
            urls.append(href)
    return urls


async def _extract_listing_details(page, url: str) -> dict:
    """Navigate to a listing detail page and extract business information."""
    await page.goto(url, wait_until="networkidle", timeout=30000)
    await _random_delay(page)

    lead = {"google_maps_url": url}

    # Business name
    try:
        name_el = page.locator(SELECTORS["name"])
        lead["name"] = await name_el.inner_text(timeout=5000)
    except Exception:
        lead["name"] = "Inconnu"

    # Rating
    try:
        rating_el = page.locator(SELECTORS["rating"]).first
        text = await rating_el.inner_text(timeout=3000)
        lead["rating"] = float(text.replace(",", "."))
    except Exception:
        lead["rating"] = None

    # Reviews count
    try:
        reviews_el = page.locator(SELECTORS["reviews_aria"]).first
        aria = await reviews_el.get_attribute("aria-label") or ""
        nums = re.findall(r"[\d\s,.]+", aria)
        if nums:
            clean = nums[0].replace(",", "").replace(".", "").replace(" ", "").replace("\u202f", "").strip()
            if clean:
                lead["reviews_count"] = int(clean)
            else:
                lead["reviews_count"] = None
        else:
            lead["reviews_count"] = None
    except Exception:
        lead["reviews_count"] = None

    # Address
    try:
        address_btn = page.locator(SELECTORS["address"])
        if await address_btn.count() > 0:
            aria = await address_btn.first.get_attribute("aria-label") or ""
            # Remove prefix like "Adresse : " or "Address: "
            lead["address"] = re.sub(r"^(Adresse\s*:\s*|Address:\s*)", "", aria).strip() or None
        else:
            lead["address"] = None
    except Exception:
        lead["address"] = None

    # Phone
    try:
        phone_btn = page.locator(SELECTORS["phone"])
        if await phone_btn.count() > 0:
            aria = await phone_btn.first.get_attribute("aria-label") or ""
            lead["phone"] = re.sub(
                r"^(Téléphone\s*:\s*|Phone:\s*|Numéro de téléphone\s*:\s*)", "", aria
            ).strip() or None
        else:
            lead["phone"] = None
    except Exception:
        lead["phone"] = None

    # Website
    try:
        website_link = page.locator(SELECTORS["website"])
        if await website_link.count() > 0:
            lead["website"] = await website_link.first.get_attribute("href")
        else:
            lead["website"] = None
    except Exception:
        lead["website"] = None

    return lead


async def scrape_google_maps(
    business_type: str,
    location: str,
    max_results: int,
) -> AsyncGenerator[dict, None]:
    """
    Scrape Google Maps for business listings.

    Yields one lead dict at a time for real-time progress tracking.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=settings.HEADLESS)
        context = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="fr-FR",
            user_agent=USER_AGENT,
        )
        page = await context.new_page()

        try:
            # Navigate to Google Maps search
            url = build_search_url(business_type, location)
            logger.info(f"Navigating to: {url}")
            await page.goto(url, wait_until="networkidle", timeout=30000)

            # Handle cookie consent
            await _dismiss_cookie_consent(page)

            # Scroll and collect listing URLs
            listing_urls = await _scroll_and_collect_urls(page, max_results)
            logger.info(f"Found {len(listing_urls)} listing URLs")

            if not listing_urls:
                logger.warning("No listings found for this search")
                return

            # Visit each listing and extract details
            for i, listing_url in enumerate(listing_urls):
                try:
                    logger.info(f"Scraping listing {i + 1}/{len(listing_urls)}")
                    lead = await _extract_listing_details(page, listing_url)
                    yield lead
                except Exception as e:
                    logger.warning(f"Failed to scrape listing {i + 1}: {e}")
                    continue

        finally:
            await browser.close()
