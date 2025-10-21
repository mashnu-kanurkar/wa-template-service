from datetime import datetime
import json
from celery import current_task, shared_task

from wa_templates.utils import constants
from wa_templates.utils.google_sheets import GoogleSheetCatalog
from wa_templates.webhooks.gupshup_webhook import handle_gupshup_template_webhook
from .models import CatalogMetadata, WhatsAppTemplate, ProviderAppInstance
from .providers.factory import get_provider
import logging
from django.db import transaction
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
import uuid
from django.core.files.storage import default_storage
from django.core.files.base import ContentFile
import os


logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retried=3)
def process_gupshup_webhook(self, webhook_data):
    self.update_state(state='PROGRESS', meta={'current': 0, 'total': 3, 'status': 'Starting sync'})
    logger.info("Processing incoming webhook event")
    try:
        processed = handle_gupshup_template_webhook(webhook_data=webhook_data)
        if processed:
            self.update_state(state='PROGRESS', meta={'current': 3, 'total': 3, 'status': 'Processed successfully'})
        else:
            raise ValueError("Something went wrong")
    except Exception as e:
        error_msg = f'Max retries exceeded. Final error: {e}'
        self.update_state(state='FAILURE', meta={
                'status': error_msg,
                'exc_type': type(e).__name__,
                'exc_message': str(e)
            })
        raise ValueError(error_msg)

@shared_task(bind=True, max_retries=3)
def sync_templates_for_app_id(self, app_id, org_id):
    self.update_state(state='PROGRESS', meta={'current': 0, 'total': 3, 'status': 'Starting sync'})
    logger.info('Syncing templates from provider %s', app_id)

    try:
        provider_instance = ProviderAppInstance.objects.get(organisation_id=org_id, app_id=app_id)
    except ProviderAppInstance.DoesNotExist as e:
        error_message = f'Provider instance not found: {app_id}'
        logger.error(error_message)
        self.update_state(state='FAILURE', meta={
            'status': error_message,
            'exc_type': type(e).__name__,
            'exc_message': str(e)
        })
        raise ValueError(error_message)

    app_token = provider_instance.get_app_token()
    if not app_token:
        error_msg = f'No app token found for provider instance: {provider_instance.app_id}'
        logger.error(error_msg)
        self.update_state(state='FAILURE', meta={
            'status': error_msg,
            'exc_type': 'ValueError',
            'exc_message': error_msg
        })
        raise ValueError(error_msg)

    provider = get_provider(provider_instance.provider_name, 
                            app_token=app_token, 
                            app_id=provider_instance.app_id, 
                            org_id = provider_instance.organisation.id)
    self.update_state(state='PROGRESS', meta={'current': 1, 'total': 3, 'status': 'Provider initialized'})

    try:
        response = provider.get_templates()
        logger.debug(f'sync template response: {response}')
        if not response.get('ok'):
            error_message = response.get('response', 'Unknown error fetching templates')
            logger.error(error_message)
            self.update_state(state='FAILURE', meta={
                'status': error_message,
                'exc_type': 'ValueError',
                'exc_message': error_message
            })
            raise ValueError(error_message)

        templates_to_update = response.get('response', [])
        logger.info('Fetched %d templates', len(templates_to_update))
        self.update_state(state='PROGRESS', meta={'current': 2, 'total': 3, 'status': 'Processing templates'})

        # Bulk update / create
        with transaction.atomic():
            WhatsAppTemplate.objects.bulk_update(
                [t for t in templates_to_update if t.pk],
                fields=['category', 'templateType', 'status', 'modifiedOn', 'meta', 'containerMeta', 'hash']
            )
            WhatsAppTemplate.objects.bulk_create([t for t in templates_to_update if not t.pk])

        self.update_state(state='PROGRESS', meta={'current': 3, 'total': 3, 'status': 'Sync successful'})
        return {'status': 'SUCCESS', 'synced': len(templates_to_update)}

    except Exception as e:
        logger.error('Error syncing templates for provider %s: %s', app_id, e)
        try:
            raise self.retry(exc=e, countdown=2**self.request.retries)
        except self.MaxRetriesExceededError:
            error_msg = f'Max retries exceeded. Final error: {e}'
            self.update_state(state='FAILURE', meta={
                'status': error_msg,
                'exc_type': type(e).__name__,
                'exc_message': str(e)
            })
            raise ValueError(error_msg)
    



@shared_task(bind=True, max_retries=3)
def submit_template_for_approval(self, template_id, app_id, org_id):
    # 1. Report initial status
    self.update_state(state='PROGRESS', meta={'current': 0, 'total': 3, 'status': 'Starting submission lookup'})
    logger.info('Submitting template for approval: %s', template_id)
    
    # --- Step 1: Database Lookup ---
    try:
        t = WhatsAppTemplate.objects.get(id=template_id)
        provider_instance_object = ProviderAppInstance.objects.get(
            organisation_id=org_id,
            app_id=app_id
        )
    except (WhatsAppTemplate.DoesNotExist, ProviderAppInstance.DoesNotExist) as e:
        logger.error('Database object not found for template %s: %s', template_id, e)
        error_message = 'Either template or provider instance not found in database'
        self.update_state(state='FAILURE', meta={
            'status': error_message,
            'exc_type': type(e).__name__,
            'exc_message': str(e)
        })
        raise ValueError(error_message)
    
    app_token = provider_instance_object.get_app_token()

    if not app_token:
        error_msg = f'No app token found for provider instance: {provider_instance_object.app_id}'
        logger.error(error_msg)
        self.update_state(state='FAILURE', meta={
            'status': error_msg,
            'exc_type': type(ValueError(error_msg)).__name__,
            'exc_message': error_msg
        })
        raise ValueError(error_message)
    
    # --- Step 2: Initialize Provider and Report Progress ---
    self.update_state(state='PROGRESS', meta={'current': 1, 'total': 3, 'status': 'Provider initialized, preparing payload.'})

    provider = get_provider(
        provider_instance_object.provider_name,
        app_token=app_token, 
        app_id=provider_instance_object.app_id,
        org_id = provider_instance_object.organisation.id
    )

    # --- Step 3: Call Provider Submission Method ---
    try:
        self.update_state(state='PROGRESS', meta={'current': 2, 'total': 3, 'status': 'Submitting to external provider.'})
        resp = provider.submit_template(t)
        
        # Ensure resp is a dictionary with 'ok' and 'response' keys
        t.provider_metadata.update({'last_update': str(datetime.now().timestamp())})

        if resp.get('ok'):
            logger.info('Template %s successfully submitted.', template_id)
            self.update_state(state='PROGRESS', meta={'current': 3, 'total': 3, 'status': 'Successfully submitted.'})
            t.update_error_meta(
                        constants.GupshupAction.APPLY_TEMPLATE.value,
                        'Success'
                    )
            message = f'Template {t.provider_template_id} submitted to gupshup'
            return {'status': 'SUCCESS', 'response': message}
        else:
            error_message = resp.get('response', 'Unknown submission error.')
            logger.error('Failed to submit template %s: %s', template_id, error_message)
            t.update_error_meta(
                        constants.GupshupAction.APPLY_TEMPLATE.value,
                        error_message
                    )
            self.update_state(state='FAILURE', meta={
                'status': error_message,
                'exc_type': type(ValueError(error_message)).__name__,
                'exc_message': error_message
            })
            raise ValueError(error_message)
            
    except Exception as e:
        logger.error('Error submitting template %s for approval: %s', template_id, e)
        try:
            raise self.retry(exc=e, countdown=2**self.request.retries)
        except self.MaxRetriesExceededError:
            error_msg = f'Max retries exceeded. Final error: {e}'
            t.update_error_meta(
                        constants.GupshupAction.APPLY_TEMPLATE.value,
                        error_message
                    )
            self.update_state(state='FAILURE', meta={
                'status': error_msg,
                'exc_type': type(e).__name__,
                'exc_message': str(e)
            })
            raise ValueError(error_message)


@shared_task(bind=True, max_retries=3)
def update_template_with_provider(self, template_id, app_id, org_id):
    # 1. Report initial status
    self.update_state(state='PROGRESS', meta={'current': 0, 'total': 3, 'status': 'Starting update lookup'})
    logger.info('Updating template for: %s', template_id)
    
    # --- Step 1: Database Lookup ---
    try:
        t = WhatsAppTemplate.objects.get(id=template_id)
        provider_instance_object = ProviderAppInstance.objects.get(
            organisation_id=org_id,
            app_id=app_id
        )
    except (WhatsAppTemplate.DoesNotExist, ProviderAppInstance.DoesNotExist) as e:
        logger.error('Database object not found for template %s: %s', template_id, e)
        error_message = 'Either template or provider instance not found in database'
        self.update_state(state='FAILURE', meta={
            'status': error_message,
            'exc_type': type(e).__name__,
            'exc_message': str(e)
        })
        raise ValueError(error_message)

    app_token = provider_instance_object.get_app_token()
    if not app_token:
        error_msg = f'No app token found for provider instance: {provider_instance_object.app_id}'
        logger.error(error_msg)
        self.update_state(state='FAILURE', meta={
            'status': error_msg,
            'exc_type': type(ValueError(error_msg)).__name__,
            'exc_message': error_msg
        })
        raise ValueError(error_message)
    
    # --- Step 2: Initialize Provider and Report Progress ---
    self.update_state(state='PROGRESS', meta={'current': 1, 'total': 3, 'status': 'Provider initialized, calling update method.'})

    provider = get_provider(
        provider_instance_object.provider_name,
        app_token=app_token,
        app_id=provider_instance_object.app_id,
        org_id = provider_instance_object.organisation.id
    )

    # --- Step 3: Call Provider Update Method ---
    try:
        self.update_state(state='PROGRESS', meta={'current': 2, 'total': 3, 'status': 'Submitting update to external provider.'})
        result = provider.update_template(t)
        
        t.provider_metadata.update({'last_update': result})

        if result.get('ok'):
            logger.info("Template %s updated and status set to 'pending'.", t.id)
            self.update_state(state='PROGRESS', meta={'current': 3, 'total': 3, 'status': 'Update successfully submitted.'})
            t.update_error_meta(
                        constants.GupshupAction.UPDATE_TEMPLATE.value,
                        "Success"
                    )
            message = f'Template {t.provider_template_id} submitted to gupshup'
            return {'status': 'SUCCESS', 'response': message}
        else:
            error_message = result.get('response', 'Unknown update error.')
            logger.error("Failed to update template %s with provider: %s", t.id, error_message)
            t.update_error_meta(
                        constants.GupshupAction.UPDATE_TEMPLATE.value,
                        error_message
                    )
            self.update_state(state='FAILURE', meta={
                'status': error_message,
                'exc_type': type(ValueError(error_message)).__name__,
                'exc_message': error_message
            })
            raise ValueError(error_message)
            
    except Exception as e:
        logger.error('Error updating template %s: %s', template_id, e)
        try:
            raise self.retry(exc=e, countdown=2**self.request.retries)
        except self.MaxRetriesExceededError:
            error_msg = f'Max retries exceeded. Final error: {e}'
            t.update_error_meta(
                        constants.GupshupAction.APPLY_TEMPLATE.value,
                        error_message
                    )
            self.update_state(state='FAILURE', meta={
                'status': error_msg,
                'exc_type': type(e).__name__,
                'exc_message': str(e)
            })
            raise ValueError(error_message)

@shared_task(bind=True, max_retries=3)
def delete_template_with_provider(self, template_id, app_id, org_id):
    self.update_state(state='PROGRESS', meta={'current': 0, 'total': 3, 'status': 'Starting template deletion process'})

    logger.info('Submitting template for approval: %s', template_id)
    try:
        t = WhatsAppTemplate.objects.get(id=template_id)
        provider_instance_object = ProviderAppInstance.objects.get(
                organisation_id=org_id,
                app_id=app_id
            )
    except WhatsAppTemplate.DoesNotExist:
        logger.error('Template not found: %s', template_id)
        error_message = f'Template {template_id} not found in database'
        self.update_state(state='FAILURE', meta={
            'status': 'Template not found in database',
            'exc_type': type(ValueError(error_message)).__name__,
            'exc_message': error_message
        })
        raise ValueError(error_message)
    
    if not provider_instance_object:  # should not happen
        logger.error('Provider instance not found for template: %s', template_id)
        error_message = f'Provider instance not found for template {template_id}'
        self.update_state(state='FAILURE', meta={
            'status': 'Provider instance not found',
            'exc_type': type(ValueError(error_message)).__name__,
            'exc_message': error_message
        })
        raise ValueError(error_message)

    provider = get_provider(provider_instance_object.provider_name,
                            app_token=provider_instance_object.get_app_token(), 
                            app_id=provider_instance_object.app_id,
                            org_id = provider_instance_object.organisation.id)
    
    self.update_state(state='PROGRESS', meta={'current': 1, 'total': 3, 'status': 'Provider initialized, attempting external deletion.'})
    # Call the new delete method
    try:
        result = provider.delete_template(t)

        if result.get('ok'):
            logger.info("Template %s successfully deleted from provider.", t.id)
            self.update_state(state='PROGRESS', meta={'current': 3, 'total': 3, 'status': 'Successfully deleted from provider'})
            t.delete()
            return {'status': 'SUCCESS', 'message': f'Template {t.id} (provider template id {t.provider_template_id}) deleted.'}
        else:
            logger.error("Failed to delete template %s from provider: %s", t.id, result.get('response'))
            error_message = result.get('response', 'Unknown provider error')
            t.update_error_meta(
                        constants.GupshupAction.DELETE_TEMPLATE.value,
                        error_message
                    )
            self.update_state(state='FAILURE', meta={
                'status': error_message,
                'exc_type': type(ValueError(error_message)).__name__,
                'exc_message': error_message
            })
            raise ValueError(error_message)

    except Exception as e:
        logger.error('Error deleting template %s: %s', template_id, e)
        try:
            raise self.retry(exc=e, countdown=2**self.request.retries)
        except self.MaxRetriesExceededError:
            error_msg = f'Max retries exceeded. Final error: {e}'
            t.update_error_meta(
                        constants.GupshupAction.DELETE_TEMPLATE.value,
                        error_message
                    )
            self.update_state(state='FAILURE', meta={
                'status': error_msg,
                'exc_type': type(e).__name__,
                'exc_message': str(e)
            })
            raise ValueError(error_message)

@shared_task(bind=True, max_retries=3)
def move_catalog_service_file_async(self, catalog_id, provider_app_id, temp_path, filename):
    """
    Moves catalog service JSON file from temp or current storage to final destination asynchronously.
    Updates progress state for TaskStatusView to track.
    """
    try:
        self.update_state(state='PROGRESS', meta={'current': 0, 'total': 4, 'status': 'Initializing file move'})
        logger.info("[Catalog:%s] Starting move task", catalog_id)

        catalog = CatalogMetadata.objects.get(id=catalog_id)
        final_path = f"catalog_credentials/{provider_app_id}/{catalog_id}/{filename}"

        # Step 1: Resolve file path
        if os.path.exists(temp_path):
            source_path = temp_path
        elif default_storage.exists(temp_path):
            # For remote storage (S3, GCS, etc.)
            source_path = default_storage.path(temp_path)
        else:
            logger.warning("[Catalog:%s] File not found at %s, skipping move", catalog_id, temp_path)
            return {'status': 'File not found, skipped move'}

        self.update_state(state='PROGRESS', meta={'current': 1, 'total': 4, 'status': 'Validated source file'})
        logger.info("[Catalog:%s] Validated source file exists", catalog_id)

        # Step 2: Read and save to final destination
        with open(source_path, "rb") as f:
            file_data = f.read()

        saved_path = default_storage.save(final_path, ContentFile(file_data))
        self.update_state(state='PROGRESS', meta={'current': 2, 'total': 4, 'status': 'Saved file to final destination'})
        logger.info("[Catalog:%s] Moved file to %s", catalog_id, saved_path)

        # Step 3: Delete old file if different
        if source_path != saved_path and os.path.exists(source_path):
            os.remove(source_path)
            logger.info("[Catalog:%s] Deleted source file %s", catalog_id, source_path)

        self.update_state(state='PROGRESS', meta={'current': 3, 'total': 4, 'status': 'Deleted old file'})

        # Step 4: Update model reference
        catalog.google_service_file.name = saved_path
        catalog.save(update_fields=["google_service_file"])
        self.update_state(state='PROGRESS', meta={'current': 4, 'total': 4, 'status': 'Updated catalog model'})
        logger.info("[Catalog:%s] Catalog updated successfully", catalog_id)

        return {'status': 'Completed successfully', 'path': saved_path}

    except Exception as e:
        error_msg = f"Error moving catalog service file: {str(e)}"
        logger.exception("[Catalog:%s] %s", catalog_id, error_msg)
        self.update_state(
            state='FAILURE',
            meta={
                'status': error_msg,
                'exc_type': type(e).__name__,
                'exc_message': str(e),
            }
        )
        raise ValueError(error_msg)




def update_progress(current, total, status="In progress"):
    current_task.update_state(
        state="PROGRESS",
        meta={"current": current, "total": total, "status": status}
    )

@shared_task(bind=True)
def read_catalog_data_task(self, sheet_url, service_file):
    try:
        update_progress(0, 1, "Starting to read catalog data")
        google_catalog = GoogleSheetCatalog(sheet_url, service_file)
        data = google_catalog.read_all()
        # data = read_catalog(sheet_url, service_file)
        update_progress(1, 1, "Catalog data read successfully")
        return {"status": "success", "data": data}
    except Exception as e:
        logger.exception("Error reading catalog data")
        error_msg = f"Error reading catalog data: {str(e)}"
        self.update_state(state='FAILURE', meta={
                'status': error_msg,
                'exc_type': type(e).__name__,
                'exc_message': str(e)
            })
        raise ValueError(str(e))

@shared_task(bind=True)
def sync_catalog_product_batch_task(self, sheet_url, service_file_content, payload, partial=True):
    import json
    """
    Unified task for add/update/delete catalog products
    payload = {
        "add": [...],
        "update": [...],
        "delete": [...]
    }
    """
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            logger.error(f"Invalid payload string received: {payload}")
            raise

    logger.info(f"Starting catalog batch task for payload: {payload.keys()}")
    try:
        google_catalog = GoogleSheetCatalog(sheet_url, service_file_content)
        task_status = google_catalog.batch_write(
            add_list=payload.get("add"),
            update_list=payload.get("update"),
            delete_list=payload.get("delete"),
            partial=partial
        )
        
        logger.info("Catalog batch task completed successfully")
        return {"status": "success", "task_status": task_status}
    except Exception as e:
        logger.exception(f"Error in catalog batch task: {e}")
        error_msg = f"Error in catalog batch task: {str(e)}"
        self.update_state(state='FAILURE', meta={
                'status': error_msg,
                'exc_type': type(e).__name__,
                'exc_message': str(e)
            })
        raise ValueError(str(e))

@shared_task(bind=True)
def add_catalog_product_task(self, sheet_url, service_file, product_data):
    try:
        update_progress(0, 1, "Starting to add product")
        google_catalog = GoogleSheetCatalog(sheet_url, service_file)
        google_catalog.add_row(sheet_url, service_file, product_data)
        update_progress(1, 1, "Product added successfully")
        return {"status": "success", "product_id": product_data.get("id")}
    except Exception as e:
        logger.exception("Error adding catalog product")
        error_msg = f"Error adding catalog product: {str(e)}"
        self.update_state(state='FAILURE', meta={
                'status': error_msg,
                'exc_type': type(e).__name__,
                'exc_message': str(e)
            })
        raise ValueError(str(e))

@shared_task(bind=True)
def update_catalog_product_task(self, sheet_url, service_file, updated_data):
    try:
        update_progress(0, 1, f"Starting to update product")
        products = updated_data.get("products", [])
        google_catalog = GoogleSheetCatalog(sheet_url, service_file)
        if not products:
            return {"updated": 0, "warning": "No products provided"}
        
        if len(products) == 0:
            return {"updated": 0, "warning": "No products provided"}
        
        if len(products)<2:
            google_catalog.add_row(sheet_url, service_file, products[0])
            return {"status": "success", "updated": 1}
        
        google_catalog.bulk_write(sheet_url, service_file, products)
        return {"status": "success", "updated": len(products)}

        # updated = update_row(sheet_url, service_file, product_id, updated_data)
        # if not updated:
        #     raise ValueError(f"Product ID {product_id} not found")
        # update_progress(1, 1, f"Product {product_id} updated successfully")
        # return {"status": "success", "product_id": product_id}
    except Exception as e:
        logger.exception(f"Error updating catalog product")
        error_msg = f"Error updating catalog product: {str(e)}"
        self.update_state(state='FAILURE', meta={
                'status': error_msg,
                'exc_type': type(e).__name__,
                'exc_message': str(e)
            })
        raise ValueError(str(e))

@shared_task(bind=True)
def delete_catalog_product_task(self, sheet_url, service_file, data):
    try:
        """
        Bulk delete catalog products.
        data: { "products": ["id1", "id2", ...] }
        """
        product_ids = data.get("products", [])
        if not product_ids:
            return {"deleted": 0, "warning": "No product IDs provided"}

        google_catalog = GoogleSheetCatalog(sheet_url, service_file)
        update_progress(0, 1, f"Starting to delete product {data}")

        deleted_count = google_catalog.bulk_delete(sheet_url, service_file, product_ids)
        return {"status": "success", "deleted": deleted_count}

        # deleted = delete_row(sheet_url, service_file, product_id)
        # if not deleted:
        #     raise ValueError(f"Product ID {product_id} not found")
        # update_progress(1, 1, f"Product {product_id} deleted successfully")
        # return {"status": "success", "product_id": product_id}
    except Exception as e:
        logger.exception(f"Error deleting catalog product")
        error_msg = f"Error deleting catalog product: {str(e)}"
        self.update_state(state='FAILURE', meta={
                'status': error_msg,
                'exc_type': type(e).__name__,
                'exc_message': str(e)
            })
        raise ValueError(str(e))

#----------------------------------------------------------------------
# Not in use - legacy single update task
#----------------------------------------------------------------------
@shared_task(bind=True)
def bulk_update_catalog_task(self, sheet_url, service_file, updates):
    try:
        google_catalog = GoogleSheetCatalog(sheet_url, service_file)
        total = len(updates)
        for i, upd in enumerate(updates, start=1):
            product_id = upd.get("id")
            google_catalog.update_row(sheet_url, service_file, product_id, upd)
            update_progress(i, total, f"Updated {i}/{total} products")
        return {"status": "success", "updated": total}
    except Exception as e:
        logger.exception("Error in bulk updating catalog")
        error_msg = f"Error in bulk updating catalog: {str(e)}"

        self.update_state(state='FAILURE', meta={
                'status': error_msg,
                'exc_type': type(e).__name__,
                'exc_message': str(e)
            })
        raise ValueError(str(e))

