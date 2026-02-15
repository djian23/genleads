import asyncio
import logging

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from app.csv_export import generate_csv
from app.database import async_session, init_db
from app.models import Job, Lead
from app.tasks import run_scrape_job

logging.basicConfig(level=logging.INFO)

app = FastAPI(title="GenLeads - Google Maps Lead Scraper")
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.on_event("startup")
async def startup():
    await init_db()


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/api/scrape", response_class=HTMLResponse)
async def start_scrape(
    request: Request,
    business_type: str = Form(...),
    location: str = Form(...),
    requested_count: int = Form(...),
):
    # Clamp requested_count
    requested_count = max(1, min(requested_count, 200))

    # Create job
    job = Job(
        business_type=business_type,
        location=location,
        requested_count=requested_count,
    )
    async with async_session() as session:
        session.add(job)
        await session.commit()
        await session.refresh(job)
        job_id = job.id

    # Launch background scraping task
    asyncio.create_task(run_scrape_job(job_id))

    # Return initial polling partial
    async with async_session() as session:
        job = await session.get(Job, job_id)
        return templates.TemplateResponse(
            "partials/job_status.html",
            {"request": request, "job": job, "leads": []},
        )


@app.get("/api/jobs/{job_id}/status", response_class=HTMLResponse)
async def job_status(request: Request, job_id: str):
    async with async_session() as session:
        job = await session.get(Job, job_id)
        if not job:
            return HTMLResponse("<p>Job introuvable.</p>", status_code=404)

        result = await session.execute(
            select(Lead).where(Lead.job_id == job_id)
        )
        leads = result.scalars().all()

    return templates.TemplateResponse(
        "partials/job_status.html",
        {"request": request, "job": job, "leads": leads},
    )


@app.get("/api/jobs/{job_id}/export")
async def export_csv(job_id: str):
    async with async_session() as session:
        job = await session.get(Job, job_id)
        if not job:
            return Response("Job introuvable.", status_code=404)

        result = await session.execute(
            select(Lead).where(Lead.job_id == job_id)
        )
        leads = result.scalars().all()

    csv_content = generate_csv(leads)
    filename = f"leads_{job.business_type}_{job.location}.csv".replace(" ", "_")

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
