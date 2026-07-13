from django.urls import path
from . import views

app_name = 'giveaway'

urlpatterns = [
    path('create/', views.create_giveaway, name='create'),
    path('mine/', views.my_giveaways, name='mine'),
    path('<str:slug>/detail/', views.giveaway_detail, name='detail'),
    path('<str:slug>/cancel/', views.cancel_giveaway, name='cancel'),
    path('<str:slug>/receipt/', views.giveaway_receipt_card, name='receipt'),
    
    # Public Endpoints
    path('claim/<str:slug>/', views.claim_page, name='claim_page'),
    path('claim/<str:slug>/status/<uuid:claim_id>/', views.claim_status, name='claim_status'),
    path('claim/<str:slug>/success/', views.claim_success, name='claim_success'),
    path('claim/<str:slug>/failed/', views.claim_failed, name='claim_failed'),
]
