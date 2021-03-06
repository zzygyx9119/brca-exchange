from django.conf.urls import url

from . import views

urlpatterns = [

    url(r'^$', views.index, name="index"),
    url(r'^suggestions/$', views.autocomplete),
    url(r'^ga4gh/variants/search$', views.search_variants, name='search_variants'),
    url(r'^ga4gh/variants/(?P<variant_id>.+)$', views.get_variant, name = 'get_variant'),
    url(r'^ga4gh/variantsets/search', views.search_variant_sets, name='search_variant_sets'),
    url(r'^ga4gh/variantsets/(?P<variant_set_id>.+)$', views.get_variant_set, name='get_variant_set'),
    url(r'^ga4gh/datasets/search', views.search_datasets, name='search_datasets'),
    url(r'^ga4gh/datasets/(?P<dataset_id>.+)$', views.get_dataset, name="get_dataset" ),
    url(r'^ga4gh/variantsets', views.empty_variantset_id_catcher, name='empty_variantset_id_catcher'),
    url(r'^ga4gh/variants', views.empty_variant_id_catcher, name='empty_variant_id_catcher'),
    url(r'^ga4gh/datasets', views.empty_dataset_catcher, name='empty_dataset_catcher')

]