"""Smart API field suggestion from Data Import Tool column names."""

from __future__ import annotations

import re
from typing import Any

EXTERNAL_ID_CANDIDATES = [
    "CUST_ID__c",
    "SAP_ID__c",
    "Account_Unified_Id__c",
    "Wholesaler_Store_ID__c",
    "Cust_ID_System_of_Record__c",
]

STATUS_CONFIRMED = "Confirmed"
STATUS_NEEDS_CONFIRMATION = "Needs Confirmation"
STATUS_UNMAPPED = "Unmapped"

# Auto-confirmed exact DIT header -> API field pairs
CONFIRMED_EXACT: dict[str, str] = {
    "Salesforce Id": "Id",
    "*Name": "Name",
    "Name": "Name",
    "Phone": "Phone",
    "Street": "BillingStreet",
    "*Street": "BillingStreet",
    "City": "BillingCity",
    "*City": "BillingCity",
    "State": "BillingState",
    "*State": "BillingState",
    "Country": "BillingCountry",
    "*Country": "BillingCountry",
    "Postal Code": "BillingPostalCode",
    "*Postal Code": "BillingPostalCode",
}

# Word-level aliases for fuzzy matching
TOKEN_ALIASES: dict[str, list[str]] = {
    "certification": ["certified"],
    "classification": ["classification", "class"],
    "centralization": ["centralization", "central"],
    "deactivate": ["deactivate"],
    "valid": ["valid"],
    "gdpr": ["gdpr"],
    "tax": ["tax"],
    "id": ["id"],
    "email": ["email"],
    "market": ["market"],
    "currency": ["currency", "iso"],
    "payment": ["payment"],
    "terms": ["terms"],
    "type": ["type"],
    "channel": ["channel"],
    "subchannel": ["subchannel"],
    "microsegment": ["microsegment"],
    "microsegments": ["microsegment"],
    "beverages": ["beverages", "bevs"],
    "bevs": ["bevs", "beverages"],
    "snacks": ["snacks"],
    "foods": ["foods", "food"],
    "food": ["food", "foods"],
    "volume": ["volume"],
    "sales": ["sales"],
    "uom": ["uom"],
    "gln": ["gln"],
    "iban": ["iban"],
    "gtm": ["gtm"],
    "dsd": ["dsd"],
    "b2b": ["b2b"],
    "digital": ["digital"],
    "platform": ["platform"],
    "disqualification": ["disqual"],
    "disqual": ["disqual"],
    "reason": ["reason"],
    "competitor": ["competitor"],
    "contract": ["contract"],
    "expiration": ["expiration"],
    "segmentation": ["segmentation"],
    "external": ["external"],
    "buying": ["buying"],
    "categories": ["categories"],
    "key": ["key"],
    "account": ["account"],
    "wholesaler": ["wholesaler"],
    "payer": ["payer"],
    "customer": ["cust", "customer"],
    "degree": ["degree"],
    "self": ["self"],
    "local": ["local"],
    "definition": ["definition"],
    "pricegroup": ["pricegroup"],
    "cluster": ["cluster"],
    "value": ["value"],
}

STOPWORDS = {"of", "the", "and", "or", "dd", "mm", "yyyy", "date", "to", "on"}


def suggest_api_field(
    dit_column: str,
    api_fields: list[str],
) -> tuple[str | None, str, list[str]]:
    """
    Suggest a Salesforce API field for a DIT column.

    Returns (suggested_api_field, status, candidate_list).
    """
    if dit_column in CONFIRMED_EXACT:
        api = CONFIRMED_EXACT[dit_column]
        if api in api_fields:
            return api, STATUS_CONFIRMED, [api]

    if _is_account_external_id_column(dit_column):
        return (
            "CUST_ID__c",
            STATUS_NEEDS_CONFIRMATION,
            [c for c in EXTERNAL_ID_CANDIDATES if c in api_fields],
        )

    dit_tokens = _tokenize_dit(dit_column)
    if not dit_tokens:
        return None, STATUS_UNMAPPED, []

    scored: list[tuple[float, str]] = []
    for api_field in api_fields:
        score = _score_api_match(dit_tokens, api_field)
        if score > 0:
            scored.append((score, api_field))

    scored.sort(key=lambda x: (-x[0], -len(x[1]), x[1]))

    if not scored:
        return None, STATUS_UNMAPPED, []

    best_score, best_field = scored[0]

    if best_score >= 1.0:
        return best_field, STATUS_CONFIRMED, [best_field]

    if best_score >= 0.6:
        candidates = [f for _, f in scored[:5] if _score_api_match(dit_tokens, f) >= 0.5]
        return best_field, STATUS_NEEDS_CONFIRMATION, candidates or [best_field]

    return None, STATUS_UNMAPPED, []


def _is_account_external_id_column(dit_column: str) -> bool:
    """Account External ID always maps to CUST_ID__c — not inferred from words."""
    normalized = dit_column.lstrip("*").lower().strip()
    external_id_labels = {
        "external id",
        "account external id",
        "external id ",
    }
    return normalized in external_id_labels or "external id" in normalized


def _tokenize_dit(text: str) -> list[str]:
    text = re.sub(r"\([^)]*\)", "", text)
    text = text.lstrip("*")
    text = re.sub(r"[/\-]", " ", text)
    text = re.sub(r"[^\w\s]", " ", text)
    words = re.split(r"[\s_]+", text.lower())
    return [w for w in words if len(w) >= 2 and w not in STOPWORDS]


def _api_tokens(api_field: str) -> set[str]:
    base = api_field.replace("__c", "").replace("__C", "")
    parts = re.split(r"[_\s]+", base.lower())
    tokens: set[str] = set()
    for part in parts:
        if part:
            tokens.add(part)
            if part.startswith("l") and len(part) == 2 and part[1].isdigit():
                tokens.add(part[1])
    return tokens


def _token_matches(token: str, api_token_set: set[str], api_norm: str) -> bool:
    if token in api_token_set:
        return True
    if token in api_norm:
        return True
    for alias in TOKEN_ALIASES.get(token, []):
        if alias in api_token_set or alias in api_norm:
            return True
    return False


def _score_api_match(dit_tokens: list[str], api_field: str) -> float:
    api_token_set = _api_tokens(api_field)
    api_norm = api_field.replace("__c", "").replace("_", " ").lower()

    if not dit_tokens:
        return 0.0

    matched = sum(
        1 for token in dit_tokens
        if _token_matches(token, api_token_set, api_norm)
    )
    return matched / len(dit_tokens)


def build_smart_column_mappings(
    dit_headers: list[str],
    api_fields: list[str],
) -> dict[str, dict[str, Any]]:
    """Build column mapping config from smart suggestions."""
    mappings: dict[str, dict[str, Any]] = {}
    for header in dit_headers:
        suggested, status, candidates = suggest_api_field(header, api_fields)
        entry: dict[str, Any] = {
            "suggested_api_field": suggested,
            "default_status": status.lower().replace(" ", "_"),
        }
        if candidates:
            entry["api_field_candidates"] = candidates
        if _is_account_external_id_column(header):
            entry["is_external_id_style"] = True
        mappings[header] = entry
    return mappings
