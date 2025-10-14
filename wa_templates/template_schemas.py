import logging
try:
    from jsonschema import validate, Draft7Validator, FormatChecker
    from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
except ImportError:
    validate = None
    Draft7Validator = None
    FormatChecker = None
    JsonSchemaValidationError = None

logger = logging.getLogger(__name__)


class PayloadValidationError(Exception):
    """Exception carrying a dict of frontend-friendly error messages.

    errors: dict mapping JSON path (dot/bracket notation) -> human message
    """

    def __init__(self, errors):
        super().__init__('Payload validation failed')
        self.errors = errors

# --- Common Schemas ---

BUTTON_SCHEMA = {
    'type': 'object',
    'properties': {
        'type': {'type': 'string', 'enum': ['QUICK_REPLY', 'URL', 'PHONE_NUMBER']},
        'text': {'type': 'string', 'maxLength': 25},
        'url': {'type': 'string', 'format': 'uri'},
        'phone_number': {'type': 'string', 'maxLength': 25},
        'buttonValue': {'type': 'string'},
        'suffix': {'type': 'string'},
        'example': {'type': 'array', 'items': {'type': 'string'}},
    },
    'required': ['type', 'text'],
    'additionalProperties': True,
    'if': {'properties': {'type': {'const': 'URL'}}},
    'then': {'required': ['url', 'buttonValue']},
    'if': {'properties': {'type': {'const': 'PHONE_NUMBER'}}},
    'then': {'required': ['phone_number']},
}

# --- Template Type Schemas (Validates the ENTIRE Input Data) ---

BASE_TEMPLATE_SCHEMA = {
    'type': 'object',
    'properties': {
        'elementName': {'type': 'string', 'maxLength': 200},
        'languageCode': {'type': 'string', 'maxLength': 10},
        'content': {'type': 'string'},
        'category': {'type': 'string'}, # Assuming Category is validated by DRF choices
        'vertical': {'type': 'string', 'maxLength': 180},
        'example': {'type': 'string'},
        'templateType': {'type': 'string', 'enum': ['TEXT', 'IMAGE', 'VIDEO', 'DOCUMENT', 'CAROUSEL', 'CATALOG']},
        'footer': {'type': ['string', 'null'], 'maxLength': 180},
        'header': {'type': ['string', 'null'], 'maxLength': 180},
        'exampleHeader': {'type': ['string', 'null']},
        'media_url': {'type': ['string', 'null'], 'format': 'uri'}, # Model field
        'enableSample': {'type': 'boolean'}, # Model field
        'payload': {'type': 'object'}, # Placeholder for nested validation
        'allowTemplateCategoryChange': {'type': 'boolean'},
    },
    'required': [
        'elementName', 
        'languageCode', 
        'content', 
        'category', 
        'vertical', 
        'example', 
        'templateType',
        'enableSample',
    ],
    'additionalProperties': True, # Allow other top-level fields (e.g., org_id, app_id, etc.)
}

# TEXT TEMPLATE SCHEMA
TEXT_SCHEMA = dict(BASE_TEMPLATE_SCHEMA, **{
    'properties': dict(BASE_TEMPLATE_SCHEMA['properties'], **{
        'payload': {
            'type': 'object',
            'properties': {
                'buttons': {'type': 'array', 'items': BUTTON_SCHEMA, 'maxItems': 10},
            },
            'additionalProperties': True,
        }
    }),
    'required': BASE_TEMPLATE_SCHEMA['required'] # Ensure payload is present for buttons validation
})

# MEDIA TEMPLATE SCHEMA (IMAGE, VIDEO, DOCUMENT)
MEDIA_SCHEMA = {
    **BASE_TEMPLATE_SCHEMA,
    'properties': {
        **BASE_TEMPLATE_SCHEMA['properties'],
        'payload': {
            'type': 'object',
            'properties': {
                'buttons': {'type': 'array', 'items': BUTTON_SCHEMA, 'maxItems': 10},
            },
            'additionalProperties': True,
        },
    },
    'required': BASE_TEMPLATE_SCHEMA['required'],
    'allOf': [
        {
            'if': {'properties': {'enableSample': {'const': True}}},
            'then': {
                'required': ['media_url'],
                'properties': {
                    'media_url': {'not': {'type': 'null'}},
                }
            }
        }
    ],
}

# CAROUSEL TEMPLATE SCHEMA
CAROUSEL_CARD_SCHEMA = {
    'type': 'object',
    'properties': {
        'mediaUrl': {'type': ['string', 'null'], 'format': 'uri'},
        'body': {'type': 'string'},
        'sampleText': {'type': 'string'},
        'buttons': {'type': 'array', 'items': BUTTON_SCHEMA, 'maxItems': 2},
        'example':{'type': 'array', 'items': {'type': 'string'}},
    },
    'required': ['mediaUrl', 'body', 'headerType', 'buttons'], # Buttons are mandatory on cards
    'additionalProperties': True,
}

CAROUSEL_SCHEMA = dict(BASE_TEMPLATE_SCHEMA, **{
    'properties': dict(BASE_TEMPLATE_SCHEMA['properties'], **{
        'payload': {
            'type': 'object',
            'properties': {
                'cards': {
                    'type': 'array',
                    'items': CAROUSEL_CARD_SCHEMA,
                    'minItems': 1,
                    'maxItems': 10,
                },
            },
            'required': ['cards'],
            'additionalProperties': True,
        }
    }),
    'required': BASE_TEMPLATE_SCHEMA['required'] + ['enableSample', 'payload']
})


SCHEMAS = {
    'TEXT': TEXT_SCHEMA,
    'IMAGE': MEDIA_SCHEMA,
    'VIDEO': MEDIA_SCHEMA,
    'DOCUMENT': MEDIA_SCHEMA,
    'CAROUSEL': CAROUSEL_SCHEMA,
    'CATALOG': BASE_TEMPLATE_SCHEMA, # Minimal validation for CATALOG
}


def validate_payload(templateType, data):
    """
    Validate the entire template data dictionary against schema rules for the given template type.
    
    In this context, 'data' is the full dictionary from serializer.validated_data.
    Raises PayloadValidationError with dict of errors if invalid.
    """
    logger.debug('Validating full template data for type %s', templateType)
    
    schema = SCHEMAS.get(templateType)
    
    if not schema:
        logger.error('No schema found for template type: %s', templateType)
        raise PayloadValidationError({'_schema': f'No schema for template type {templateType}'})
        
    if Draft7Validator is None or FormatChecker is None:
        logger.error('jsonschema library is not installed')
        raise ImportError('jsonschema is required to validate payloads. Install via pip install jsonschema')

    # --- 1. Perform Schema Validation on the entire data dictionary ---
    
    # NOTE: We use data (the full validated_data) here, not just data.get('payload')
    validator = Draft7Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(data), key=lambda e: e.path)
    logger.debug('Found %d schema validation errors', len(errors))
    
    if errors:
        errs = {}
        for e in errors:
            # build a readable path
            path = []
            for p in e.path:
                if isinstance(p, int):
                    if path:
                        path[-1] = f"{path[-1]}[{p}]"
                    else:
                        path.append(f"[{p}]")
                else:
                    path.append(str(p))
            
            # Use the field name as the key, prefix nested errors with 'payload.'
            key = '.'.join(path) if path else '_schema'
            errs[key] = e.message
            
        raise PayloadValidationError(errs)

    # --- 2. Additional Semantic Checks ---
    
    # Check for CAROUSEL specific requirements (media existence check)
    if templateType == 'CAROUSEL':
        # Safely access nested cards using .get()
        cards = data.get('payload', {}).get('cards') or []
        for idx, c in enumerate(cards):
            # Check for media reference on each card
            if not (c.get('mediaUrl') or c.get('mediaId') or c.get('exampleMedia')):
                raise PayloadValidationError({
                    f'payload.cards[{idx}]': 'Each card requires mediaUrl, mediaId, or exampleMedia.'
                })