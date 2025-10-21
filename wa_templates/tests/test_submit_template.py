import json
from unittest import mock
from unittest.mock import MagicMock, patch
from io import BytesIO

from wa_templates.providers.gupshup import GupshupProvider

# --- Mock Data from Logs ---
# 1. Mock data for successful media upload response
MEDIA_UPLOAD_SUCCESS_RESPONSE = {
    "handleId": {
        "message": "4::aW1hZ2UvcG5n:ARZ_tgiXFwqdFjHhJKATN26vGk_95muJmgykl8Ri1KhKEbuIBrUbFtNUGrZ5HO5cSXKphlxteCm8Wu2baXCCKEdycRLy4dXvyP8G9eRryag_dA:e:1760802361:340384197887925:61580519339768:ARZ4CdfFm5XotDp513Q"
    },
    "status": "success"
}

# 2. Mock data for successful template submission response (from the API body)
TEMPLATE_SUBMISSION_SUCCESS_RESPONSE = {
    "status": "success",
    "template": {
        "appId": "0f6c672a-6c89-4a3f-b17b-90c11455041b",
        "buttonSupported": "QR,URL",
        "category": "MARKETING",
        "containerMeta": '{"appId":"0f6c672a-6c89-4a3f-b17b-90c11455041b","data":"Hi {{1}}.", ...}', # Truncated for brevity
        "createdOn": 1760456761813,
        "data": "Hi {{1}}.\nThis is the footer | [please check] | [test,https://www.google.co.uk/]",
        "elementName": "sgjadlnb_b225d",
        "id": "2467d5f7-da6c-4017-a3d6-9eeb71a3a5c1",
        "languageCode": "en",
        "languagePolicy": "deterministic",
        "meta": '{"example":"Hi There."}',
        "modifiedOn": 1760456761813,
        "namespace": "a2b66527_e442_444a_8f94_7bcc7277d90a",
        "priority": 1,
        "quality": "UNKNOWN",
        "retry": 0,
        "stage": "NONE",
        "status": "PENDING",
        "templateType": "IMAGE",
        "vertical": "Ticket update",
        "wabaId": "1557831122064378"
    }
}

# 3. Mock Template Object Data
class MockWhatsAppTemplate:
    """A mock Django model object replicating the attributes used in the logs."""
    def __init__(self, media_url, template_id=12):
        self.id = template_id
        self.elementName = 'sgjadlnb_b225d'
        self.languageCode = 'en'
        self.content = 'Hi {{1}}.'
        self.category = 'MARKETING'
        self.templateType = 'IMAGE'
        self.vertical = 'Ticket update'
        self.example = 'Hi There.'
        self.media_url = media_url
        self.enableSample = True
        self.exampleHeader = None
        self.allowTemplateCategoryChange = True
        self.footer = 'This is the footer'
        self.header = None
        self.payload = {
            'buttons': [
                {'type': 'QUICK_REPLY', 'text': 'please check'},
                {'type': 'URL', 'text': 'test', 'url': 'https://www.google.co.uk/', 'buttonValue': 'https://www.google.co.uk/', 'suffix': ''}
            ]
        }
        self.exampleMedia = None
        self.provider_metadata = {}
        self.provider_template_id = None
        self.status = 'DRAFT' # Initial status

    def save(self):
        """Mock save method to track state changes."""
        pass # In a real test, you might assert this was called

    def update_error_meta(self, action, message):
        """Mock update error meta for tracking errors."""
        pass

    def json(self):
        """Mock json representation of the object."""
        return {'id': self.id, 'status': self.status, 'elementName': self.elementName}


@patch('requests.get') # Patch step 1: Download media
@patch('requests.post') # Patch step 2: Upload media
@patch.object(GupshupProvider, 'save_template_data_from_provider', MagicMock())
def test_submit_template_success_flow(mock_post, mock_get, caplog):
    """
    Tests the GupshupProvider.submit_template function, mocking the external
    API calls for media download, media upload, and template submission.
    """
    # --- Setup Mocks ---

    # 1. Mock requests.get (for downloading the media)
    mock_download_response = MagicMock()
    mock_download_response.status_code = 200
    mock_download_response.content = b'image_bytes' # Mock the image content
    mock_download_response.raise_for_status.return_value = None
    mock_get.return_value = mock_download_response

    # 2. Mock requests.post (for uploading the media)
    mock_upload_response = MagicMock()
    mock_upload_response.status_code = 200
    mock_upload_response.json.return_value = MEDIA_UPLOAD_SUCCESS_RESPONSE
    mock_upload_response.text = json.dumps(MEDIA_UPLOAD_SUCCESS_RESPONSE) # For logging
    mock_post.return_value = mock_upload_response

    # 3. Instantiate the provider with mock parameters
    provider = GupshupProvider(
        app_token='##',
        app_id='##',
        org_id='mock_org_id'
    )
    
    # 4. Mock the internal _make_request (for template submission)
    # Patch this function *after* provider instantiation, or patch it at the module level.
    # It's cleaner to mock the return value structure here.
    @patch.object(GupshupProvider, '_make_request')
    def run_test(mock_make_request):
        # Mock successful template submission response from _make_request
        mock_make_request.return_value = {
            'ok': True, 
            'status_code': 200, 
            'json': TEMPLATE_SUBMISSION_SUCCESS_RESPONSE
        }
        
        # 5. Create the Mock Template object
        template_obj = MockWhatsAppTemplate(media_url='https://www.gstatic.com/webp/gallery3/1.png')

        # --- Execution ---
        result = provider.submit_template(template_obj)

        # --- Assertions ---
        
        # 1. Assert initial requests (media download/upload) were made
        mock_get.assert_called_once_with(
            'https://www.gstatic.com/webp/gallery3/1.png', 
            stream=False, 
            timeout=10
        )
        
        # 2. Assert media upload was called (using requests.post)
        # Note: Checking file content mock is tricky due to BytesIO, 
        # but we can check the URL and headers.
        assert mock_post.called
        
        # 3. Assert the template object was updated with the handle ID
        expected_handle_id = MEDIA_UPLOAD_SUCCESS_RESPONSE['handleId']['message']
        assert template_obj.exampleMedia == expected_handle_id
        assert template_obj.media_url == expected_handle_id
        
        # 4. Assert the final template submission API call was made
        mock_make_request.assert_called_once()
        
        # 5. Assert the result indicates success
        assert result['ok'] is True
        assert template_obj.status == 'PENDING' # Check if save_template_data_from_provider updated status

    run_test()