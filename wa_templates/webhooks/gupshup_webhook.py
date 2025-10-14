import logging
from django.utils import timezone

from wa_templates.models import WhatsAppTemplate
# from .models import WhatsAppTemplate # Assuming your model is imported here

logger = logging.getLogger(__name__)

def handle_gupshup_template_webhook(webhook_data: dict) -> bool:
    """
    Processes Gupshup template-event webhooks, updates main fields, and logs 
    secondary data to the 'webhookMeta' JSONField using a replacement structure.
    """
    
    logger.info("Received Gupshup template webhook. Top-level type: %s", webhook_data.get('type'))
    
    # --- 1. Locate Template (Same logic as before) ---
    payload = webhook_data.get('payload', {})
    template_id = payload.get('id')
    element_name = payload.get('elementName')
    language_code = payload.get('languageCode')
    event_type = payload.get('type') # 'status-update', 'category-update', 'quality-update', or None
    
    template: WhatsAppTemplate = None
    
    # ... (Lookup logic by template_id and then by elementName/languageCode remains unchanged) ...
    if template_id:
        try:
            template = WhatsAppTemplate.objects.get(provider_template_id=template_id)
        except WhatsAppTemplate.DoesNotExist:
            pass
    
    if not template and element_name and language_code:
        try:
            template = WhatsAppTemplate.objects.get(elementName=element_name, languageCode=language_code)
        except WhatsAppTemplate.DoesNotExist:
            logger.error(
                "Template (ID: %s, Name: %s) not found. Webhook processing stopped.",
                template_id, element_name
            )
            return False

    if not template:
        logger.error("Failed to locate template. Webhook processing stopped.")
        return False
        
    original_status = template.status
    main_field_value = ''
    meta_fields_to_update = {}
    
    logger.info(
        "Processing event '%s' for template %s (Current Status: %s).", 
        event_type, template.provider_template_id or template.elementName, original_status
    )

    # --- 2. Process Event Types ---
    
    if event_type in ['status-update', None]:
        status_raw = payload.get('status', '').lower()
        description = payload.get('description')
        
        new_status = status_raw 

        valid_statuses = [c[0] for c in WhatsAppTemplate.STATUS_CHOICES]
        
        if new_status and new_status in valid_statuses:
            main_field_value = new_status
            meta_fields_to_update['status'] = new_status
            logger.info("Status change detected: %s -> %s", original_status, new_status)
        
        # CRITICAL: Update the dedicated status_description field
        if description:
            meta_fields_to_update['status_description'] = description
        else:
            meta_fields_to_update['status_description'] = None # Clear if no new description

        if new_status == 'deleted':
            template.mark_as_deleted()
        
    elif event_type == 'category-update':
        category_data = payload.get('category', {})
        
        new_category = category_data.get('new')
        old_category = category_data.get('old')
        
        if new_category:
            main_field_value = new_category
            meta_fields_to_update['category'] = new_category.upper()
            logger.info("Category change: %s -> %s", template.category, new_category)

        if old_category:
            meta_fields_to_update['oldCategory'] = old_category.upper()
            

    elif event_type == 'quality-update':
        quality_raw = payload.get('quality')
        if quality_raw:
            main_field_value = quality_raw
            meta_fields_to_update['quality'] = quality_raw 
            logger.info("Quality update detected: %s", quality_raw)

    else:
        logger.warning(
            "Unrecognized event type '%s' for template %s. Ignoring payload.",
            event_type, template.provider_template_id
        )
        return False
        
    # --- 3. Final Update and Logging ---
    
    try:
        # Use the helper function to perform the combined update and meta logging
        template._update_and_log_webhook_event(
            event_type = event_type, 
            main_field_value = main_field_value,
            event_payload = meta_fields_to_update
        )

        logger.info("Template %s successfully processed event '%s'. Main fields and webhookMeta updated.", 
                    template.provider_template_id or template.elementName, event_type)
        return True
    except Exception as e:
        logger.exception("FATAL ERROR saving template %s after webhook: %s", template.provider_template_id, e)
        return False