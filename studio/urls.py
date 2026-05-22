from django.urls import path
from . import views

app_name = 'studio'

urlpatterns = [
    path('', views.index, name='index'),
    path('profile/', views.profile, name='profile'),
    path('profile/basic/', views.profile_basic, name='profile_basic'),
    path('profile/contact/', views.profile_contact, name='profile_contact'),
    path('profile/links/', views.profile_links, name='profile_links'),
    path('profile/resume/', views.profile_resume, name='profile_resume'),
]