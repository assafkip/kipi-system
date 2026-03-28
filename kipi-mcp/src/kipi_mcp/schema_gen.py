from __future__ import annotations

import re

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}")
_URL_RE = re.compile(r"^https?://")

SCHEMAS: dict[str, dict] = {
    "organization": {
        "required": ["name", "url"],
        "optional": ["logo", "sameAs", "contactPoint"],
        "type": "Organization",
    },
    "website": {
        "required": ["name", "url"],
        "optional": ["potentialAction"],
        "type": "WebSite",
    },
    "article": {
        "required": ["headline", "image", "datePublished", "author"],
        "optional": ["dateModified", "publisher", "description", "mainEntityOfPage"],
        "type": "Article",
    },
    "blog_posting": {
        "required": ["headline", "image", "datePublished", "author"],
        "optional": ["dateModified", "publisher", "description", "mainEntityOfPage"],
        "type": "BlogPosting",
    },
    "product": {
        "required": ["name", "image", "offers"],
        "optional": ["sku", "brand", "aggregateRating", "review", "description"],
        "type": "Product",
    },
    "software_application": {
        "required": ["name", "offers"],
        "optional": ["applicationCategory", "operatingSystem", "aggregateRating"],
        "type": "SoftwareApplication",
    },
    "faq": {
        "required": ["questions"],
        "optional": [],
        "type": "FAQPage",
    },
    "howto": {
        "required": ["name", "steps"],
        "optional": ["description", "totalTime"],
        "type": "HowTo",
    },
    "breadcrumb": {
        "required": ["items"],
        "optional": [],
        "type": "BreadcrumbList",
    },
    "local_business": {
        "required": ["name", "address"],
        "optional": ["geo", "telephone", "openingHours", "priceRange"],
        "type": "LocalBusiness",
    },
    "event": {
        "required": ["name", "startDate", "location"],
        "optional": ["endDate", "eventAttendanceMode", "eventStatus", "image", "description", "offers", "organizer"],
        "type": "Event",
    },
}

_DATE_FIELDS = {"datePublished", "dateModified", "startDate", "endDate"}
_URL_FIELDS = {"url", "image", "logo"}

_STRONGLY_RECOMMENDED: dict[str, list[str]] = {
    "article": ["dateModified", "publisher", "description"],
    "blog_posting": ["dateModified", "publisher", "description"],
    "product": ["sku", "brand", "aggregateRating", "description"],
    "software_application": ["applicationCategory", "aggregateRating"],
    "event": ["endDate", "image", "description", "offers"],
    "local_business": ["telephone", "openingHours"],
    "organization": ["logo", "sameAs"],
    "website": ["potentialAction"],
}


def _validate_dates(data: dict) -> list[str]:
    warnings = []
    for field in _DATE_FIELDS:
        value = data.get(field)
        if value and isinstance(value, str):
            if not _DATE_RE.match(value):
                raise ValueError(f"field '{field}' is not ISO 8601 format: {value!r}")
            if "T" not in value and "+" not in value and "Z" not in value:
                warnings.append(f"date field '{field}' has no timezone info")
    return warnings


def _validate_urls(data: dict) -> None:
    for field in _URL_FIELDS:
        value = data.get(field)
        if value and isinstance(value, str):
            if not _URL_RE.match(value):
                raise ValueError(f"field '{field}' must start with http:// or https://: {value!r}")


def _wrap_author(author: str | dict) -> dict:
    if isinstance(author, str):
        return {"@type": "Person", "name": author}
    result = dict(author)
    if "@type" not in result:
        result["@type"] = "Person"
    return result


def _wrap_offers(offers: dict) -> dict:
    return {
        "@type": "Offer",
        "price": offers["price"],
        "priceCurrency": offers["currency"],
        "availability": offers.get("availability", "https://schema.org/InStock"),
    }


def _build_faq(data: dict) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": q["question"],
                "acceptedAnswer": {"@type": "Answer", "text": q["answer"]},
            }
            for q in data["questions"]
        ],
    }


def _build_howto(data: dict) -> dict:
    schema: dict = {
        "@context": "https://schema.org",
        "@type": "HowTo",
        "name": data["name"],
        "step": [
            {"@type": "HowToStep", "name": s["name"], "text": s["text"]}
            for s in data["steps"]
        ],
    }
    for field in ("description", "totalTime"):
        if field in data:
            schema[field] = data[field]
    return schema


def _build_breadcrumb(data: dict) -> dict:
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": item["name"], "item": item["url"]}
            for i, item in enumerate(data["items"])
        ],
    }


def _build_local_business(data: dict) -> dict:
    addr = data["address"]
    schema: dict = {
        "@context": "https://schema.org",
        "@type": "LocalBusiness",
        "name": data["name"],
        "address": {
            "@type": "PostalAddress",
            "streetAddress": addr["street"],
            "addressLocality": addr["city"],
            "addressRegion": addr["state"],
            "postalCode": addr["zip"],
            "addressCountry": addr["country"],
        },
    }
    for field in ("geo", "telephone", "openingHours", "priceRange"):
        if field in data:
            schema[field] = data[field]
    return schema


def _build_generic(page_type: str, data: dict) -> dict:
    spec = SCHEMAS[page_type]
    schema_type = spec["type"]
    schema: dict = {"@context": "https://schema.org", "@type": schema_type}

    for field in spec["required"] + spec["optional"]:
        if field not in data:
            continue
        value = data[field]
        if field == "author":
            schema[field] = _wrap_author(value)
        elif field == "offers" and isinstance(value, dict) and "price" in value:
            schema[field] = _wrap_offers(value)
        else:
            schema[field] = value

    return schema


class SchemaGenerator:

    def generate(self, page_type: str, data: dict) -> dict:
        if page_type not in SCHEMAS:
            raise ValueError(f"unsupported page_type: {page_type!r}. Valid types: {sorted(SCHEMAS)}")

        spec = SCHEMAS[page_type]
        missing = [f for f in spec["required"] if f not in data]
        if missing:
            raise ValueError(f"missing required fields for '{page_type}': {missing}")

        _validate_urls(data)
        warnings = _validate_dates(data)

        if page_type == "faq":
            schema = _build_faq(data)
        elif page_type == "howto":
            schema = _build_howto(data)
        elif page_type == "breadcrumb":
            schema = _build_breadcrumb(data)
        elif page_type == "local_business":
            schema = _build_local_business(data)
        else:
            schema = _build_generic(page_type, data)

        for rec_field in _STRONGLY_RECOMMENDED.get(page_type, []):
            if rec_field not in data:
                warnings.append(f"strongly recommended field '{rec_field}' is missing")

        return {"schema": schema, "page_type": page_type, "warnings": warnings}

    def generate_graph(self, schemas: list[dict]) -> dict:
        cleaned = []
        for s in schemas:
            copy = dict(s)
            copy.pop("@context", None)
            cleaned.append(copy)
        return {"@context": "https://schema.org", "@graph": cleaned}
