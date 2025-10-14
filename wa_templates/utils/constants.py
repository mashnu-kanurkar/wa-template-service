# constants.py

from enum import Enum
from django.utils.translation import gettext_lazy as _

# --- API Endpoints / Webhook Event Types ---
# Use an Enum for a clean, immutable set of keys/actions.

class GupshupAction(Enum):
    """
    Defines keys for various template operations or webhooks.
    Using enums makes keys easy to read and prevents typos.
    """
    # Template Management Actions
    UPDATE_TEMPLATE = "update_template"
    DELETE_TEMPLATE = "delete_template"
    APPLY_TEMPLATE = "apply_template"
    GET_TEMPLATE_DETAILS = "get_template_details"
    SYNC_TEMPLATES = "sync_templates"
    UPLOAD_MEDIA = "upload_media"
    
    # Internal Statuses / Errors
    UPLOAD_SUCCESS = "media_upload_success"
    UPLOAD_FAILED = "media_upload_failed"
    TEMPLATE_APPROVED = "template_approved"
    TEMPLATE_REJECTED = "template_rejected"
    
    # Message Types (if needed)
    TEXT_MESSAGE = "text"
    IMAGE_MESSAGE = "image"
    
    @classmethod
    def choices(cls):
        """Returns a list of (value, value) tuples for Django choices."""
        return [(item.value, item.value) for item in cls]

# --- Error Messages (if you want these centralized) ---

# Note: Using gettext_lazy for potential future internationalization
class ErrorMessageEnume(object):
    """
    Constants for standard error strings used across the application.
    """
    INVALID_PAYLOAD = _("The request payload was incorrect or malformed.")
    MISSING_HANDLE_ID = _("Media upload succeeded but missing handle ID in response.")
    NETWORK_TIMEOUT = _("The request timed out while communicating with the provider.")
    
# --- Configuration Values ---

class Config(object):
    """
    General configuration values.
    """
    MEDIA_UPLOAD_RETRIES = 3
    REQUEST_TIMEOUT_SECONDS = 10
    
# Example of using a simple constant variable
DEFAULT_TS_KEY = "ts"