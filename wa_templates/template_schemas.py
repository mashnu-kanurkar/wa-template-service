try:
    from jsonschema import validate, Draft7Validator, FormatChecker
    from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
except Exception:
    validate = None
    Draft7Validator = None
    FormatChecker = None
    JsonSchemaValidationError = None


class PayloadValidationError(Exception):
    """Exception carrying a dict of frontend-friendly error messages.

    errors: dict mapping JSON path (dot/bracket notation) -> human message
    """

    def __init__(self, errors):
        super().__init__('Payload validation failed')
        self.errors = errors

# JSON Schemas for each template type. These are simplified but capture required structure.
BUTTON_SCHEMA = {
    'type': 'object',
    'properties': {
        'type': {'type': 'string', 'enum': ['QUICK_REPLY', 'URL', 'CALL']},
        'text': {'type': 'string'},
        'url': {'type': 'string', 'format': 'uri'},
        'buttonValue': {'type': 'string'},
        'suffix': {'type': 'string'},
    },
    'required': ['type', 'text'],
    'additionalProperties': True,
    'if': {'properties': {'type': {'const': 'URL'}}},
    'then': {'required': ['url', 'buttonValue']},
}

TEXT_SCHEMA = {
    'type': 'object',
    'properties': {
        'elementName': {'type': 'string', 'maxLength': 180},
        'languageCode': {'type': 'string'},
        'content': {'type': 'string', 'maxLength': 1024},
        'category': {'type': 'string'},
        'vertical': {'type': 'string', 'maxLength': 180},
        'footer': {'type': ['string', 'null']},
        'example': {'type': 'string'},
        'header': {'type': ['string', 'null']},
    'buttons': {'type': 'array', 'items': BUTTON_SCHEMA},
        'allowTemplateCategoryChange': {'type': 'boolean'},
        'appId': {'type': 'string'},
    },
    'required': ['elementName', 'content', 'category', 'vertical', 'example']
}

MEDIA_SCHEMA = {
    'type': 'object',
    'properties': {
        'elementName': {'type': 'string', 'maxLength': 180},
        'languageCode': {'type': 'string'},
        'content': {'type': 'string'},
        'category': {'type': 'string'},
        'vertical': {'type': 'string', 'maxLength': 180},
        'footer': {'type': ['string', 'null']},
        'example': {'type': 'string'},
    'exampleMedia': {'type': ['string', 'null']},
        'enableSample': {'type': ['boolean', 'null']},
        'allowTemplateCategoryChange': {'type': 'boolean'},
        'appId': {'type': 'string'},
    },
    'required': ['elementName', 'content', 'category', 'vertical', 'example', 'appId'],
    'if': {'properties': {'enableSample': {'const': True}}},
    'then': {'required': ['exampleMedia']}
}

CAROUSEL_SCHEMA = {
    'type': 'object',
    'properties': {
        'elementName': {'type': 'string', 'maxLength': 180},
        'languageCode': {'type': 'string'},
        'content': {'type': 'string'},
        'category': {'type': 'string'},
        'vertical': {'type': 'string'},
        'example': {'type': 'string'},
        'enableSample': {'type': ['boolean', 'null']},
        'cards': {
            'type': 'array',
            'items': {
                'type': 'object',
                'properties': {
                    'headerType': {'type': 'string', 'enum': ['IMAGE', 'VIDEO', 'DOCUMENT']},
                    'mediaUrl': {'type': ['string', 'null'], 'format': 'uri'},
                    'mediaId': {'type': ['string', 'null']},
                    'exampleMedia': {'type': ['string', 'null']},
                    'body': {'type': 'string'},
                    'sampleText': {'type': 'string'},
                    'buttons': {'type': 'array', 'items': BUTTON_SCHEMA},
                },
                'required': ['body'],
                'additionalProperties': True,
            }
        },
        'allowTemplateCategoryChange': {'type': 'boolean'},
        'appId': {'type': 'string'},
    },
    'required': ['elementName', 'content', 'category', 'vertical', 'example', 'cards', 'appId']
}

SCHEMAS = {
    'TEXT': TEXT_SCHEMA,
    'IMAGE': MEDIA_SCHEMA,
    'VIDEO': MEDIA_SCHEMA,
    'DOCUMENT': MEDIA_SCHEMA,
    'CAROUSEL': CAROUSEL_SCHEMA,
    'CATALOG': {'type': 'object'},
}


def validate_payload(template_type, payload):
    schema = SCHEMAS.get(template_type)
    if not schema:
        raise PayloadValidationError({'_schema': f'No schema for template type {template_type}'})
    # jsonschema may not be installed in the environment running unit tests for
    # unrelated modules. Delay raising an ImportError until validation is needed.
    if Draft7Validator is None or FormatChecker is None:
        raise ImportError('jsonschema is required to validate payloads. Install via pip install jsonschema')

    validator = Draft7Validator(schema, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(payload), key=lambda e: e.path)
    if errors:
        errs = {}
        for e in errors:
            # build a readable path
            path = []
            for p in e.path:
                if isinstance(p, int):
                    # array index
                    if path:
                        path[-1] = f"{path[-1]}[{p}]"
                    else:
                        path.append(f"[{p}]")
                else:
                    path.append(str(p))
            key = '.'.join(path) if path else '_schema'
            # friendly message
            errs[key] = e.message
        raise PayloadValidationError(errs)
    # additional checks: buttons/cards structure
    # validate buttons if present
    # additional semantic checks with friendly messages
    if 'buttons' in payload and isinstance(payload['buttons'], list):
        for idx, b in enumerate(payload['buttons']):
            if not isinstance(b, dict):
                raise PayloadValidationError({f'buttons[{idx}]': 'Each button must be an object'})
            if 'type' not in b or 'text' not in b:
                raise PayloadValidationError({f'buttons[{idx}]': 'Each button must include type and text'})
            if b.get('type') == 'URL':
                if not b.get('url') or not b.get('buttonValue'):
                    raise PayloadValidationError({f'buttons[{idx}]': 'URL buttons require url and buttonValue'})
    # validate cards structure for carousel
    if template_type == 'CAROUSEL':
        cards = payload.get('cards') or []
        if not isinstance(cards, list) or len(cards) == 0:
            raise PayloadValidationError({'cards': 'cards must be a non-empty list'})
        for idx, c in enumerate(cards):
            if not isinstance(c, dict):
                raise PayloadValidationError({f'cards[{idx}]': 'each card must be an object'})
            if not (c.get('mediaUrl') or c.get('mediaId') or c.get('exampleMedia')):
                raise PayloadValidationError({f'cards[{idx}]': 'each card requires mediaUrl or mediaId or exampleMedia'})
