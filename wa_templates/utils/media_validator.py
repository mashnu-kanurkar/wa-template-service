import mimetypes
import re
from urllib.parse import urlparse
from django.core.validators import URLValidator
from django.core.exceptions import ValidationError
import logging

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

def is_valid_media_url(url: str, expected_mime: str) -> bool:
    """
    Validates that:
      1. URL is a valid HTTP(S) URL
      2. The file extension maps to the expected MIME type
      3. The MIME type is one of the allowed ones
    """
    if not url:
        return False

    # 1. Basic URL structure validation
    try:
        URLValidator(schemes=['http', 'https'])(url)
    except ValidationError:
        logger.debug(f"Invalid URL structure: {url}")
        return False

    # 2. MIME type check validity
    if expected_mime not in ALLOWED_MIME_TYPES:
        logger.warning(f"Unexpected MIME type provided: {expected_mime}")
        return False

    # 3. Infer MIME type from file extension
    parsed_url = urlparse(url)
    url_path = parsed_url.path.lower()

    guessed_mime, _ = mimetypes.guess_type(url_path)

    if not guessed_mime:
        logger.debug(f"Could not infer MIME type from URL: {url}")
        return False

    # 4. Match inferred MIME with expected
    if guessed_mime != expected_mime:
        logger.debug(f"MIME type mismatch: expected {expected_mime}, got {guessed_mime}")
        return False

    # 5. Finally, check that expected MIME is allowed
    if expected_mime not in ALLOWED_MIME_TYPES:
        logger.debug(f"MIME {expected_mime} not in allowed list.")
        return False

    logger.debug(f"URL '{url}' is valid for MIME type '{expected_mime}'")
    return True
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
