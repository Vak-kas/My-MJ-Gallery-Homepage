from django.urls import path
from . import views

app_name = 'studio'

urlpatterns = [
    path('', views.index, name='index'),
    path('profile/', views.profile, name='profile'),
    path('profile/basic/', views.profile_basic, name='profile_basic'),

    path('career/', views.career, name='career'),
    
    # Education
    path('career/education/create/', views.education_create, name='education_create'),
    path('career/education/<int:id>/update/', views.education_update, name='education_update'),
    path('career/education/<int:id>/delete/', views.education_delete, name='education_delete'),
    path('career/education/<int:id>/toggle-visibility/', views.education_toggle_visibility, name='education_toggle_visibility'),
    path('career/education/reorder/', views.education_reorder, name='education_reorder'),
    
    # Internship
    path('career/internship/create/', views.internship_create, name='internship_create'),
    path('career/internship/<int:id>/update/', views.internship_update, name='internship_update'),
    path('career/internship/<int:id>/delete/', views.internship_delete, name='internship_delete'),
    path('career/internship/<int:id>/toggle-visibility/', views.internship_toggle_visibility, name='internship_toggle_visibility'),
    path('career/internship/reorder/', views.internship_reorder, name='internship_reorder'),
    
    # Research
    path('career/research/create/', views.research_create, name='research_create'),
    path('career/research/<int:id>/update/', views.research_update, name='research_update'),
    path('career/research/<int:id>/delete/', views.research_delete, name='research_delete'),
    path('career/research/<int:id>/toggle-visibility/', views.research_toggle_visibility, name='research_toggle_visibility'),
    path('career/research/reorder/', views.research_reorder, name='research_reorder'),
    
    # Leadership
    path('career/leadership/create/', views.leadership_create, name='leadership_create'),
    path('career/leadership/<int:id>/update/', views.leadership_update, name='leadership_update'),
    path('career/leadership/<int:id>/delete/', views.leadership_delete, name='leadership_delete'),
    path('career/leadership/<int:id>/toggle-visibility/', views.leadership_toggle_visibility, name='leadership_toggle_visibility'),
    path('career/leadership/reorder/', views.leadership_reorder, name='leadership_reorder'),
    
    # Teaching
    path('career/teaching/create/', views.teaching_create, name='teaching_create'),
    path('career/teaching/<int:id>/update/', views.teaching_update, name='teaching_update'),
    path('career/teaching/<int:id>/delete/', views.teaching_delete, name='teaching_delete'),
    path('career/teaching/<int:id>/toggle-visibility/', views.teaching_toggle_visibility, name='teaching_toggle_visibility'),
    path('career/teaching/reorder/', views.teaching_reorder, name='teaching_reorder'),

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