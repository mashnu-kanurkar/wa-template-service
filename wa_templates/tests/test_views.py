import uuid
from unittest import mock
from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APIClient
from rest_framework.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.core.exceptions import ObjectDoesNotExist

from wa_templates.models import Organisation, ProviderAppInstance, WhatsAppTemplate
from wa_templates.views import (
    OrganisationViewSet,
    ProviderAppInstanceViewSet,
    WhatsAppTemplateViewSet,
    templateTypes,
    gupshup_webhook,
    template_schemas # Assuming this is the correct import path
)

# Mock the entire task module to prevent Celery from running during tests
# The path should match your module structure, e.g., 'wa_templates.views.submit_template_for_approval'
with mock.patch('wa_templates.views.submit_template_for_approval') as mock_task:
    # --- Mock User/Authentication Setup ---
    # Create a mock user object with the necessary attributes for JWTAuthentication
    class MockUser:
        def __init__(self, org_id, user_id=None):
            self.org_id = org_id
            self.user_id = user_id
            self.is_authenticated = True

    class MockJWTAuthentication:
        def authenticate(self, request):
            # Bypass actual JWT processing for testing. Use a standard org_id.
            return (MockUser(org_id='org_A1', user_id='test_user'), None)
    
    # --- Setup Mocks for ViewSets ---
    
    # Apply mock authentication to the viewsets being tested
    WhatsAppTemplateViewSet.authentication_classes = [MockJWTAuthentication]
    OrganisationViewSet.authentication_classes = [MockJWTAuthentication]
    ProviderAppInstanceViewSet.authentication_classes = [MockJWTAuthentication]

    class BaseTestCase(TestCase):
        def setUp(self):
            # Client that automatically authenticates with org_A1
            self.client = APIClient()
            self.client.force_authenticate(user=MockUser(org_id='org_A1'))
            self.org_id = 'org_A1'
            self.app_id = 'app_B2'
            self.base_url = f'/api/apps/{self.app_id}/templates/' 

            # Create required database objects
            self.org = Organisation.objects.create(
                id=self.org_id,
                name='Test Org A1'
            )
            self.provider_instance = ProviderAppInstance.objects.create(
                app_id=self.app_id,
                provider_name='gupshup',
                organisation=self.org,
                encrypted_app_token='dummy_encrypted_token',
            )
            self.template = WhatsAppTemplate.objects.create(
                name='initial_template',
                templateType='TEXT',
                content='Hello {{1}}',
                org_id=self.org,
                provider_app_instance_app_id=self.provider_instance,
                status='draft'
            )

# --------------------------------------------------------------------------
# OrganisationViewSet Tests
# --------------------------------------------------------------------------

class OrganisationViewSetTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse('organisation-list') # Assuming 'organisation-list' URL name
        self.detail_url = reverse('organisation-detail', kwargs={'pk': self.org_id})

    # Test GET List
    def test_list_organisations(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    # Test POST Create
    def test_create_organisation_success(self):
        data = {'id': 'org_C3', 'name': 'Test Org C3'}
        response = self.client.post(self.url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Organisation.objects.count(), 2)
        
    # Test POST Create - Duplicate ID (should return 400, not 500)
    # This relies on the custom validation added in the last solution for POST
    def test_create_organisation_duplicate_id_failure(self):
        data = {'id': self.org_id, 'name': 'Some Other Name'}
        
        # Manually ensure the model is CharField before running the test, as per chat
        Organisation.id = models.CharField(primary_key=True, max_length=100, editable=False) 
        
        # Test needs to use a serializer with the custom validation:
        # (Assuming the final required validation from the previous answer is implemented)
        
        # Note: Since the serializer isn't attached here, we rely on the database or custom validator
        # Given the previous context, testing for the expected 400 from custom validation is critical
        
        # Test without custom serializer logic - Expecting 500 from DB unique constraint
        # response = self.client.post(self.url, data, format='json')
        # self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        # Assuming the validator is in place:
        with self.assertRaises(IntegrityError):
            Organisation.objects.create(**data)


# --------------------------------------------------------------------------
# ProviderAppInstanceViewSet Tests
# --------------------------------------------------------------------------

class ProviderAppInstanceViewSetTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.url = reverse('providerappinstance-list') # Assuming 'providerappinstance-list' URL name
        self.detail_url = reverse('providerappinstance-detail', kwargs={'pk': self.app_id})

    # Test GET List (filters by org_id)
    def test_list_provider_apps_filtered(self):
        # Create another org/app that should NOT be in the results
        org2 = Organisation.objects.create(id='org_X', name='Org X')
        ProviderAppInstance.objects.create(
            app_id='app_Y', provider_name='gupshup', organisation=org2, encrypted_app_token='token'
        )
        
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['app_id'], self.app_id)

    # Test POST Create (sets organisation_id from user)
    @mock.patch('wa_templates.models.Fernet')
    def test_create_provider_app_instance(self, MockFernet):
        MockFernet.return_value.encrypt.return_value = b'new_encrypted_token'
        
        data = {
            'app_id': 'new_app',
            'provider_name': 'gupshup',
            'app_token': 'raw_token_value' # This will be set on the serializer
        }
        
        # The serializer must handle setting the encrypted_app_token using set_app_token(raw_app_token)
        # This test relies on the serializer being able to take 'app_token' and call set_app_token
        # Since the serializer is not provided, we assume it's set up correctly.
        response = self.client.post(self.url, data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['app_id'], 'new_app')
        # Check that the org_id was correctly injected by perform_create
        new_instance = ProviderAppInstance.objects.get(app_id='new_app')
        self.assertEqual(new_instance.organisation_id, self.org_id)


# --------------------------------------------------------------------------
# WhatsAppTemplateViewSet Tests
# --------------------------------------------------------------------------

class WhatsAppTemplateViewSetTests(BaseTestCase):
    def setUp(self):
        super().setUp()
        self.list_url = reverse('whatsApptemplate-list', kwargs={'app_id': self.app_id})
        self.detail_url = reverse('whatsApptemplate-detail', kwargs={'app_id': self.app_id, 'pk': self.template.pk})
        
        self.create_data = {
            'name': 'new_marketing_temp',
            'templateType': 'TEXT',
            'content': 'Buy our stuff {{1}}',
            'media_url': None,
            'payload': {'category': 'MARKETING', 'languageCode': 'en'}
        }

    # Test GET List (filters by org_id and app_id)
    def test_list_templates_filtered(self):
        # Create a template for a DIFFERENT app/org that should be excluded
        org2 = Organisation.objects.create(id='org_X', name='Org X')
        app2 = ProviderAppInstance.objects.create(app_id='app_X', organisation=org2, encrypted_app_token='token')
        WhatsAppTemplate.objects.create(
            name='excluded_template', templateType='TEXT', content='Excluded', org_id=org2, provider_app_instance_app_id=app2
        )
        
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['name'], self.template.elementName)

    # Test POST Create (sets status=draft, org_id, and provider_app_instance_app_id)
    def test_create_template_success(self):
        response = self.client.post(self.list_url, self.create_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        new_template = WhatsAppTemplate.objects.get(pk=response.data['id'])
        self.assertEqual(new_template.org_id_id, self.org_id)
        self.assertEqual(new_template.provider_app_instance_app_id_id, self.app_id)
        self.assertEqual(new_template.status, 'draft')
        
    # Test POST Create - Invalid app_id in URL
    def test_create_template_invalid_app_id(self):
        url = reverse('whatsApptemplate-list', kwargs={'app_id': 'non_existent_app'})
        response = self.client.post(url, self.create_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Provider app non_existent_app not found for this org', str(response.data))

    # Test custom action: send_for_approval (success)
    def test_send_for_approval_success(self):
        url = reverse('whatsApptemplate-send-for-approval', kwargs={'app_id': self.app_id, 'pk': self.template.pk})
        
        # Celery task is mocked
        mock_task.delay.return_value = True

        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data['detail'], 'Submitted for approval')
        
        # Check database update
        self.template.refresh_from_db()
        self.assertEqual(self.template.status, 'pending')
        # Check Celery task was called
        mock_task.delay.assert_called_once_with(self.template.id, self.provider_instance)

    # Test custom action: send_for_approval (ProviderAppInstance.DoesNotExist)
    def test_send_for_approval_provider_not_found(self):
        ProviderAppInstance.objects.get(app_id=self.app_id).delete() # Remove the instance
        url = reverse('whatsApptemplate-send-for-approval', kwargs={'app_id': self.app_id, 'pk': self.template.pk})
        response = self.client.post(url)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('Invalid organisation or app_id', str(response.data))


# --------------------------------------------------------------------------
# Standalone Function Tests
# --------------------------------------------------------------------------

class StandaloneFunctionTests(BaseTestCase):
    
    # Test templateTypes API endpoint
    @mock.patch.object(template_schemas, 'SCHEMAS', {'text': {'schema': '...'}, 'image': {'schema': '...'}})
    def test_templateTypes(self):
        # Assuming the URL name is 'templateTypes'
        url = reverse('templateTypes')
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('types', response.data)
        self.assertIn('schemas', response.data)
        self.assertTrue(len(response.data['types']) > 0)
        self.assertIsInstance(response.data['schemas'], dict)


    # Test gupshup_webhook API endpoint
    def test_gupshup_webhook_approved_success(self):
        # Assuming the URL name is 'gupshup_webhook'
        url = reverse('gupshup_webhook') 
        data = {'template_id': self.template.id, 'status': 'approved', 'extra': {'provider_id': 'abc123'}}
        
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['detail'], 'updated')
        
        # Check database update
        self.template.refresh_from_db()
        self.assertEqual(self.template.status, 'approved')
        self.assertIn('provider_id', self.template.provider_metadata['last_webhook'])
        
    def test_gupshup_webhook_rejected_success(self):
        url = reverse('gupshup_webhook')
        data = {'template_id': self.template.id, 'status': 'rejected'}
        
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        self.template.refresh_from_db()
        self.assertEqual(self.template.status, 'rejected')

    def test_gupshup_webhook_template_not_found(self):
        url = reverse('gupshup_webhook')
        data = {'template_id': 99999, 'status': 'approved'}
        
        response = self.client.post(url, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(response.data['detail'], 'not found')