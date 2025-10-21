from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import CatalogDataViewSet, CatalogMetadataViewSet, WhatsAppTemplateViewSet, OrganisationViewSet, ProviderAppInstanceViewSet, TaskStatusView, gupshup_webhook, templateTypes

router = DefaultRouter()
router.register('templates', WhatsAppTemplateViewSet)
router.register(r'organisations', OrganisationViewSet, basename='organisation')
router.register(r'provider', ProviderAppInstanceViewSet, basename='providerappinstance')

# custom template endpoints under app_id
template_list = WhatsAppTemplateViewSet.as_view({
    'get': 'list',
    'post': 'create'
})
template_detail = WhatsAppTemplateViewSet.as_view({
    'get': 'retrieve',
    'put': 'update',
    'patch': 'partial_update',
    'delete': 'destroy'
})
catalog_meta_details = CatalogMetadataViewSet.as_view({
    'get': 'retrieve',
    'post': 'create',
    'put': 'update',
    'delete': 'destroy',
})

catalog_dataset_details = CatalogDataViewSet.as_view({
    'get': 'retrieve',
    'post': 'batch',
    'put': 'batch',
    'delete': 'destroy',
})
provider_details = ProviderAppInstanceViewSet.as_view(
    {
        'put': 'update',
        'delete': 'destroy',
    }
)
template_send_for_approval = WhatsAppTemplateViewSet.as_view({
    'post': 'send_for_approval'
})

template_sync_from_provider = WhatsAppTemplateViewSet.as_view(
    {
        'post':'sync_from_provider'
    }
)

urlpatterns = [
    path('', include(router.urls)),
    # AppId-based template routes
    path('<str:app_id>/templates/', template_list, name='template-list'),
    path('<str:app_id>/templates/<int:pk>/', template_detail, name='template-detail'),
    path('<str:app_id>/templates/<int:pk>/send_for_approval',template_send_for_approval, name='template-send-for-approval'),
    path('<str:app_id>/templates/sync_provider',template_sync_from_provider, name='template-sync-from-provider'),

    path('<str:app_id>/provider/', provider_details, name='provider-detail'),

    path('<str:app_id>/catalog/metadata/', catalog_meta_details, name='catalog-metadata'),
    path('<str:app_id>/catalog/data/', catalog_dataset_details, name='catalog-data'),
    
    path('tasks/<uuid:task_id>/status/', TaskStatusView.as_view(), name='task-status'),

    path('webhooks/gupshup/', gupshup_webhook, name='gupshup_webhook'),
    path('template-types/', templateTypes, name='templateTypes'),
]
