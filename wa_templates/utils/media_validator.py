import re
from urllib.parse import urlparse
from django.core.validators import URLValidator
from django.core.exceptions import ValidationError
import logging

logger = logging.getLogger(__name__)
# --- Configuration for file extensions ---
FILE_EXTENSIONS = {
    'IMAGE': ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic'),
    'VIDEO': ('.mp4', '.mov', '.avi', '.webm', '.3gp'),
    'DOCUMENT': ('.pdf', '.doc', '.docx', '.xls', '.xlsx', '.txt', '.csv'),
    # Add other types as needed
}

# ----------------------------------------------------------------------
# 1. URL and Extension Validation
# ----------------------------------------------------------------------

def is_valid_media_url(url: str, file_type: str) -> bool:
    """
    Checks if a URL is structurally correct and ends with an appropriate 
    file extension for the given file_type.
    """
    if not url:
        return False

    # 1. Basic URL structure check using Django's validator
    try:
        URLValidator(schemes=['http', 'https'])(url)
    except ValidationError:
        return False
    
    # 2. File extension check based on type
    file_type = file_type.upper()
    if file_type not in FILE_EXTENSIONS:
        # If type is unknown, treat it as structurally valid but log a warning
        # For this exercise, we enforce a check for known types.
        logger.warning(f"Unknown file_type '{file_type}' provided for URL validation.")
        return False 
        
    required_extensions = FILE_EXTENSIONS[file_type]
    
    # Extract the path part and check the extension
    parsed_url = urlparse(url)
    url_path = parsed_url.path.lower()

    # The file path must end with one of the required extensions
    if not url_path.endswith(required_extensions):
        logger.debug(f"URL extension check failed. Expected: {required_extensions}, Got: {url_path}")
        return False
    
    logger.debug(f"URL '{url}' passed validation for type '{file_type}'")
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
