from datetime import datetime
import time
from celery import shared_task
from .models import WhatsAppTemplate, ProviderAppInstance
from .providers.factory import get_provider
import logging
from django.db import transaction


logger = logging.getLogger(__name__)

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
        t.provider_metadata.update({'last_update': str(str(datetime.now().timestamp()))}) 

        if resp.get('ok'):
            logger.info('Template %s successfully submitted.', template_id)
            self.update_state(state='PROGRESS', meta={'current': 3, 'total': 3, 'status': 'Successfully submitted.'})
            t.errorMessage = None
            t.save()
            return {'status': 'SUCCESS', 'response': resp.get('response')}
        else:
            error_message = resp.get('response', 'Unknown submission error.')
            logger.error('Failed to submit template %s: %s', template_id, error_message)
            t.errorMessage = error_message
            t.save()
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
            t.errorMessage = None
            t.save()
            return {'status': 'SUCCESS', 'response': result.get('response')}
        else:
            error_message = result.get('response', 'Unknown update error.')
            logger.error("Failed to update template %s with provider: %s", t.id, error_message)
            t.errorMessage = error_message
            t.save()
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
            return {'status': 'SUCCESS', 'message': f'Template {t.id} deleted.'}
        else:
            logger.error("Failed to delete template %s from provider: %s", t.id, result.get('response'))
            error_message = result.get('response', 'Unknown provider error')
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
            self.update_state(state='FAILURE', meta={
                'status': error_msg,
                'exc_type': type(e).__name__,
                'exc_message': str(e)
            })
            raise ValueError(error_message)