import csv
import io

from app.models import Lead

FIELDNAMES = [
    "name",
    "phone",
    "address",
    "website",
    "rating",
    "reviews_count",
    "google_maps_url",
]


def generate_csv(leads: list[Lead]) -> str:
    """Generate a CSV string from a list of Lead objects."""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=FIELDNAMES)
    writer.writeheader()
    for lead in leads:
        writer.writerow({
            "name": lead.name,
            "phone": lead.phone or "",
            "address": lead.address or "",
            "website": lead.website or "",
            "rating": lead.rating or "",
            "reviews_count": lead.reviews_count or "",
            "google_maps_url": lead.google_maps_url or "",
        })
    return output.getvalue()
