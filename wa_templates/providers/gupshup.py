from datetime import datetime
import hashlib
import json
from urllib.parse import urlencode
import requests

from wa_templates.models import WhatsAppTemplate
from wa_templates.utils.media_validator import is_gupshup_handle_id, is_valid_media_url
from .base import BaseProvider
from django.conf import settings
import time
import logging
from requests_toolbelt.utils import dump
from io import BytesIO
from urllib.parse import urlparse


logger = logging.getLogger(__name__)

class GupshupProvider(BaseProvider):
    BASE = 'https://partner.gupshup.io'

    def __init__(self, app_token=None, app_id=None, org_id=None):
        self.app_token = app_token
        self.app_id = app_id
        self.org_id = org_id

    def headers(self):
        logger.debug('Generating headers for GupshupProvider with app_id %s', self.app_id)
        return {
            'Authorization': f'{self.app_token}',
            "Accept": "application/json",
        }
    
    def _make_request(self, method, endpoint, data=None, params=None, is_json=False, content_type=None):
        """
        Central function to execute an API request, log the cURL command, 
        and handle standard provider errors.
        """
        url = f"{self.BASE}{endpoint}"
                # Determine the correct data payload (form data or JSON)
        kwargs = {
            'headers': self.headers(), 
        }
        if params:
            kwargs['params'] = params
        
        logger.debug(f'headers and params are ready')
        if is_json:
            kwargs['json'] = data
            # Adjust headers for JSON if necessary (though requests handles this usually)
            if content_type is None:
                kwargs['headers']['Content-Type'] = 'application/json'
        elif data:
            if data:
                for key, value in data.items():
                    if isinstance(value, (dict, list)):
                        logger.debug(f'Converting {key} to JSON string')
                        data[key] = json.dumps(value)
                    elif not isinstance(value, str):
                        logger.debug(f'Converting {key} to string')
                        data[key] = str(value)

                logger.debug(f'Final payload before POST: {data}')
                logger.debug('Converting payload to form data')
                kwargs['data'] = data
                if content_type is None:
                    kwargs['headers']['Content-Type'] = 'application/x-www-form-urlencoded'
        
        if content_type is not None:
            kwargs['headers']['Content-Type'] = content_type
        # 1. Create a Request object (not prepared) for cURL dumping
        req = requests.Request(method, url, **kwargs)
        prepped = req.prepare()
        
        # 2. Send Request
        with requests.Session() as s:
            try:
                # Use stream=False for non-media uploads
                if data:
                    logger.info("Encoded form data:\n%s", urlencode(data))

                r = s.send(prepped,timeout=10, allow_redirects=True)
                logger.debug(f'response from gupshup {r}')
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

        # 3. Process Successful Response
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

    def upload_media(self, media_url, file_type):
        """
        Uploads media to Gupshup using the actual binary file (downloaded from media_url).
        Returns the handle ID string on success.
        """
        try:
            logger.debug('Uploading media from URL: %s', media_url)
            if not media_url:
                return None

            # Step 1: Download file content
            download_resp = requests.get(media_url, stream=False, timeout=10)
            logger.debug(f'download response {download_resp.status_code}')
            if download_resp.status_code != 200:
                raise requests.exceptions.RequestException(
                    f"Failed to download media from {media_url}, status={download_resp.status_code}"
                )
            download_resp.raise_for_status()

            filename = urlparse(media_url).path.split("/")[-1] or "media_file"
            
            file_bytes = BytesIO(download_resp.content)
            logger.debug("File bytes successfully downloaded")

            # Step 2: Prepare upload details
            upload_url = f"{self.BASE}/partner/app/{self.app_id}/upload/media"

            files = {
                "file": (filename, file_bytes, file_type.lower())
            }
            data = {
                "file_type": file_type.lower()
            }

            # Step 3: Retry upload up to 3 times
            for attempt in range(3):
                logger.debug("Attempt %d to upload media", attempt + 1)
                h = self.headers()
                if 'content-type' in h:
                    del h['content-type']
                
                try:
                    response = requests.post(
                        upload_url,
                        headers=h,
                        files=files,
                        data=data,
                        timeout=20,
                    )
                    logger.debug("Media upload response: %s", response.text)

                    if response.status_code == 200:
                        resp_json = response.json()
                        if resp_json.get("status") == "success":
                            handle_id_obj = resp_json.get("handleId")

                            if isinstance(handle_id_obj, dict):
                                handle_id = handle_id_obj.get("message")
                            # Or if handleId is a direct string field (more common)
                            else:
                                handle_id = resp_json.get("handleId")

                            
                            if handle_id:
                                logger.info("Media uploaded successfully, handleId: %s", handle_id)
                                return handle_id  
                            else:
                                logger.warning("Upload success but missing handleId field: %s", resp_json)
                                # Log the full response text for debugging the handleId structure
                                logger.error("Gupshup response text: %s", response.text) 
                                raise requests.exceptions.HTTPError("Missing handleId in Gupshup response")
  
                            # handle_id = resp_json.get("handleId", {}).get("message")
                            # if handle_id:
                            #     logger.info("Media uploaded successfully, handleId: %s", handle_id)
                            #     return handle_id
                            # else:
                            #     logger.warning("Upload success but missing handleId field: %s", resp_json)
                            #     raise requests.exceptions.HTTPError("Missing handleId in Gupshup response")
                        else:
                            logger.warning("Upload failed with status=%s, message=%s", resp_json.get("status"), resp_json.get("message"))
                            logger.error("Gupshup error response: %s", response.text)
                    else:
                        logger.warning("Upload failed with HTTP %s: %s", response.status_code, response.text)
                        response.raise_for_status() # For non-200 responses, raise to trigger retry/exit

                except Exception as e:
                    logger.error("Error on upload attempt %d: %s", attempt + 1, str(e))

                # Retry after exponential backoff
                time.sleep(1 + attempt)

            logger.error("Media upload failed after 3 attempts.")
            raise requests.exceptions.HTTPError("Media upload failed after retries.")

        except requests.exceptions.RequestException as e:
            logger.error("Request/Network Exception during media upload: %s", str(e))
            raise e
        except Exception as e:
            logger.error("General Exception during media upload: %s", str(e))
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
                    
                    handle_id = self.upload_media(template.media_url, template.file_type)
                    if handle_id:
                        logger.debug('Media uploaded successfully: %s', handle_id)
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
                'templateType': template.templateType,
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
            
            if buttons:
                payload['buttons'] = json.dumps(buttons)  # Gupshup expects double quotes in JSON strings

            
            if template.templateType.lower() == 'carousel' and template.payload.get('cards'):
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

                        card_upload = self.upload_media(card_data.get('mediaUrl'), card_data.get('headerType'))
                        if card_upload:
                            card['exampleMedia'] = card_upload.get('handleId').get('message')
                        else:
                            logger.error('Failed to upload media for carousel card: %s', card_data.get('mediaUrl'))
                            return {'ok': False, 'response': 'Failed to upload media for carousel card'}
                    
                    if card_data.get('buttons'):
                        card_buttons = self.parse_buttons(card_data.get('buttons'))
                        if card_buttons:
                            card['buttons'] = json.dumps(card_buttons)

                    cards.append(card)
                payload['cards'] = json.dumps(cards)  # Gupshup expects double quotes in JSON strings


            logger.debug('Prepared payload for template submission: %s', payload)

            # Handle more fields based on type
            #r = requests.post(url, headers=self.headers(), data=payload, timeout=10)
            url_path = f"/partner/app/{self.app_id}/templates"
            provider_resp_data = self._make_request( method='POST', endpoint=url_path, data=payload)
            if provider_resp_data.get('ok'):
                response_body = provider_resp_data.get('json', provider_resp_data.get('text'))
                # ... (your success logic using response_body) ...
                if provider_resp_data.get('json', {}).get('status') == 'success':
                    self.save_template_data_from_provider(provider_resp_data['json'], template)
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
        t_data = r.get('template', {})

        if t_data.get('containerMeta'):
            template.containerMeta = t_data.get('containerMeta')
            self.parse_container_meta(t_data, template)

        if t_data.get('buttonSupported'):
            template.buttonSupported = t_data.get('buttonSupported')
        if t_data.get('id'):
            template.provider_template_id = t_data.get('id')

        if t_data.get('internalCategory'):
            template.internalCategory = t_data.get('internalCategory')
        if t_data.get('internalType'):
            template.internalType = t_data.get('internalType')

        if t_data.get('externalId'):
            template.externalId = t_data.get('externalId')

        if t_data.get('oldCategory'):
            template.oldCategory = t_data.get('oldCategory')

        if t_data.get('status'):    
            template.status = t_data.get('status')

        if t_data.get('createdOn'):
            template.createdOn = t_data.get('createdOn')

        if t_data.get('modifiedOn'):
            template.modifiedOn = t_data.get('modifiedOn')

        if t_data.get('data'):
            template.data = t_data.get('data')
        if t_data.get('elementName'):
            template.elementName = t_data.get('elementName')
        if t_data.get('languagePolicy'):
            template.languagePolicy = t_data.get('languagePolicy')
        if t_data.get('meta'):
            template.meta = t_data.get('meta')
        if t_data.get('namespace'):
            template.namespace = t_data.get('namespace')
        if t_data.get('priority'):
            template.priority = t_data.get('priority')
        if t_data.get('quality'):
            template.quality = t_data.get('quality')
        if t_data.get('retry'):
            template.retry = t_data.get('retry')
        if t_data.get('stage'):
            template.stage = t_data.get('stage')
        if t_data.get('wabaId'):
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
            elif payload_button.get('type') == "PHONE_NUMBER":
                button['type'] = 'PHONE_NUMBER'
                button['text'] = payload_button.get('text')
                button['phone_number'] = payload_button.get('phone_number')
            buttons.append(button)
        return buttons

    
    def get_templates(self):
        # try:
        logger.debug('Fetching templates')
        url = f"/partner/app/{self.app_id}/templates"
        #r = requests.get(url, headers=self.headers(), timeout=10)
        provider_resp_data = self._make_request(method='GET', endpoint=url)
        logger.debug(f'provider response: {provider_resp_data}')
        if provider_resp_data.get('ok'):
            response_body = provider_resp_data.get('json')
            
            # If 'json' key is missing, check if 'text' is present and try to parse it
            if response_body is None and provider_resp_data.get('text'):
                try:
                    response_body = json.loads(provider_resp_data['text'])
                except json.JSONDecodeError:
                    logger.error("Failed to decode text response as JSON: %s", provider_resp_data['text'])
                    return {'ok': False, 'response': 'Provider returned unparseable text response.'}

            # If after all attempts, response_body is still None or not a dict, handle it.
            if not isinstance(response_body, dict):
                logger.error("Get templates API did not return a dictionary object.")
                return {'ok': False, 'response': "Provider returned an invalid or empty JSON response."}
            
            
            logger.debug('Get template response body: %s', response_body)
            if response_body.get('status') == 'success':
                templates = response_body.get('templates', [])
                
                templates_to_update = []
                for tpl in templates:
                    element_name = tpl.get('elementName')
                    if not element_name:
                        continue
                    # Compute hash of template content for change detection
                    tpl_hash = hashlib.md5(json.dumps(tpl, sort_keys=True).encode('utf-8')).hexdigest()

                    template_obj = WhatsAppTemplate.objects.filter(elementName=element_name).first()
                    logger.debug(f'template_obj : {template_obj}')

                    t_update = self.sync_templates(tpl, tpl_hash, template_obj)
                    templates_to_update.append(t_update)

                return {'ok': True, 'response': templates_to_update}
            else:
                return {'ok': False, 'response': response_body}
        else:
            logger.error('Failed to fetch templates: %s', provider_resp_data.get('response'))
            return {'ok': False, 'response': provider_resp_data.get('response')}
        # except Exception as e:
        #     logger.error('Exception during fetching templates: %s', str(e))
        #     return {'ok': False, 'response': "Internal error"}
    
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
        
    def sync_templates(self, tpl,tpl_hash, template_obj = None):
        
        if template_obj is not None:
            logger.debug("template_obj present, updating")
            if template_obj.hash != tpl_hash:
                logger.debug("template_obj and gupshup template hash code mismatched, procedding with update")
                template_obj.hash = tpl_hash
                template_obj.provider_app_instance_app_id_id  = tpl.get('appId')
                template_obj.org_id_id = self.org_id
                template_obj.buttonSupported = tpl.get('buttonSupported')
                template_obj.category = tpl.get('category')
                template_obj.containerMeta = tpl.get('containerMeta')
                template_obj.createdOn = tpl.get('createdOn')
                template_obj.data = tpl.get('data')
                template_obj.elementName = tpl.get('elementName')
                template_obj.externalId = tpl.get('externalId')
                template_obj.provider_template_id = tpl.get('id')
                template_obj.internalCategory = tpl.get('internalCategory')
                template_obj.internalType = tpl.get('internalType')
                template_obj.languageCode = tpl.get('languageCode')
                template_obj.languagePolicy = tpl.get('languagePolicy')
                template_obj.meta = tpl.get('meta')
                template_obj.modifiedOn = tpl.get('modifiedOn')
                template_obj.namespace = tpl.get('namespace')
                template_obj.oldCategory = tpl.get('oldCategory')
                template_obj.priority = tpl.get('priority')
                template_obj.quality = tpl.get('quality')
                template_obj.retry = tpl.get('retry')
                template_obj.stage = tpl.get('stage')
                template_obj.status = tpl.get('status')
                template_obj.templateType = tpl.get('templateType')
                template_obj.wabaId = tpl.get('wabaId')

                template_obj.provider_metadata.update({'last_update': str(datetime.now().timestamp())})
                
                if tpl.get('containerMeta'):
                    self.parse_container_meta(tpl.get('containerMeta'), template_obj)
            return template_obj

        else:
            logger.debug("template_obj not present, creating new")
            new_template = WhatsAppTemplate(
                org_id_id = self.org_id, 
                hash = tpl_hash,
                provider_app_instance_app_id_id = tpl.get('appId'),
                buttonSupported = tpl.get('buttonSupported'),
                category = tpl.get('category'),
                containerMeta = tpl.get('containerMeta'),
                createdOn = tpl.get('createdOn'),
                data = tpl.get('data'),
                elementName = tpl.get('elementName'),
                externalId = tpl.get('externalId'),
                provider_template_id = tpl.get('id'),
                internalCategory = tpl.get('internalCategory'),
                internalType = tpl.get('internalType'),
                languageCode = tpl.get('languageCode'),
                languagePolicy = tpl.get('languagePolicy'),
                meta = tpl.get('meta'),
                modifiedOn = tpl.get('modifiedOn'),
                namespace = tpl.get('namespace'),
                oldCategory = tpl.get('oldCategory'),
                priority = tpl.get('priority'),
                quality = tpl.get('quality'),
                retry = tpl.get('retry'),
                stage = tpl.get('stage'),
                status = tpl.get('status'),
                templateType = tpl.get('templateType'),
                wabaId = tpl.get('wabaId'),
            )
            if tpl.get('containerMeta'):
                self.parse_container_meta(tpl.get('containerMeta'), new_template)
            return new_template
    
    def parse_container_meta(self, containerMeta, t_obj):
        # Check if containerMeta is already a dict (which causes the TypeError)
        if isinstance(containerMeta, dict):
            containerMeta_json = containerMeta
        # If it's a string (the expected format), parse it
        elif isinstance(containerMeta, (str, bytes, bytearray)):
            try:
                containerMeta_json = json.loads(containerMeta)
            except json.JSONDecodeError as e:
                # Handle the case where the string is not valid JSON
                print(f"Error decoding JSON for containerMeta: {e}")
                return t_obj # Return object without parsing meta
        else:
            # Handle unexpected types gracefully
            print(f"Unexpected type for containerMeta: {type(containerMeta)}")
            return t_obj
    
        if containerMeta_json.get('data'):
            t_obj.content = containerMeta_json.get('data')
        
        if containerMeta_json.get("buttons"):
            t_obj.payload = {'buttons': containerMeta_json.get("buttons")}
        
        if containerMeta_json.get("header"):
            t_obj.header = containerMeta_json.get("header")

        if containerMeta_json.get("footer"):
            t_obj.footer = containerMeta_json.get("footer")
        
        if containerMeta_json.get("sampleText"):
            t_obj.example = containerMeta_json.get("sampleText")

        if containerMeta_json.get("sampleHeader"):
            t_obj.exampleHeader = containerMeta_json.get("sampleHeader")

        if containerMeta_json.get("enableSample"):
            t_obj.enableSample = containerMeta_json.get("enableSample")
        
        if containerMeta_json.get("allowTemplateCategoryChange"):
            t_obj.allowTemplateCategoryChange = containerMeta_json.get("allowTemplateCategoryChange")
        
        if containerMeta_json.get("correctCategory"):
            t_obj.category = containerMeta_json.get("correctCategory")
        return t_obj
        