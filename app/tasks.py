import asyncio
import logging
from datetime import datetime
from functools import partial

from app.database import async_session
from app.models import Job, Lead
from app.scraper import scrape_google_maps_sync

logger = logging.getLogger(__name__)


def _run_scraper(business_type: str, location: str, requested_count: int) -> list[dict]:
    """Run the synchronous Playwright scraper (called from a thread)."""
    return scrape_google_maps_sync(business_type, location, requested_count)


async def run_scrape_job(job_id: str) -> None:
    """Run a scraping job in the background, updating progress in the database."""
    async with async_session() as session:
        job = await session.get(Job, job_id)
        if not job:
            logger.error(f"Job {job_id} not found")
            return

        job.status = "running"
        await session.commit()

        try:
            # Run Playwright in a thread to avoid Windows asyncio subprocess issue
            loop = asyncio.get_event_loop()
            leads_data = await loop.run_in_executor(
                None,
                partial(
                    _run_scraper,
                    job.business_type,
                    job.location,
                    job.requested_count,
                ),
            )

            # Save all leads to the database
            for lead_data in leads_data:
                lead = Lead(job_id=job_id, **lead_data)
                session.add(lead)
                job.progress += 1
                await session.commit()

            job.status = "completed"
            job.completed_at = datetime.utcnow()
            logger.info(f"Job {job_id} completed with {job.progress} leads")

        except Exception as e:
            logger.error(f"Job {job_id} failed: {e}")
            job.status = "failed"
            job.error_message = str(e)

        await session.commit()
