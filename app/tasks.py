import logging
from datetime import datetime

from app.database import async_session
from app.models import Job, Lead
from app.scraper import scrape_google_maps

logger = logging.getLogger(__name__)


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
            async for lead_data in scrape_google_maps(
                job.business_type,
                job.location,
                job.requested_count,
            ):
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
