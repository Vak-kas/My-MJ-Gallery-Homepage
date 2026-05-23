from django.urls import path
from . import views

app_name = 'studio'

urlpatterns = [
    path('', views.index, name='index'),
    path('profile/', views.profile, name='profile'),
    path('profile/basic/', views.profile_basic, name='profile_basic'),

    path('profile/contact/', views.profile_contact, name='profile_contact'),
    path('profile/contact/<int:contact_id>/update/', views.profile_contact_update, name='profile_contact_update'),
    path('profile/contact/<int:contact_id>/visibility/', views.profile_contact_toggle_visibility, name='profile_contact_toggle_visibility'),
    path('profile/contact/<int:contact_id>/delete/', views.profile_contact_delete, name='profile_contact_delete'),

    path('profile/links/', views.profile_links, name='profile_links'),
    path('profile/links/<int:link_id>/update/', views.profile_link_update, name='profile_link_update'),
    path('profile/links/<int:link_id>/delete/', views.profile_link_delete, name='profile_link_delete'),
    path('profile/links/<int:link_id>/toggle-visibility/', views.profile_link_toggle_visibility, name='profile_link_toggle_visibility'),
    path('profile/links/<int:link_id>/toggle-primary/', views.profile_link_toggle_primary, name='profile_link_toggle_primary'),
    
    path('profile/resume/', views.profile_resume, name='profile_resume'),
]