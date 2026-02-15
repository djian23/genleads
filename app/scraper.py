import logging
import random
import re
import urllib.parse

from playwright.sync_api import sync_playwright

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


def _dismiss_cookie_consent(page) -> None:
    """Dismiss the Google cookie consent banner if it appears."""
    for text in ["Tout accepter", "Accept all", "Accepter tout"]:
        try:
            btn = page.locator("button", has_text=text)
            if btn.count() > 0:
                btn.first.click()
                page.wait_for_timeout(1500)
                return
        except Exception:
            continue


def _random_delay(page) -> None:
    """Wait a random amount of time to appear human-like."""
    delay = random.randint(
        int(settings.SCRAPE_DELAY_MIN * 1000),
        int(settings.SCRAPE_DELAY_MAX * 1000),
    )
    page.wait_for_timeout(delay)


def _scroll_and_collect_urls(page, max_results: int) -> list[str]:
    """Scroll the Google Maps results feed and collect listing URLs."""
    page.wait_for_selector(SELECTORS["feed"], timeout=15000)

    previous_count = 0
    for _ in range(settings.MAX_SCROLL_COUNT):
        listings = page.locator(SELECTORS["listing_link"])
        current_count = listings.count()

        if current_count >= max_results:
            break

        # Check for end-of-list markers
        for end_text in [
            "Vous avez atteint la fin",
            "You've reached the end",
        ]:
            end_marker = page.locator("p.fontBodyMedium span", has_text=end_text)
            if end_marker.count() > 0:
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
            feed.evaluate("el => el.scrollTop = el.scrollHeight")
            _random_delay(page)
            continue

        # End marker was found (break in the for loop)
        break

    # Collect URLs
    listings = page.locator(SELECTORS["listing_link"])
    count = min(listings.count(), max_results)
    urls = []
    for i in range(count):
        href = listings.nth(i).get_attribute("href")
        if href:
            urls.append(href)
    return urls


def _extract_listing_details(page, url: str) -> dict:
    """Navigate to a listing detail page and extract business information."""
    page.goto(url, wait_until="networkidle", timeout=30000)
    _random_delay(page)

    lead = {"google_maps_url": url}

    # Business name
    try:
        name_el = page.locator(SELECTORS["name"])
        lead["name"] = name_el.inner_text(timeout=5000)
    except Exception:
        lead["name"] = "Inconnu"

    # Rating
    try:
        rating_el = page.locator(SELECTORS["rating"]).first
        text = rating_el.inner_text(timeout=3000)
        lead["rating"] = float(text.replace(",", "."))
    except Exception:
        lead["rating"] = None

    # Reviews count
    try:
        reviews_el = page.locator(SELECTORS["reviews_aria"]).first
        aria = reviews_el.get_attribute("aria-label") or ""
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
        if address_btn.count() > 0:
            aria = address_btn.first.get_attribute("aria-label") or ""
            lead["address"] = re.sub(r"^(Adresse\s*:\s*|Address:\s*)", "", aria).strip() or None
        else:
            lead["address"] = None
    except Exception:
        lead["address"] = None

    # Phone
    try:
        phone_btn = page.locator(SELECTORS["phone"])
        if phone_btn.count() > 0:
            aria = phone_btn.first.get_attribute("aria-label") or ""
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
        if website_link.count() > 0:
            lead["website"] = website_link.first.get_attribute("href")
        else:
            lead["website"] = None
    except Exception:
        lead["website"] = None

    return lead


def scrape_google_maps_sync(
    business_type: str,
    location: str,
    max_results: int,
    on_lead: callable = None,
) -> list[dict]:
    """
    Scrape Google Maps for business listings (synchronous version).

    Calls on_lead(lead_dict) after each lead is scraped for progress tracking.
    Returns the full list of leads at the end.
    """
    leads = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=settings.HEADLESS)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            locale="fr-FR",
            user_agent=USER_AGENT,
        )
        page = context.new_page()

        try:
            # Navigate to Google Maps search
            url = build_search_url(business_type, location)
            logger.info(f"Navigating to: {url}")
            page.goto(url, wait_until="networkidle", timeout=30000)

            # Handle cookie consent
            _dismiss_cookie_consent(page)

            # Scroll and collect listing URLs
            listing_urls = _scroll_and_collect_urls(page, max_results)
            logger.info(f"Found {len(listing_urls)} listing URLs")

            if not listing_urls:
                logger.warning("No listings found for this search")
                return leads

            # Visit each listing and extract details
            for i, listing_url in enumerate(listing_urls):
                try:
                    logger.info(f"Scraping listing {i + 1}/{len(listing_urls)}")
                    lead = _extract_listing_details(page, listing_url)
                    leads.append(lead)
                    if on_lead:
                        on_lead(lead)
                except Exception as e:
                    logger.warning(f"Failed to scrape listing {i + 1}: {e}")
                    continue

        finally:
            browser.close()

    return leads
