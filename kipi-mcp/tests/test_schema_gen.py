from __future__ import annotations

import pytest

from kipi_mcp.schema_gen import SchemaGenerator, SCHEMAS


@pytest.fixture
def gen() -> SchemaGenerator:
    return SchemaGenerator()


# ---------------------------------------------------------------------------
# Valid data fixtures per page type
# ---------------------------------------------------------------------------

VALID_DATA: dict[str, dict] = {
    "organization": {
        "name": "Acme Corp",
        "url": "https://acme.example.com",
        "logo": "https://acme.example.com/logo.png",
        "sameAs": ["https://twitter.com/acme"],
    },
    "website": {
        "name": "Acme",
        "url": "https://acme.example.com",
    },
    "article": {
        "headline": "How to Scale APIs",
        "image": "https://acme.example.com/img.jpg",
        "datePublished": "2024-01-15T10:00:00Z",
        "author": "Jane Doe",
        "dateModified": "2024-02-01T00:00:00Z",
        "publisher": {"@type": "Organization", "name": "Acme"},
        "description": "A guide to scaling APIs.",
    },
    "blog_posting": {
        "headline": "Microservice Patterns",
        "image": "https://acme.example.com/blog.jpg",
        "datePublished": "2024-03-10",
        "author": {"@type": "Person", "name": "John"},
    },
    "product": {
        "name": "API Tool",
        "image": "https://acme.example.com/product.jpg",
        "offers": {"price": "49.00", "currency": "USD"},
        "description": "An API tool.",
        "sku": "SKU-001",
    },
    "software_application": {
        "name": "DevApp",
        "offers": {"price": "0", "currency": "USD", "availability": "https://schema.org/InStock"},
        "applicationCategory": "DeveloperApplication",
    },
    "faq": {
        "questions": [
            {"question": "What is it?", "answer": "It is a tool."},
            {"question": "How much?", "answer": "Free tier available."},
        ]
    },
    "howto": {
        "name": "Deploy a service",
        "steps": [
            {"name": "Build", "text": "Run docker build."},
            {"name": "Push", "text": "Push to registry."},
        ],
        "description": "Step-by-step deployment.",
        "totalTime": "PT10M",
    },
    "breadcrumb": {
        "items": [
            {"name": "Home", "url": "https://acme.example.com/"},
            {"name": "Blog", "url": "https://acme.example.com/blog"},
            {"name": "Post", "url": "https://acme.example.com/blog/post"},
        ]
    },
    "local_business": {
        "name": "Acme Store",
        "address": {
            "street": "123 Main St",
            "city": "Springfield",
            "state": "IL",
            "zip": "62701",
            "country": "US",
        },
        "telephone": "+1-800-555-0100",
    },
    "event": {
        "name": "API Summit",
        "startDate": "2024-09-01",
        "location": "Online",
        "endDate": "2024-09-02",
        "description": "A conference on APIs.",
    },
}


# ---------------------------------------------------------------------------
# Parametrized: all page types produce valid structure
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("page_type", list(SCHEMAS.keys()))
def test_generate_valid_data_returns_expected_keys(gen, page_type):
    result = gen.generate(page_type, VALID_DATA[page_type])
    assert "schema" in result
    assert "page_type" in result
    assert "warnings" in result
    assert result["page_type"] == page_type
    assert isinstance(result["warnings"], list)


@pytest.mark.parametrize("page_type", list(SCHEMAS.keys()))
def test_generate_schema_has_context_and_type(gen, page_type):
    result = gen.generate(page_type, VALID_DATA[page_type])
    schema = result["schema"]
    assert schema["@context"] == "https://schema.org"
    assert "@type" in schema
    assert schema["@type"] == SCHEMAS[page_type]["type"]


# ---------------------------------------------------------------------------
# Missing required fields
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("page_type,missing_field", [
    ("organization", "name"),
    ("organization", "url"),
    ("article", "headline"),
    ("article", "author"),
    ("product", "offers"),
    ("faq", "questions"),
    ("howto", "steps"),
    ("breadcrumb", "items"),
    ("local_business", "address"),
    ("event", "startDate"),
])
def test_generate_missing_required_field_raises(gen, page_type, missing_field):
    data = dict(VALID_DATA[page_type])
    del data[missing_field]
    with pytest.raises(ValueError, match=missing_field):
        gen.generate(page_type, data)


# ---------------------------------------------------------------------------
# Invalid page type
# ---------------------------------------------------------------------------

def test_generate_invalid_page_type_raises(gen):
    with pytest.raises(ValueError, match="unsupported page_type"):
        gen.generate("banana", {"name": "x"})


def test_generate_invalid_page_type_message_lists_valid_types(gen):
    with pytest.raises(ValueError) as exc_info:
        gen.generate("not_real", {})
    assert "organization" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Date validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("date_value", [
    "2024-01-15",
    "2024-01-15T10:00:00Z",
    "2024-12-31T23:59:59+05:30",
])
def test_generate_valid_date_formats_accepted(gen, date_value):
    data = dict(VALID_DATA["article"])
    data["datePublished"] = date_value
    result = gen.generate("article", data)
    assert result["schema"]["datePublished"] == date_value


@pytest.mark.parametrize("bad_date", [
    "15-01-2024",
    "January 15 2024",
    "2024/01/15",
    "not-a-date",
])
def test_generate_invalid_date_format_raises(gen, bad_date):
    data = dict(VALID_DATA["article"])
    data["datePublished"] = bad_date
    with pytest.raises(ValueError, match="datePublished"):
        gen.generate("article", data)


def test_generate_date_without_timezone_adds_warning(gen):
    data = dict(VALID_DATA["article"])
    data["datePublished"] = "2024-01-15"
    result = gen.generate("article", data)
    warning_text = " ".join(result["warnings"])
    assert "timezone" in warning_text


def test_generate_date_with_timezone_no_timezone_warning(gen):
    data = dict(VALID_DATA["article"])
    data["datePublished"] = "2024-01-15T10:00:00Z"
    result = gen.generate("article", data)
    tz_warnings = [w for w in result["warnings"] if "timezone" in w and "datePublished" in w]
    assert len(tz_warnings) == 0


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("url_field,page_type", [
    ("url", "organization"),
    ("image", "article"),
    ("logo", "organization"),
])
def test_generate_invalid_url_raises(gen, url_field, page_type):
    data = dict(VALID_DATA[page_type])
    data[url_field] = "ftp://not-valid.com"
    with pytest.raises(ValueError, match=url_field):
        gen.generate(page_type, data)


def test_generate_url_without_scheme_raises(gen):
    data = dict(VALID_DATA["organization"])
    data["url"] = "acme.example.com"
    with pytest.raises(ValueError, match="url"):
        gen.generate("organization", data)


# ---------------------------------------------------------------------------
# FAQ transformation
# ---------------------------------------------------------------------------

def test_generate_faq_produces_main_entity(gen):
    result = gen.generate("faq", VALID_DATA["faq"])
    schema = result["schema"]
    assert "mainEntity" in schema
    assert "questions" not in schema


def test_generate_faq_main_entity_structure(gen):
    result = gen.generate("faq", VALID_DATA["faq"])
    entities = result["schema"]["mainEntity"]
    assert len(entities) == 2
    q = entities[0]
    assert q["@type"] == "Question"
    assert q["name"] == "What is it?"
    assert q["acceptedAnswer"]["@type"] == "Answer"
    assert q["acceptedAnswer"]["text"] == "It is a tool."


def test_generate_faq_single_question(gen):
    data = {"questions": [{"question": "Q?", "answer": "A."}]}
    result = gen.generate("faq", data)
    assert len(result["schema"]["mainEntity"]) == 1


# ---------------------------------------------------------------------------
# HowTo transformation
# ---------------------------------------------------------------------------

def test_generate_howto_produces_step_array(gen):
    result = gen.generate("howto", VALID_DATA["howto"])
    schema = result["schema"]
    assert "step" in schema
    assert "steps" not in schema


def test_generate_howto_step_structure(gen):
    result = gen.generate("howto", VALID_DATA["howto"])
    steps = result["schema"]["step"]
    assert len(steps) == 2
    assert steps[0]["@type"] == "HowToStep"
    assert steps[0]["name"] == "Build"
    assert steps[0]["text"] == "Run docker build."


def test_generate_howto_includes_optional_fields(gen):
    result = gen.generate("howto", VALID_DATA["howto"])
    schema = result["schema"]
    assert schema.get("description") == "Step-by-step deployment."
    assert schema.get("totalTime") == "PT10M"


# ---------------------------------------------------------------------------
# Breadcrumb transformation
# ---------------------------------------------------------------------------

def test_generate_breadcrumb_produces_item_list_element(gen):
    result = gen.generate("breadcrumb", VALID_DATA["breadcrumb"])
    schema = result["schema"]
    assert "itemListElement" in schema
    assert "items" not in schema


def test_generate_breadcrumb_positions_are_1_indexed(gen):
    result = gen.generate("breadcrumb", VALID_DATA["breadcrumb"])
    items = result["schema"]["itemListElement"]
    assert items[0]["position"] == 1
    assert items[1]["position"] == 2
    assert items[2]["position"] == 3


def test_generate_breadcrumb_item_structure(gen):
    result = gen.generate("breadcrumb", VALID_DATA["breadcrumb"])
    item = result["schema"]["itemListElement"][0]
    assert item["@type"] == "ListItem"
    assert item["name"] == "Home"
    assert item["item"] == "https://acme.example.com/"


# ---------------------------------------------------------------------------
# LocalBusiness address transformation
# ---------------------------------------------------------------------------

def test_generate_local_business_address_is_postal_address(gen):
    result = gen.generate("local_business", VALID_DATA["local_business"])
    addr = result["schema"]["address"]
    assert addr["@type"] == "PostalAddress"


def test_generate_local_business_address_field_mapping(gen):
    result = gen.generate("local_business", VALID_DATA["local_business"])
    addr = result["schema"]["address"]
    assert addr["streetAddress"] == "123 Main St"
    assert addr["addressLocality"] == "Springfield"
    assert addr["addressRegion"] == "IL"
    assert addr["postalCode"] == "62701"
    assert addr["addressCountry"] == "US"


def test_generate_local_business_optional_fields_pass_through(gen):
    result = gen.generate("local_business", VALID_DATA["local_business"])
    assert result["schema"]["telephone"] == "+1-800-555-0100"


# ---------------------------------------------------------------------------
# Offers transformation
# ---------------------------------------------------------------------------

def test_generate_product_offers_wrapped_as_offer(gen):
    result = gen.generate("product", VALID_DATA["product"])
    offers = result["schema"]["offers"]
    assert offers["@type"] == "Offer"
    assert offers["price"] == "49.00"
    assert offers["priceCurrency"] == "USD"


def test_generate_product_offers_default_availability(gen):
    data = dict(VALID_DATA["product"])
    data["offers"] = {"price": "10.00", "currency": "USD"}
    result = gen.generate("product", data)
    assert result["schema"]["offers"]["availability"] == "https://schema.org/InStock"


def test_generate_product_offers_custom_availability(gen):
    data = dict(VALID_DATA["product"])
    data["offers"] = {"price": "10.00", "currency": "USD", "availability": "https://schema.org/PreOrder"}
    result = gen.generate("product", data)
    assert result["schema"]["offers"]["availability"] == "https://schema.org/PreOrder"


def test_generate_software_application_offers_wrapped(gen):
    result = gen.generate("software_application", VALID_DATA["software_application"])
    assert result["schema"]["offers"]["@type"] == "Offer"


# ---------------------------------------------------------------------------
# Author transformation
# ---------------------------------------------------------------------------

def test_generate_article_author_string_wrapped_as_person(gen):
    data = dict(VALID_DATA["article"])
    data["author"] = "Jane Doe"
    result = gen.generate("article", data)
    author = result["schema"]["author"]
    assert author["@type"] == "Person"
    assert author["name"] == "Jane Doe"


def test_generate_article_author_dict_with_type_unchanged(gen):
    data = dict(VALID_DATA["article"])
    data["author"] = {"@type": "Organization", "name": "Acme"}
    result = gen.generate("article", data)
    author = result["schema"]["author"]
    assert author["@type"] == "Organization"
    assert author["name"] == "Acme"


def test_generate_article_author_dict_without_type_gets_person(gen):
    data = dict(VALID_DATA["article"])
    data["author"] = {"name": "Jane"}
    result = gen.generate("article", data)
    assert result["schema"]["author"]["@type"] == "Person"


def test_generate_blog_posting_author_string_wrapped(gen):
    data = dict(VALID_DATA["blog_posting"])
    data["author"] = "Bob"
    result = gen.generate("blog_posting", data)
    assert result["schema"]["author"]["@type"] == "Person"


# ---------------------------------------------------------------------------
# generate_graph
# ---------------------------------------------------------------------------

def test_generate_graph_wraps_schemas_in_graph(gen):
    org = gen.generate("organization", VALID_DATA["organization"])["schema"]
    web = gen.generate("website", VALID_DATA["website"])["schema"]
    graph = gen.generate_graph([org, web])
    assert graph["@context"] == "https://schema.org"
    assert "@graph" in graph
    assert len(graph["@graph"]) == 2


def test_generate_graph_removes_context_from_items(gen):
    org = gen.generate("organization", VALID_DATA["organization"])["schema"]
    web = gen.generate("website", VALID_DATA["website"])["schema"]
    assert "@context" in org
    graph = gen.generate_graph([org, web])
    for item in graph["@graph"]:
        assert "@context" not in item


def test_generate_graph_preserves_types(gen):
    org = gen.generate("organization", VALID_DATA["organization"])["schema"]
    faq = gen.generate("faq", VALID_DATA["faq"])["schema"]
    graph = gen.generate_graph([org, faq])
    types = {item["@type"] for item in graph["@graph"]}
    assert types == {"Organization", "FAQPage"}


def test_generate_graph_single_schema(gen):
    org = gen.generate("organization", VALID_DATA["organization"])["schema"]
    graph = gen.generate_graph([org])
    assert len(graph["@graph"]) == 1


def test_generate_graph_empty_list(gen):
    graph = gen.generate_graph([])
    assert graph["@graph"] == []


# ---------------------------------------------------------------------------
# Optional field warnings
# ---------------------------------------------------------------------------

def test_generate_missing_recommended_fields_produces_warnings(gen):
    data = {"name": "Acme Corp", "url": "https://acme.example.com"}
    result = gen.generate("organization", data)
    warning_text = " ".join(result["warnings"])
    assert "logo" in warning_text or "sameAs" in warning_text


def test_generate_product_missing_recommended_fields_warns(gen):
    data = {"name": "Tool", "image": "https://acme.example.com/img.jpg", "offers": {"price": "0", "currency": "USD"}}
    result = gen.generate("product", data)
    warned_fields = " ".join(result["warnings"])
    assert "description" in warned_fields or "sku" in warned_fields


def test_generate_all_required_only_no_errors(gen):
    data = {"name": "Acme Corp", "url": "https://acme.example.com"}
    result = gen.generate("organization", data)
    assert result["schema"]["@type"] == "Organization"


# ---------------------------------------------------------------------------
# Optional fields included in output
# ---------------------------------------------------------------------------

def test_generate_organization_includes_optional_fields(gen):
    result = gen.generate("organization", VALID_DATA["organization"])
    schema = result["schema"]
    assert schema["logo"] == "https://acme.example.com/logo.png"
    assert schema["sameAs"] == ["https://twitter.com/acme"]


def test_generate_event_includes_optional_fields(gen):
    result = gen.generate("event", VALID_DATA["event"])
    schema = result["schema"]
    assert schema["endDate"] == "2024-09-02"
    assert schema["description"] == "A conference on APIs."
