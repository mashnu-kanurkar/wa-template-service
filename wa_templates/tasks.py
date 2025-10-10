from celery import shared_task
from .models import WhatsAppTemplate
from .providers.factory import get_provider
import logging

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def submit_template_for_approval(self, template_id):
    try:
        t = WhatsAppTemplate.objects.get(id=template_id)
    except WhatsAppTemplate.DoesNotExist:
        logger.error('Template not found: %s', template_id)
        return

    provider = get_provider('gupshup')
    resp = provider.submit_template(t)
    t.provider_metadata.update({'last_submit': resp})
    t.save()
    return resp
