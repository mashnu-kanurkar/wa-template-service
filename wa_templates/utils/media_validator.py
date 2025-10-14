import logging
import mimetypes
import re
from urllib.parse import urlparse
from django.core.validators import URLValidator
from django.core.exceptions import ValidationError

logger = logging.getLogger(__name__)

# Allowed MIME types
ALLOWED_MIME_TYPES = {
    "audio/aac",
    "audio/mp4",
    "audio/mpeg",
    "audio/amr",
    "audio/ogg",
    "audio/opus",
    "application/vnd.ms-powerpoint",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/pdf",
    "text/plain",
    "application/vnd.ms-excel",
    "image/jpeg",
    "image/png",
    "image/webp",
    "video/mp4",
    "video/3gpp",
}

# Template-type → allowed MIME group
TEMPLATE_MIME_GROUPS = {
    "IMAGE": {"image/jpeg", "image/png", "image/webp"},
    "VIDEO": {"video/mp4", "video/3gpp"},
    "DOCUMENT": {
        "application/pdf",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "text/plain",
    },
    "AUDIO": {
        "audio/aac",
        "audio/mp4",
        "audio/mpeg",
        "audio/amr",
        "audio/ogg",
        "audio/opus",
    },
}


def is_valid_media_url(url: str, template_type: str) -> tuple[bool, str | None]:
    """
    Validates that:
      1. URL is a valid HTTP(S) URL
      2. The MIME type inferred from URL is valid and allowed for the given template_type

    Returns:
      (is_valid: bool, file_type: str | None)
    """
    if not url:
        logger.debug("Empty URL provided.")
        return False, None

    # 1. Validate URL structure
    try:
        URLValidator(schemes=["http", "https"])(url)
    except ValidationError:
        logger.debug(f"Invalid URL structure: {url}")
        return False, None

    # 2. Normalize template_type
    template_type = template_type.upper().strip()
    if template_type not in TEMPLATE_MIME_GROUPS:
        logger.warning(f"Unknown template type: {template_type}")
        return False, None

    # 3. Infer MIME type
    parsed_url = urlparse(url)
    guessed_mime, _ = mimetypes.guess_type(parsed_url.path.lower())

    if not guessed_mime:
        logger.debug(f"Could not infer MIME type from URL: {url}")
        return False, None

    # 4. Ensure MIME is allowed
    if guessed_mime not in ALLOWED_MIME_TYPES:
        logger.debug(f"MIME '{guessed_mime}' not in allowed list.")
        return False, guessed_mime

    # 5. Check MIME compatibility with template_type
    allowed_for_template = TEMPLATE_MIME_GROUPS[template_type]
    if guessed_mime not in allowed_for_template:
        logger.debug(
            f"MIME '{guessed_mime}' not allowed for template type '{template_type}'. "
            f"Allowed: {allowed_for_template}"
        )
        return False, guessed_mime

    logger.debug(f"URL '{url}' is valid for template type '{template_type}' with MIME '{guessed_mime}'.")
    return True, guessed_mime


# ----------------------------------------------------------------------
# 2. Gupshup Handle ID Check
# ----------------------------------------------------------------------

# The Gupshup handle ID is a long, colon-separated, Base64-like string.
# A full validation is brittle and unnecessary; we check for the characteristic structure.
# Example: 4::aW1h...G5n:ARYY-6d3...:e:1634970144:2...:100033...:A...
GUPSHUP_HANDLE_ID_PATTERN = re.compile(
    r'^'              # Start of string
    r'\d{1,2}::'      # Starts with 1 or 2 digits followed by :: (e.g., 4::)
    r'[\w\-]+:'       # Base64-like segment (A-Z, a-z, 0-9, _, -) followed by :
    r'[\w\-]+:'       # Another Base64-like segment
    r'[a-z]{1}:'      # A single lowercase letter followed by : (e.g., e:)
    r'\d{10,}:'       # Timestamp (10 or more digits) followed by :
    r'[\w\-]+:'       # Another digit/word segment
    r'[\w\-]+:'       # Another digit/word segment
    r'[\w\-]+$'       # Last Base64-like segment (end of string)
)

def is_gupshup_handle_id(id_string: str) -> bool:
    """
    Checks if the provided string matches the characteristic format of a 
    Gupshup media handle ID.
    
    This function should be used to decide whether to skip media upload.
    """
    if not id_string or len(id_string) < 50: # Handle IDs are typically very long
        return False
        
    return bool(GUPSHUP_HANDLE_ID_PATTERN.match(id_string))
