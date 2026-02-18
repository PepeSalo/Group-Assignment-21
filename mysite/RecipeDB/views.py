import os
import logging
import shutil
import subprocess
import threading
import time
import gc
from pathlib import Path

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, PermissionRequiredMixin
from django.contrib import messages
from django.views.generic import (
    ListView, DetailView, CreateView, UpdateView, DeleteView, TemplateView
)
from django.urls import reverse_lazy, reverse
from django.db.models import Q, Avg, Count
from django.http import JsonResponse, HttpResponseRedirect
from django.conf import settings
from django.core.paginator import Paginator

import pytesseract
from PIL import Image

from .models import (
    Recipe, Author, Genre, Ingredient, RecipeIngredient,
    PersonalRating, PublishedRating, RecipeURL
)
from .forms import (
    CustomUserCreationForm, CustomAuthenticationForm, RecipeSearchForm,
    PersonalRatingForm, RecipeForm, RecipeIngredientForm, RecipeURLForm,
    AuthorForm, IngredientForm, GenreForm, OCRUploadForm
)

# Configure logging
logger = logging.getLogger(__name__)

# Constants for file operations
FILE_DELETE_MAX_RETRIES = 30
FILE_DELETE_RETRY_DELAY = 2.0  # seconds


def _background_delete_file(file_path):
    """
    Delete a file in a background thread with retries.
    Waits for external locks (antivirus, Explorer thumbnails, etc.) to release.
    Runs entirely in the background — does not block the web request.
    """
    file_path = Path(file_path)

    def _do_delete():
        for attempt in range(FILE_DELETE_MAX_RETRIES):
            if not file_path.exists():
                logger.info(f"Background delete: file already gone: {file_path}")
                return
            try:
                gc.collect()
                file_path.unlink()
                logger.info(f"Background delete succeeded (attempt {attempt + 1}): {file_path}")
                return
            except OSError as e:
                logger.debug(f"Background delete attempt {attempt + 1}/{FILE_DELETE_MAX_RETRIES} "
                             f"failed ({e}): {file_path}")
                time.sleep(FILE_DELETE_RETRY_DELAY)
        logger.warning(f"Background delete gave up after {FILE_DELETE_MAX_RETRIES} retries: {file_path}")

    thread = threading.Thread(target=_do_delete, daemon=True)
    thread.start()
    logger.debug(f"Scheduled background delete for: {file_path}")

# Configure Tesseract
if hasattr(settings, 'TESSERACT_CMD'):
    pytesseract.pytesseract.tesseract_cmd = settings.TESSERACT_CMD


# ============= Home and Basic Views =============

class HomeView(TemplateView):
    """Home page view."""
    template_name = 'RecipeDB/home.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        try:
            context['total_recipes'] = Recipe.objects.count()
            context['total_authors'] = Author.objects.count()
            context['total_genres'] = Genre.objects.count()
            context['recent_recipes'] = Recipe.objects.all()[:6]
        except Exception as e:
            logger.error(f"Error loading home page data: {e}")
            context['error'] = "Error loading data"
        return context


# ============= Authentication Views =============

def signup_view(request):
    """User registration view."""
    if request.user.is_authenticated:
        return redirect('recipe_list')
    
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)
        try:
            if form.is_valid():
                user = form.save()
                login(request, user)
                messages.success(request, 'Account created successfully!')
                return redirect('recipe_list')
            else:
                for field, errors in form.errors.items():
                    for error in errors:
                        messages.error(request, f'{field}: {error}')
        except Exception as e:
            logger.error(f"Error during signup: {e}")
            messages.error(request, 'An error occurred during registration.')
    else:
        form = CustomUserCreationForm()
    
    return render(request, 'RecipeDB/signup.html', {'form': form})


def login_view(request):
    """User login view."""
    if request.user.is_authenticated:
        return redirect('recipe_list')
    
    if request.method == 'POST':
        form = CustomAuthenticationForm(request, data=request.POST)
        try:
            if form.is_valid():
                user = form.get_user()
                login(request, user)
                messages.success(request, f'Welcome back, {user.username}!')
                next_url = request.GET.get('next', 'recipe_list')
                return redirect(next_url)
            else:
                messages.error(request, 'Invalid username or password.')
        except Exception as e:
            logger.error(f"Error during login: {e}")
            messages.error(request, 'An error occurred during login.')
    else:
        form = CustomAuthenticationForm()
    
    return render(request, 'RecipeDB/login.html', {'form': form})


@login_required
def logout_view(request):
    """User logout view."""
    logout(request)
    messages.info(request, 'You have been logged out.')
    return redirect('home')


# ============= Recipe Views =============

class RecipeListView(ListView):
    """List all recipes with pagination."""
    model = Recipe
    template_name = 'RecipeDB/recipe_list.html'
    context_object_name = 'recipes'
    paginate_by = 12

    def get_queryset(self):
        """Get filtered queryset based on search parameters."""
        queryset = Recipe.objects.all().prefetch_related(
            'authors', 'genres', 'ingredients'
        )
        
        try:
            form = RecipeSearchForm(self.request.GET)
            if form.is_valid():
                query = form.cleaned_data.get('query')
                author = form.cleaned_data.get('author')
                genre = form.cleaned_data.get('genre')
                ingredient = form.cleaned_data.get('ingredient')
                min_rating = form.cleaned_data.get('min_rating')

                # General search query (title, author, ingredients)
                if query:
                    queryset = queryset.filter(
                        Q(title__icontains=query) |
                        Q(authors__first_name__icontains=query) |
                        Q(authors__last_name__icontains=query) |
                        Q(authors__publisher_name__icontains=query) |
                        Q(ingredients__name__icontains=query)
                    ).distinct()

                # Author filter
                if author:
                    queryset = queryset.filter(
                        Q(authors__first_name__icontains=author) |
                        Q(authors__last_name__icontains=author) |
                        Q(authors__publisher_name__icontains=author)
                    ).distinct()

                # Genre filter
                if genre:
                    queryset = queryset.filter(genres=genre)

                # Ingredient filter
                if ingredient:
                    queryset = queryset.filter(
                        ingredients__name__icontains=ingredient
                    ).distinct()

                # Rating filter
                if min_rating:
                    # Filter by personal ratings average
                    queryset = queryset.annotate(
                        avg_rating=Avg('personal_ratings__score')
                    ).filter(avg_rating__gte=min_rating)
        
        except Exception as e:
            logger.error(f"Error filtering recipes: {e}")
        
        return queryset.order_by('-created_at')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['search_form'] = RecipeSearchForm(self.request.GET)
        return context


class RecipeDetailView(DetailView):
    """Detail view for a single recipe."""
    model = Recipe
    template_name = 'RecipeDB/recipe_detail.html'
    context_object_name = 'recipe'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        recipe = self.object
        
        try:
            # Get all related data
            context['recipe_ingredients'] = RecipeIngredient.objects.filter(
                recipe=recipe
            ).select_related('ingredient').order_by('order')
            
            context['recipe_urls'] = RecipeURL.objects.filter(recipe=recipe)
            context['published_ratings'] = PublishedRating.objects.filter(recipe=recipe)
            context['personal_ratings'] = PersonalRating.objects.filter(recipe=recipe)
            
            # Get user's personal rating if logged in
            if self.request.user.is_authenticated:
                context['user_rating'] = recipe.get_user_personal_rating(self.request.user)
                context['rating_form'] = PersonalRatingForm()
            
            # Calculate averages
            context['avg_published_rating'] = recipe.get_average_published_rating()
            context['avg_personal_rating'] = recipe.get_average_personal_rating()
            
        except Exception as e:
            logger.error(f"Error loading recipe details: {e}")
            context['error'] = "Error loading recipe details"
        
        return context


def _save_ingredients_from_text(recipe, ingredients_text):
    """
    Parse ingredients text and save to recipe.
    Each line: 'quantity - ingredient name' or 'quantity - ingredient name (notes)'
    Lines without ' - ' separator are treated as ingredient name only.
    """
    from .models import MAX_NAME_LENGTH
    
    # Remove existing ingredients
    RecipeIngredient.objects.filter(recipe=recipe).delete()
    
    if not ingredients_text or not ingredients_text.strip():
        return
    
    lines = [line.strip() for line in ingredients_text.split('\n') if line.strip()]
    
    for order, line in enumerate(lines):
        quantity = ''
        notes = ''
        name = line
        
        # Extract notes in parentheses at the end
        if '(' in line and line.rstrip().endswith(')'):
            notes_start = line.rfind('(')
            notes = line[notes_start + 1:-1].strip()
            line = line[:notes_start].strip()
        
        # Split on ' - ' to separate quantity from name
        if ' - ' in line:
            parts = line.split(' - ', 1)
            quantity = parts[0].strip()[:100]
            name = parts[1].strip()
        else:
            name = line.strip()
        
        # Truncate and clean name
        name = name.lower()[:MAX_NAME_LENGTH]
        if not name:
            continue
        
        ingredient, _ = Ingredient.objects.get_or_create(name=name)
        RecipeIngredient.objects.create(
            recipe=recipe,
            ingredient=ingredient,
            quantity=quantity,
            notes=notes[:200],
            order=order
        )


def _save_authors_from_text(recipe, authors_text):
    """
    Parse authors text and save to recipe.
    Each line is an author name. New authors are created automatically.
    """
    from .models import MAX_NAME_LENGTH
    
    recipe.authors.clear()
    
    if not authors_text or not authors_text.strip():
        return
    
    lines = [line.strip() for line in authors_text.split('\n') if line.strip()]
    
    for line in lines:
        name = line[:MAX_NAME_LENGTH]
        # Try to find existing author by any name field
        author = Author.objects.filter(
            Q(publisher_name__iexact=name) |
            Q(first_name__iexact=name) |
            Q(last_name__iexact=name)
        ).first()
        
        if not author:
            # Check if name has two parts (first last)
            parts = name.split(None, 1)
            if len(parts) == 2:
                author, _ = Author.objects.get_or_create(
                    first_name=parts[0][:MAX_NAME_LENGTH],
                    last_name=parts[1][:MAX_NAME_LENGTH],
                    defaults={'publisher_name': ''}
                )
            else:
                author, _ = Author.objects.get_or_create(
                    publisher_name=name
                )
        
        recipe.authors.add(author)


def _save_genres_from_text(recipe, genres_text):
    """
    Parse genres text and save to recipe.
    Each line is a genre name. New genres are created automatically.
    """
    from .models import MAX_NAME_LENGTH
    
    recipe.genres.clear()
    
    if not genres_text or not genres_text.strip():
        return
    
    lines = [line.strip() for line in genres_text.split('\n') if line.strip()]
    
    for line in lines:
        name = line[:MAX_NAME_LENGTH]
        genre, _ = Genre.objects.get_or_create(name__iexact=name, defaults={'name': name})
        recipe.genres.add(genre)


def _save_source_url(recipe, source_url):
    """Save or update the primary source URL for a recipe."""
    if not source_url or not source_url.strip():
        return
    
    source_url = source_url.strip()
    
    # Try to update existing primary URL
    existing = RecipeURL.objects.filter(recipe=recipe, is_primary=True).first()
    if existing:
        if existing.url != source_url:
            existing.url = source_url
            existing.save()
    else:
        # Check if this URL already exists for this recipe
        existing_url = RecipeURL.objects.filter(recipe=recipe, url=source_url).first()
        if existing_url:
            existing_url.is_primary = True
            existing_url.save()
        else:
            RecipeURL.objects.create(
                recipe=recipe,
                url=source_url,
                description='Source',
                is_primary=True
            )


def _save_recipe_related_text(recipe, form):
    """Save all text-based related fields for a recipe."""
    _save_ingredients_from_text(recipe, form.cleaned_data.get('ingredients_text', ''))
    _save_authors_from_text(recipe, form.cleaned_data.get('authors_text', ''))
    _save_genres_from_text(recipe, form.cleaned_data.get('genres_text', ''))
    _save_source_url(recipe, form.cleaned_data.get('source_url', ''))


class RecipeCreateView(LoginRequiredMixin, CreateView):
    """Create a new recipe."""
    model = Recipe
    form_class = RecipeForm
    template_name = 'RecipeDB/recipe_form.html'
    success_url = reverse_lazy('recipe_list')

    def form_valid(self, form):
        """Set the created_by user and save related data."""
        try:
            form.instance.created_by = self.request.user
            response = super().form_valid(form)
            _save_recipe_related_text(self.object, form)
            messages.success(self.request, 'Recipe created successfully!')
            return response
        except Exception as e:
            logger.error(f"Error creating recipe: {e}")
            messages.error(self.request, 'Error creating recipe.')
            return self.form_invalid(form)


class RecipeUpdateView(LoginRequiredMixin, UpdateView):
    """Update an existing recipe."""
    model = Recipe
    form_class = RecipeForm
    template_name = 'RecipeDB/recipe_form.html'

    def dispatch(self, request, *args, **kwargs):
        """Check user has change permission or is the recipe creator."""
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        obj = self.get_object()
        if not (
            request.user == obj.created_by
            or request.user.has_perm('RecipeDB.change_recipe')
        ):
            messages.error(request, 'You do not have permission to edit this recipe.')
            return redirect('recipe_detail', pk=obj.pk)
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        """Save the updated recipe and related data."""
        try:
            response = super().form_valid(form)
            _save_recipe_related_text(self.object, form)
            messages.success(self.request, 'Recipe updated successfully!')
            return response
        except Exception as e:
            logger.error(f"Error updating recipe: {e}")
            messages.error(self.request, 'Error updating recipe.')
            return self.form_invalid(form)


class RecipeDeleteView(LoginRequiredMixin, DeleteView):
    """Delete a recipe. Requires delete permission or recipe ownership."""
    model = Recipe
    template_name = 'RecipeDB/recipe_confirm_delete.html'
    success_url = reverse_lazy('recipe_list')

    def dispatch(self, request, *args, **kwargs):
        """Check user has delete permission or is the recipe creator."""
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        obj = self.get_object()
        if not (
            request.user == obj.created_by
            or request.user.has_perm('RecipeDB.delete_recipe')
        ):
            messages.error(request, 'You do not have permission to delete this recipe.')
            return redirect('recipe_detail', pk=obj.pk)
        return super().dispatch(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        """Delete the recipe with message."""
        try:
            messages.success(request, 'Recipe deleted successfully!')
            return super().delete(request, *args, **kwargs)
        except Exception as e:
            logger.error(f"Error deleting recipe: {e}")
            messages.error(request, 'Error deleting recipe.')
            return redirect('recipe_list')


# ============= Rating Views =============

@login_required
def rate_recipe(request, pk):
    """Add or update a personal rating for a recipe."""
    recipe = get_object_or_404(Recipe, pk=pk)
    
    if request.method == 'POST':
        try:
            # Try to get existing rating
            try:
                rating = PersonalRating.objects.get(recipe=recipe, user=request.user)
                created = False
            except PersonalRating.DoesNotExist:
                rating = PersonalRating(recipe=recipe, user=request.user)
                created = True
            
            form = PersonalRatingForm(request.POST, instance=rating)
            if form.is_valid():
                form.save()
                if created:
                    messages.success(request, 'Rating added successfully!')
                else:
                    messages.success(request, 'Rating updated successfully!')
            else:
                for field, errors in form.errors.items():
                    for error in errors:
                        messages.error(request, f'{field}: {error}')
        except Exception as e:
            logger.error(f"Error rating recipe: {e}")
            messages.error(request, 'Error saving rating.')
    
    return redirect('recipe_detail', pk=pk)


# ============= OCR Views =============

@login_required
def ocr_upload(request):
    """Upload images for OCR processing."""
    if request.method == 'POST':
        form = OCRUploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                image_file = form.cleaned_data['image_file']
                auto_search_web = form.cleaned_data.get('auto_search_web', False)
                original_filename = image_file.name
                logger.debug(f"OCR upload: original_filename={original_filename!r}")
                
                # Process the image
                result = process_ocr_image(image_file, request.user, auto_search_web)
                logger.debug(f"OCR result: success={result.get('success')}, error={result.get('error', 'none')}")
                
                # Close the uploaded file to release handles before file ops
                image_file.close()
                gc.collect()
                
                # Handle the source file in IMAGES folder
                images_folder = Path(getattr(settings, 'OCR_IMAGES_FOLDER', ''))
                logger.debug(f"IMAGES folder: {images_folder}, exists={images_folder.exists()}")
                if images_folder.exists():
                    source_path = images_folder / original_filename
                    logger.debug(f"Trying exact match: {source_path}, exists={source_path.exists()}")
                    
                    # Django sanitizes filenames (spaces → underscores), so also try
                    # the original name with underscores replaced back to spaces
                    if not source_path.exists():
                        alt_name = original_filename.replace('_', ' ')
                        alt_path = images_folder / alt_name
                        logger.debug(f"Trying spaces restored: {alt_path}, exists={alt_path.exists()}")
                        if alt_path.exists():
                            source_path = alt_path
                            logger.info(f"Matched with spaces restored: {source_path}")
                    
                    # If still not found, search the folder for a matching file
                    if not source_path.exists():
                        logger.info(f"No match for '{original_filename}' in {images_folder}, searching...")
                        orig_stem = Path(original_filename).stem.lower().replace('_', ' ')
                        orig_suffix = Path(original_filename).suffix.lower()
                        for f in images_folder.iterdir():
                            if f.is_file() and not f.name.startswith('ERR_'):
                                if (f.suffix.lower() == orig_suffix and 
                                    f.stem.lower().replace('_', ' ') == orig_stem):
                                    source_path = f
                                    logger.info(f"Fuzzy matched to: {source_path}")
                                    break
                    
                    if source_path.exists():
                        if result['success']:
                            # Delete from IMAGES folder (already saved to media/recipes)
                            # Schedule in background so user doesn't wait
                            _background_delete_file(source_path)
                            messages.info(request, "Source image will be deleted from IMAGES folder.")
                        else:
                            # Rename with ERR prefix: copy immediately, delete original in background
                            err_name = f"ERR_{source_path.name}"
                            err_path = images_folder / err_name
                            # Avoid overwriting existing ERR files
                            counter = 1
                            while err_path.exists():
                                stem = source_path.stem
                                suffix = source_path.suffix
                                err_name = f"ERR_{stem}_{counter}{suffix}"
                                err_path = images_folder / err_name
                                counter += 1
                            try:
                                shutil.copy2(str(source_path), str(err_path))
                                logger.info(f"Copied failed OCR image to: {err_path}")
                                messages.info(request, f"Source image renamed to {err_name}")
                                # Delete original in background
                                _background_delete_file(source_path)
                            except Exception as e:
                                logger.warning(f"Could not copy source image: {e}")
                                messages.warning(request, f"Could not rename source image: {e}")
                    else:
                        logger.warning(f"Source image not found in IMAGES folder: {original_filename}")
                        messages.warning(request, f"Source image '{original_filename}' not found in IMAGES folder.")
                
                if result['success']:
                    messages.success(request, f"Recipe processed successfully! Confidence: {result['confidence']:.1%}")
                    return redirect('recipe_detail', pk=result['recipe_id'])
                else:
                    messages.error(request, f"OCR processing failed: {result['error']}")
            except Exception as e:
                logger.error(f"Error during OCR upload: {e}")
                messages.error(request, 'Error processing image.')
    else:
        form = OCRUploadForm()
    
    return render(request, 'RecipeDB/ocr_upload.html', {'form': form})


def process_ocr_image(image_file, user, auto_search_web=False):
    """
    Process an image file using OCR to extract recipe information.
    
    Args:
        image_file: Uploaded image file
        user: User who uploaded the file
        auto_search_web: Whether to search web for additional info
        
    Returns:
        dict with 'success', 'recipe_id', 'confidence', and 'error' keys
    """
    try:
        # Reset file pointer to the beginning
        image_file.seek(0)
        
        # Open and process the image
        image = Image.open(image_file)
        
        try:
            # Convert image to RGB if necessary (some formats may not work with Tesseract)
            if image.mode not in ('RGB', 'L'):
                image = image.convert('RGB')
            
            # Perform OCR
            text = pytesseract.image_to_string(image)
            
            # Get OCR confidence data
            data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
            confidences = [float(conf) for conf in data['conf'] if conf != '-1']
            avg_confidence = sum(confidences) / len(confidences) / 100.0 if confidences else 0.0
        finally:
            # Close the PIL image to release file handles
            image.close()
        
        # Determine if OCR was successful
        threshold = getattr(settings, 'OCR_CONFIDENCE_THRESHOLD', 0.7)
        success = avg_confidence >= threshold
        
        if not success:
            # Rename file with 'U' prefix for unsuccessful
            return {
                'success': False,
                'error': f'OCR confidence too low: {avg_confidence:.1%}',
                'confidence': avg_confidence
            }
        
        # Extract recipe information from text
        recipe_data = extract_recipe_from_text(text)
        
        if not recipe_data.get('title'):
            return {
                'success': False,
                'error': 'Could not extract recipe title from image',
                'confidence': avg_confidence
            }
        
        # Truncate title to fit model field limit
        from .models import MAX_TITLE_LENGTH, MAX_NAME_LENGTH
        title = recipe_data['title'][:MAX_TITLE_LENGTH]
        
        # Create recipe
        recipe = Recipe.objects.create(
            title=title,
            instructions=recipe_data.get('instructions', ''),
            created_by=user,
            ocr_confidence=avg_confidence,
            source_file=image_file.name
        )
        
        # Save the image
        recipe.image.save(image_file.name, image_file, save=True)
        
        # Add authors if extracted
        for author_name in recipe_data.get('authors', []):
            author_name_truncated = author_name[:MAX_NAME_LENGTH]
            author, _ = Author.objects.get_or_create(
                publisher_name=author_name_truncated
            )
            recipe.authors.add(author)
        
        # Add ingredients if extracted
        for ing_data in recipe_data.get('ingredients', []):
            ing_name = ing_data['name'].lower()[:MAX_NAME_LENGTH]
            ingredient, _ = Ingredient.objects.get_or_create(
                name=ing_name
            )
            RecipeIngredient.objects.create(
                recipe=recipe,
                ingredient=ingredient,
                quantity=ing_data.get('quantity', '')[:100],
                order=ing_data.get('order', 0)
            )
        
        # Search web for recipe URL if checkbox was checked
        if auto_search_web and recipe_data.get('title'):
            found_url = _search_web_for_recipe(recipe_data['title'])
            if found_url:
                RecipeURL.objects.create(
                    recipe=recipe,
                    url=found_url,
                    description='Found via web search',
                    is_primary=True
                )
        
        return {
            'success': True,
            'recipe_id': recipe.pk,
            'confidence': avg_confidence
        }
        
    except Exception as e:
        logger.error(f"Error processing OCR image: {e}")
        return {
            'success': False,
            'error': str(e),
            'confidence': 0.0
        }


def _search_web_for_recipe(title):
    """
    Search the web for a recipe by title and return the URL if found.
    
    Uses a simple search via urllib. Returns the first relevant result URL
    or None if no result found.
    
    Args:
        title: Recipe title to search for
        
    Returns:
        str URL or None
    """
    try:
        import urllib.request
        import urllib.parse
        import json
        
        # Use DuckDuckGo Instant Answer API (no API key needed)
        query = urllib.parse.quote(f"{title} recipe")
        url = f"https://api.duckduckgo.com/?q={query}&format=json&no_html=1"
        
        req = urllib.request.Request(url, headers={'User-Agent': 'RecipeDB/1.0'})
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
        
        # Check for a direct result URL
        if data.get('AbstractURL'):
            return data['AbstractURL']
        
        # Check related topics for a URL
        for topic in data.get('Results', []):
            if topic.get('FirstURL'):
                return topic['FirstURL']
        
        for topic in data.get('RelatedTopics', []):
            if topic.get('FirstURL'):
                return topic['FirstURL']
        
        return None
        
    except Exception as e:
        logger.warning(f"Web search for recipe '{title}' failed: {e}")
        return None


def extract_recipe_from_text(text):
    """
    Extract structured recipe data from OCR text.
    
    This is a simple implementation - you can enhance it with NLP.
    
    Args:
        text: Raw text from OCR
        
    Returns:
        dict with recipe data
    """
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    recipe_data = {
        'title': '',
        'instructions': '',
        'authors': [],
        'ingredients': []
    }
    
    try:
        # First non-empty line is likely the title
        if lines:
            recipe_data['title'] = lines[0]
        
        # Simple heuristic: lines with measurements are likely ingredients
        ingredient_keywords = ['cup', 'tablespoon', 'teaspoon', 'gram', 'g', 'kg', 'ml', 'oz', 'lb']
        
        for i, line in enumerate(lines[1:], start=1):
            lower_line = line.lower()
            if any(keyword in lower_line for keyword in ingredient_keywords):
                # Try to separate quantity from ingredient name
                parts = line.split(None, 2)  # Split into max 3 parts
                if len(parts) >= 2:
                    recipe_data['ingredients'].append({
                        'name': ' '.join(parts[1:]) if len(parts) > 2 else parts[1],
                        'quantity': parts[0],
                        'order': len(recipe_data['ingredients'])
                    })
        
        # Everything else goes to instructions
        instruction_lines = [l for l in lines[1:] if l not in [ing['name'] for ing in recipe_data['ingredients']]]
        recipe_data['instructions'] = '\n'.join(instruction_lines)
        
    except Exception as e:
        logger.error(f"Error extracting recipe data from text: {e}")
    
    return recipe_data


# ============= Additional CRUD Views =============

class AuthorListView(ListView):
    """List all authors."""
    model = Author
    template_name = 'RecipeDB/author_list.html'
    context_object_name = 'authors'
    paginate_by = 20


class IngredientListView(ListView):
    """List all ingredients."""
    model = Ingredient
    template_name = 'RecipeDB/ingredient_list.html'
    context_object_name = 'ingredients'
    paginate_by = 50


class GenreListView(ListView):
    """List all genres."""
    model = Genre
    template_name = 'RecipeDB/genre_list.html'
    context_object_name = 'genres'
    paginate_by = 20
