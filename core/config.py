"""Application configuration and constants."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# Deployment and metadata source configuration
# ---------------------------------------------------------------------------

_IN_DOCKER = Path("/.dockerenv").exists() or os.environ.get("DOCKER_CONTAINER", "").lower() == "true"

_TRUTHY_ENV_VALUES = frozenset({"1", "true", "yes", "on"})


def _env_is_truthy(name: str) -> bool:
    """Return True when an env var is set to a common truthy string."""
    return os.environ.get(name, "").strip().lower() in _TRUTHY_ENV_VALUES


def _is_streamlit_community_cloud() -> bool:
    """Heuristic for Streamlit Community Cloud (Linux appuser, no local EUSFA clone)."""
    if os.environ.get("USER", "").strip() == "appuser":
        return True
    return Path("/home/appuser/.streamlit").is_dir()


def _is_hosted_deployment() -> bool:
    """True on Docker, Streamlit Cloud, or explicit demo/production deployment modes."""
    if _IN_DOCKER or _is_streamlit_community_cloud():
        return True
    deployment = os.environ.get("DEPLOYMENT_MODE", "local").strip().lower()
    if deployment in {"demo", "production"}:
        return True
    return _env_is_truthy("STREAMLIT_HOSTED")


def _default_metadata_mode() -> str:
    return "bundled" if _is_hosted_deployment() else "local"


def _default_deployment_mode() -> str:
    if _is_hosted_deployment() and not os.environ.get("DEPLOYMENT_MODE", "").strip():
        return "demo"
    return "local"


DEPLOYMENT_MODE = os.environ.get("DEPLOYMENT_MODE", _default_deployment_mode()).strip().lower()
"""One of: local, demo, production."""

METADATA_MODE = os.environ.get("METADATA_MODE", _default_metadata_mode()).strip().lower()
"""One of: local (live git clone), bundled (read-only snapshot in container)."""


def get_metadata_mode() -> str:
    return os.environ.get("METADATA_MODE", _default_metadata_mode()).strip().lower()


def get_deployment_mode() -> str:
    return os.environ.get("DEPLOYMENT_MODE", _default_deployment_mode()).strip().lower()


def is_hosted_deployment() -> bool:
    return _is_hosted_deployment()


def get_bundled_metadata_dir() -> Path:
    return Path(
        os.environ.get("BUNDLED_METADATA_PATH", str(PROJECT_ROOT / "bundled_metadata"))
    ).expanduser()


BUNDLED_METADATA_DIR = get_bundled_metadata_dir()

SSO_DISABLED = _env_is_truthy("SSO_DISABLED")
SSO_ENABLED = _env_is_truthy("SSO_ENABLED")


def _local_dev_metadata_default() -> Path:
    """Developer-only default when running locally without explicit env vars."""
    return Path.home() / ".cursor" / "EUSFA SF" / "EUROPE_SFA"


def resolve_metadata_repo_path() -> Path:
    """
    Return the filesystem root used for Salesforce DX metadata reads.

    - bundled: read-only snapshot copied at build time (no Path.home() fallback)
    - local: EUSFA_SFDX_REPO_PATH env var, or developer default when DEPLOYMENT_MODE=local
    """
    if get_metadata_mode() == "bundled":
        return get_bundled_metadata_dir().resolve()

    env_path = os.environ.get("EUSFA_SFDX_REPO_PATH", "").strip()
    if env_path:
        return Path(env_path).expanduser().resolve()

    if get_deployment_mode() == "local":
        return _local_dev_metadata_default().resolve()

    raise RuntimeError(
        "EUSFA_SFDX_REPO_PATH must be set when METADATA_MODE=local and "
        f"DEPLOYMENT_MODE={get_deployment_mode()!r}."
    )


# Backward-compatible alias used across the codebase.
EUSFA_SFDX_REPO_PATH = resolve_metadata_repo_path()


def is_bundled_metadata_mode() -> bool:
    return get_metadata_mode() == "bundled"


def is_git_metadata_sync_enabled() -> bool:
    """Git fetch/pull controls are only available for local developer clones."""
    return get_metadata_mode() == "local" and get_deployment_mode() == "local"


def is_sso_required() -> bool:
    """Return True when Streamlit Entra OIDC login should gate the app."""
    if SSO_DISABLED:
        return False

    require_sso = os.environ.get("REQUIRE_SSO", "").strip()
    if require_sso:
        return require_sso.lower() in _TRUTHY_ENV_VALUES

    if get_deployment_mode() == "production":
        return True

    # Demo / Community Cloud default to open access unless REQUIRE_SSO is set.
    # Local dev defaults to False unless SSO_ENABLED is set for auth-flow testing.
    return SSO_ENABLED if get_deployment_mode() == "local" else False


def metadata_source_label(*, live_connected: bool = False) -> str:
    """User-facing label for the active metadata provider."""
    if live_connected:
        return "Live Salesforce Org"
    return "Approved Snapshot"


# ---------------------------------------------------------------------------
# Salesforce OAuth (primary auth for live metadata)
# ---------------------------------------------------------------------------

DEFAULT_SALESFORCE_API_VERSION = "v59.0"
DEFAULT_SALESFORCE_OAUTH_SCOPES = "api refresh_token id"


def get_salesforce_client_id() -> str:
    return os.environ.get("SALESFORCE_CLIENT_ID", "").strip()


def get_salesforce_redirect_uri() -> str:
    return os.environ.get("SALESFORCE_REDIRECT_URI", "").strip()


def get_salesforce_api_version() -> str:
    version = os.environ.get("SALESFORCE_API_VERSION", DEFAULT_SALESFORCE_API_VERSION).strip()
    if not version.startswith("v"):
        version = f"v{version}"
    return version


def get_salesforce_oauth_scopes() -> str:
    return os.environ.get("SALESFORCE_OAUTH_SCOPES", DEFAULT_SALESFORCE_OAUTH_SCOPES).strip()


def salesforce_login_host(environment: str) -> str:
    """Return Salesforce authorize/token host for production or sandbox."""
    if environment.strip().lower() in {"sandbox", "test"}:
        return "https://test.salesforce.com"
    return "https://login.salesforce.com"


# ---------------------------------------------------------------------------
# Application constants
# ---------------------------------------------------------------------------

UPLOAD_METHODS = [
    "Data Import Tool",
    "Workbench",
]

TEMPLATES = [
    "Account Relationship",
    "Assortment",
    "Assortment Assignment",
    "Assortment Product",
    "Contact",
    "Contract",
    "Customer to Route",
    "Customers",
    "Employee to Route",
    "Order",
    "Order Item",
    "Key Account",
    "Payers",
    "Pricelist Master",
    "Products",
    "Prospects",
    "Retail Promotion",
    "Retail Sales Geo",
    "Routing Import",
    "Store Assortment",
    "Store Product",
    "Units of Measure",
    "Wholesalers",
]

LOAD_ACTIONS = {
    "Insert": {
        "label": "Insert (Create New Records)",
        "description": (
            "Use this when uploading records that do not already exist in Salesforce. "
            "Example: loading brand-new customers. Salesforce Id is NOT required."
        ),
    },
    "Update": {
        "label": "Update (Update Existing Records)",
        "description": (
            "Use this when changing records that already exist in Salesforce. "
            "Example: updating an existing customer's address. Salesforce Id IS required."
        ),
    },
}

DEFAULT_PREPARATION_TASK = "Prepare and Validate File"

PREPARATION_TASKS = {
    "Prepare and Validate File": {
        "label": "🛠️ Prepare & Validate File (Recommended)",
        "description": (
            "Maps headers, validates your data, and creates a tool-ready CSV."
        ),
        "load_operation": None,
        "preparation_only": True,
    },
    "Prepare for Insert": {
        "label": "➕ Prepare for Insert",
        "description": (
            "Maps headers, validates your data, and checks that the file is ready to create new Salesforce records."
        ),
        "load_operation": "Insert",
        "preparation_only": False,
    },
    "Prepare for Update": {
        "label": "✏️ Prepare for Update",
        "description": (
            "Maps headers, validates your data, and checks that the file is ready to update existing Salesforce records."
        ),
        "load_operation": "Update",
        "preparation_only": False,
    },
}

LOAD_ACTION_NOT_EVALUATED = "Not Evaluated"

READINESS_STATUS = {
    "READY": "READY",
    "READY_WITH_WARNINGS": "READY WITH WARNINGS",
    "NEEDS_HEADER_REVIEW": "NEEDS HEADER REVIEW",
    "NEEDS_USER_ACTION": "NEEDS USER ACTION",
    "NOT_READY": "NOT READY",
}

CORRECTION_CATEGORIES = {
    "rename": "Rename header",
    "add_generated_value": "Add generated value",
    "add_empty_optional_column": "Add empty optional column",
    "reorder_columns": "Reorder columns",
    "exclude_extra_column": "Exclude extra column",
    "required_data_missing": "Required data missing",
    "manual_mapping_required": "Manual mapping required",
}

REQUIREDNESS = {
    "INSERT": "Required for Insert",
    "UPDATE": "Required for Update",
    "BUSINESS": "Required by business rule",
    "OPTIONAL": "Optional",
    "SYSTEM": "System-generated",
    "COPILOT": "Copilot-generated",
    "NOT_APPLICABLE": "Not applicable",
}

PREPARATION_CATEGORIES = {
    "rename_headers": "Rename headers",
    "convert_dates": "Convert dates",
    "populate_type": "Populate Type column",
    "remove_blank_rows": "Remove blank rows",
    "trim_whitespace": "Trim whitespace",
    "add_id_column": "Add Id column",
    "reorder_columns": "Reorder columns",
}

FORMATTING_CATEGORIES = {
    "convert_dates": "Wrong date format",
    "trim_whitespace": "Leading/trailing spaces",
    "remove_blank_rows": "Completely blank rows",
    "restore_leading_zeroes": "Missing leading zeroes",
    "normalize_phone": "Phone formatting issues",
    "malformed_csv": "Commas or malformed rows",
}
