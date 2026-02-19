from django.urls import path
from . import views

urlpatterns = [
    # Home
    path('', views.HomeView.as_view(), name='home'),
    
    # Authentication
    path('signup/', views.signup_view, name='signup'),
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    
    # Recipe CRUD
    path('recipes/', views.RecipeListView.as_view(), name='recipe_list'),
    path('recipes/<int:pk>/', views.RecipeDetailView.as_view(), name='recipe_detail'),
    path('recipes/create/', views.RecipeCreateView.as_view(), name='recipe_create'),
    path('recipes/<int:pk>/edit/', views.RecipeUpdateView.as_view(), name='recipe_update'),
    path('recipes/<int:pk>/delete/', views.RecipeDeleteView.as_view(), name='recipe_delete'),
    
    # Rating
    path('recipes/<int:pk>/rate/', views.rate_recipe, name='rate_recipe'),
    
    # OCR
    path('ocr/upload/', views.ocr_upload, name='ocr_upload'),
    path('ocr/merge/', views.recipe_merge_confirm, name='recipe_merge_confirm'),
    
    # Supporting models
    path('authors/', views.AuthorListView.as_view(), name='author_list'),
    path('ingredients/', views.IngredientListView.as_view(), name='ingredient_list'),
    path('genres/', views.GenreListView.as_view(), name='genre_list'),
]
