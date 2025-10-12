import json
import requests

from wa_templates.utils.media_validator import is_gupshup_handle_id, is_valid_media_url
from .base import BaseProvider
from django.conf import settings
import time
import logging
from requests_toolbelt.utils import dump


logger = logging.getLogger(__name__)

class GupshupProvider(BaseProvider):
    BASE = 'https://partner.gupshup.io'

    def __init__(self, app_token=None, app_id=None):
        self.app_token = app_token
        self.app_id = app_id

    def headers(self):
        logger.debug('Generating headers for GupshupProvider with app_id %s', self.app_id)
        return {
            'Authorization': f'{self.app_token}',
            "Accept": "application/json",
            'Content-Type': 'application/x-www-form-urlencoded'
        }
    
    def _make_request(self, method, endpoint, data=None, params=None, is_json=False):
        """
        Central function to execute an API request, log the cURL command, 
        and handle standard provider errors.
        """
        url = f"{self.BASE}{endpoint}"
                # Determine the correct data payload (form data or JSON)
        kwargs = {
            'headers': self.headers(), 
            'params': params,
        }
        if is_json:
            kwargs['json'] = data
            # Adjust headers for JSON if necessary (though requests handles this usually)
            kwargs['headers']['Content-Type'] = 'application/json'
        elif data:
            kwargs['data'] = data # Form data for Gupshup

        # 1. Create a Request object (not prepared) for cURL dumping
        req = requests.Request(method, url, **kwargs)
        prepped = req.prepare()

        # 2. Log cURL command from the prepared request
        # NOTE: We use prepped object here, not the response, to get the cURL before send
        #cUrl_request = dump.dump_response(prepped).decode('utf-8')
        #logger.debug(f"cURL Request sent to Gupshup:\n{cUrl_request}")
        
        # 3. Send Request
        with requests.Session() as s:
            try:
                # Use stream=False for non-media uploads
                r = s.send(prepped,timeout=10, allow_redirects=True)
                try:
                    dump_data = dump.dump_all(r)
                    logger.debug("Outgoing HTTP:\n%s", dump_data.decode("utf-8"))
                except Exception as e:
                    logger.warning("Failed to dump request: %s", e)
                r.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)
            
            except requests.exceptions.HTTPError as e:
                logger.error("HTTP Error from Gupshup (%s %s): %s", method, endpoint, e)
                # Return standardized error structure
                return {'ok': False, 'status_code': r.status_code, 'response': r.text}
            
            except requests.exceptions.RequestException as e:
                logger.error("Network Error during Gupshup request (%s %s): %s", method, endpoint, e)
                return {'ok': False, 'status_code': 0, 'response': f'Network Error: {e}'}

        # 4. Process Successful Response
        response_data = {'ok': True, 'status_code': r.status_code}
        try:
            # Attempt to parse JSON only if content type indicates JSON
            if r.headers.get('content-type', '').startswith('application/json'):
                response_data['json'] = r.json()
            else:
                response_data['text'] = r.text
        except json.JSONDecodeError:
                response_data['text'] = r.text
        
        return response_data

    def upload_media(self, template):
        """
        Uploads media to Gupshup using template.media_url (public URL).
        Returns the handle ID string on success.
        """
        try:
            logger.debug('Uploading media for template %s from URL: %s', template.id, template.media_url)
            if not template.media_url:
                return None
            
            # We assume Gupshup allows uploading a public URL via x-www-form-urlencoded
            url = f"/partner/app/{self.app_id}/upload/media"
            
            # Gupshup docs show a form, so let's send form data instead of JSON
            data = {
                'file_type': template.file_type.upper(), # Required for form data upload
                'mediaUrl': template.media_url # Using mediaUrl based on your previous code structure
            }
            
            for attempt in range(3):
                logger.debug('Attempt %d to upload media', attempt + 1)
                # requests handles encoding data=dict as application/x-www-form-urlencoded
                #r = requests.post(url, headers=self.headers(), data=data, timeout=10)
                provider_resp_data = self._make_request(method='POST', endpoint=url, data=data)
                if provider_resp_data.get('ok'):
                    response_body = provider_resp_data.get('json', provider_resp_data.get('text'))
                    logger.debug('Media upload response body: %s', response_body)
                    if provider_resp_data.get('json', {}).get('status') == 'success':
                        handle_id = provider_resp_data['json'].get('handleId', {}).get('message')
                        if handle_id:
                            logger.debug('Media upload successful, handleId: %s', handle_id)
                            return handle_id
                        else:
                            logger.warning('Media upload successful but missing handleId: %s', response_body)
                            raise requests.exceptions.HTTPError("Media upload response missing handleId.")
                    else:
                        logger.warning('Media upload failed with response: %s', response_body)
                        time.sleep(1 + attempt)  # Exponential backoff
                else:
                    logger.warning('Media upload failed (status %d): %s', r.status_code, r.text)
                    time.sleep(1 + attempt)
            logger.error('Media upload failed after 3 attempts.')
            raise requests.exceptions.HTTPError('Media upload failed after retries.')
        except Exception as e:
            logger.error('Exception during media upload: %s', str(e))
            raise e

    def submit_template(self, template):
        try:
            # If there's media, upload first
            logger.debug('Submitting template %s for approval', template.id)
            if template.media_url:
                logger.debug('Template has media_url')
                isHandleId = is_gupshup_handle_id(template.media_url)

                if isHandleId:
                    logger.debug('media_url is already a Gupshup handle ID, skipping upload')
                    template.provider_metadata['media_id'] = template.media_url
                    template.save()
                else:
                    logger.debug('media_url is not a Gupshup handle ID, proceeding to upload')
                    isValidMedia = is_valid_media_url(template.media_url, template.file_type)
                    if not isValidMedia:
                        logger.error('Invalid media URL or file type, aborting template submission')
                        return {'ok': False, 'response': 'Invalid media URL or file type'}
                    
                    upload = self.upload_media(template)
                    handle_id = self.upload_media(template)
                    if handle_id:
                        logger.debug('Media uploaded successfully: %s', upload)
                        template.provider_metadata['media_id'] = handle_id
                        template.save()
                    else:
                        logger.error('Media upload failed, aborting template submission')
                        return {'ok': False, 'response': 'Media upload failed'}

            payload = {
                'elementName': template.elementName,
                'languageCode': template.languageCode,
                'content': template.content,
                'category': template.category,
                'templateType': template.template_type,
                'vertical': template.vertical,
                'footer': template.footer,
                'allowTemplateCategoryChange': str(template.allowTemplateCategoryChange).lower(),
                'example': template.example,
                'exampleHeader': template.exampleHeader,
                'header': template.header,
                'enableSample': str(template.enableSample).lower(),
            }

            if template.enableSample and 'media_id' in template.provider_metadata:
                payload['exampleMedia'] = template.provider_metadata['media_id']

            buttons = []
            if template.payload:
                if template.payload.get('buttons'):
                    payload_buttons = template.payload.get('buttons')
                    buttons = self.parse_buttons(payload_buttons)
            
            if buttons.__len__() > 0:
                payload['buttons'] = json.dumps(buttons)  # Gupshup expects double quotes in JSON strings
            
            if template.template_type.lower() == 'carousel' and template.payload.get('cards'):
                cards = []
                for card_data in template.payload.get('cards'):
                    card = {
                        'headerType': card_data.get('headerType'),
                        'body': card_data.get('body'),
                        'sampleText': card_data.get('sampleText'),
                    }
                    if card_data.get('mediaUrl'):
                        # Upload media for each card if mediaUrl is present
                        logger.debug('Uploading media for carousel card: %s', card_data.get('mediaUrl'))
                        isValidMedia = is_valid_media_url(card_data.get('mediaUrl'), card_data.get('headerType'))
                        if not isValidMedia:
                            logger.error('Invalid media URL or file type for carousel card, aborting template submission')
                            return {'ok': False, 'response': 'Invalid media URL or file type in carousel card'}

                        card_upload = self.upload_media(card_data.get('mediaUrl'))
                        if card_upload and card_upload.get('status') == 'success':
                            card['exampleMedia '] = card_upload.get('handleId').get('message')
                        else:
                            logger.error('Failed to upload media for carousel card: %s', card_data.get('mediaUrl'))
                            return {'ok': False, 'response': 'Failed to upload media for carousel card'}
                    
                    if card_data.get('buttons'):
                        card_buttons = self.parse_buttons(card_data.get('buttons'))
                        if buttons.__len__() > 0:
                            card['buttons'] = json.dumps(buttons)

                    cards.append(card)
                payload['cards'] = json.dumps(cards)  # Gupshup expects double quotes in JSON strings


            logger.debug('Prepared payload for template submission: %s', payload)

            # Handle more fields based on type
            #r = requests.post(url, headers=self.headers(), data=payload, timeout=10)
            url_path = f"/partner/app/{self.app_id}/templates/{template.template_type.lower()}"
            provider_resp_data = self._make_request( method='POST', endpoint=url_path, data=payload)
            if provider_resp_data.get('ok'):
                response_body = provider_resp_data.get('json', provider_resp_data.get('text'))
                # ... (your success logic using response_body) ...
                if provider_resp_data.get('json', {}).get('status') == 'success':
                    self.save_template_provider(provider_resp_data['json'], template)
                    return {'ok': True, 'response': template.json()}
                else:
                    error_text = response_body # Use the JSON response body here
                    logger.error('Template submission failed with response: %s', error_text)
                    template.errorMessage = error_text
                    template.save()
                    return {'ok': False, 'response': error_text}
            
            else:
                # Handle failure from _make_request (network or HTTP error)
                error_text = provider_resp_data.get('response')
                template.errorMessage = error_text
                template.save()
                return {'ok': False, 'response': error_text}
        except Exception as e:
            logger.error('Exception during template submission: %s', str(e))
            return {'ok': False, 'response': f'Internal error'}

    def save_template_data_from_provider(self, r, template):
        logger.debug('Saving provider response data to template %s', r.json())
        t_data = r.json().get('template', {}).json()
        template.provider_template_id = t_data.get('id')
        template.status = t_data.get('status', 'pending')
        template.containerMeta = t_data.get('containerMeta', {})
        template.createdOn = t_data.get('createdOn')
        template.modifiedOn = t_data.get('modifiedOn')
        template.data = t_data.get('data')
        template.elementName = t_data.get('elementName')
        template.languagePolicy = t_data.get('languagePolicy')
        template.meta = t_data.get('meta')
        template.namespace = t_data.get('namespace')
        template.priority = t_data.get('priority', 0)
        template.quality = t_data.get('quality')
        template.retry = t_data.get('retry', 0)
        template.stage = t_data.get('stage')
        template.wabaId = t_data.get('wabaId')
        template.save()
    
    def parse_buttons(self, buttons_data):
        buttons = []
        for payload_button in buttons_data:
            button = {}
            if payload_button.get('type') == 'QUICK_REPLY':
                button['type'] = 'QUICK_REPLY'
                button['text'] = payload_button.get('text')
            elif payload_button.get('type') == 'URL':
                button['type'] = 'URL'
                button['text'] = payload_button.get('text')
                button['url'] = payload_button.get('url')
                button['buttonValue'] = payload_button.get('buttonValue')
                button['suffix'] = payload_button.get('suffix')
            buttons.append(button)
        return buttons

    
    def get_templates(self):
        try:
            logger.debug('Fetching templates')
            url = f"/partner/app/{self.app_id}/templates"
            #r = requests.get(url, headers=self.headers(), timeout=10)
            provider_resp_data = self._make_request(method='GET', endpoint=url)
            if provider_resp_data.get('ok'):
                response_body = provider_resp_data.get('json', provider_resp_data.get('text'))
                logger.debug('Get template response body: %s', response_body)
                return {'ok': True, 'response': response_body.get('templates', [])}
            else:
                logger.error('Failed to fetch templates: %s', provider_resp_data.get('response'))
                return {'ok': False, 'response': provider_resp_data.get('response')}
        except Exception as e:
            logger.error('Exception during fetching templates: %s', str(e))
            return {'ok': False, 'response': "Internal error"}
    
    def delete_template(self, template):
        try: 
            url_path = f"/partner/app/{self.app_id}/templates/{template.elementName}"
            provider_resp_data = self._make_request(
                method='DELETE',
                endpoint=url_path
            )
            if provider_resp_data.get('ok'):
                logger.debug('Template deletion response status: %d', provider_resp_data['status_code'])
                # Status 200 or 204 are successful deletions
                if provider_resp_data['status_code'] in (200, 204):
                    return {'ok': True}
                else:
                    return {'ok': False, 'response': provider_resp_data.get('text', 'Deletion failed with unexpected status.')}

            return {'ok': False, 'response': provider_resp_data.get('response')}
        except Exception as e:
            logger.error('Exception during template deletion: %s', str(e))
            return {'ok': False, 'response': "Internal error"}
    
    def update_template(self, template):
        try:
            logger.debug('Updating template %s', template.id)
            url_path = f"/partner/app/{self.app_id}/templates/{template.id}"
            provider_resp_data = self._make_request(
                method='PUT',
                endpoint=url_path
            )
            if provider_resp_data.get('ok'):
                response_body = provider_resp_data.get('json', provider_resp_data.get('text'))
                # ... (your success logic using response_body) ...
                if provider_resp_data.get('json', {}).get('status') == 'success':
                    self.save_template_provider(provider_resp_data['json'], template)
                    template.status = 'pending'
                    template.save()
                    return {'ok': True, 'response': template.json()}
                else:
                    error_text = response_body # Use the JSON response body here
                    logger.error('Template submission failed with response: %s', error_text)
                    template.errorMessage = error_text
                    template.save()
                    return {'ok': False, 'response': error_text}
            
            else:
                # Handle failure from _make_request (network or HTTP error)
                error_text = provider_resp_data.get('response')
                template.errorMessage = error_text
                template.save()
                return {'ok': False, 'response': error_text}
        except Exception as e:
            logger.error('Exception during template update: %s', str(e))
            return {'ok': False, 'response': "Internal error"}
    