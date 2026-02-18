from django.db import models
from django.contrib.auth.models import User
from django.core.validators import MinValueValidator, MaxValueValidator, URLValidator
from django.core.exceptions import ValidationError
from django.urls import reverse

# Constants
MAX_RATING = 5
MIN_RATING = 1
MAX_TITLE_LENGTH = 200
MAX_NAME_LENGTH = 255
MAX_URL_LENGTH = 2000


class Author(models.Model):
    """
    Author model - can have either personal name (first/last) or publisher name.
    At least one must be provided.
    """
    first_name = models.CharField(max_length=MAX_NAME_LENGTH, blank=True, db_index=True)
    last_name = models.CharField(max_length=MAX_NAME_LENGTH, blank=True, db_index=True)
    publisher_name = models.CharField(max_length=MAX_NAME_LENGTH, blank=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['last_name', 'first_name', 'publisher_name']
        indexes = [
            models.Index(fields=['last_name', 'first_name']),
            models.Index(fields=['publisher_name']),
        ]
        verbose_name = 'Author'
        verbose_name_plural = 'Authors'

    def clean(self):
        """Validate that at least one name field is provided."""
        if not self.first_name and not self.last_name and not self.publisher_name:
            raise ValidationError('At least one of first_name, last_name, or publisher_name must be provided.')
        
        # Clean whitespace
        self.first_name = self.first_name.strip() if self.first_name else ''
        self.last_name = self.last_name.strip() if self.last_name else ''
        self.publisher_name = self.publisher_name.strip() if self.publisher_name else ''

    def save(self, *args, **kwargs):
        """Override save to ensure validation."""
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        """String representation of the author."""
        if self.publisher_name:
            return self.publisher_name
        if self.first_name and self.last_name:
            return f"{self.first_name} {self.last_name}"
        if self.first_name:
            return self.first_name
        if self.last_name:
            return self.last_name
        return f"Author {self.id}"

    def get_full_name(self):
        """Get full name of the author."""
        return str(self)


class Genre(models.Model):
    """Genre/Category for recipes (e.g., Dessert, Main Course, Italian, etc.)"""
    name = models.CharField(max_length=MAX_NAME_LENGTH, unique=True, db_index=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Genre'
        verbose_name_plural = 'Genres'

    def clean(self):
        """Clean and validate genre name."""
        if self.name:
            self.name = self.name.strip()
            if not self.name:
                raise ValidationError('Genre name cannot be empty or whitespace only.')

    def save(self, *args, **kwargs):
        """Override save to ensure validation."""
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Ingredient(models.Model):
    """Individual ingredient that can be used in recipes."""
    name = models.CharField(max_length=MAX_NAME_LENGTH, unique=True, db_index=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Ingredient'
        verbose_name_plural = 'Ingredients'

    def clean(self):
        """Clean and validate ingredient name."""
        if self.name:
            self.name = self.name.strip().lower()
            if not self.name:
                raise ValidationError('Ingredient name cannot be empty or whitespace only.')

    def save(self, *args, **kwargs):
        """Override save to ensure validation."""
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Recipe(models.Model):
    """Main recipe model with all relationships."""
    title = models.CharField(max_length=MAX_TITLE_LENGTH, db_index=True)
    instructions = models.TextField(help_text='Step-by-step cooking instructions')
    authors = models.ManyToManyField(Author, related_name='recipes', blank=True)
    genres = models.ManyToManyField(Genre, related_name='recipes', blank=True)
    ingredients = models.ManyToManyField(
        Ingredient, 
        through='RecipeIngredient',
        related_name='recipes'
    )
    
    # OCR and source information
    source_file = models.CharField(max_length=500, blank=True, help_text='Original file path for OCR')
    ocr_confidence = models.FloatField(
        null=True, 
        blank=True,
        validators=[MinValueValidator(0.0), MaxValueValidator(1.0)],
        help_text='OCR confidence score (0-1)'
    )
    image = models.ImageField(upload_to='recipes/', blank=True, null=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='created_recipes'
    )

    class Meta:
        ordering = ['-created_at', 'title']
        indexes = [
            models.Index(fields=['title']),
            models.Index(fields=['-created_at']),
            models.Index(fields=['ocr_confidence']),
        ]
        verbose_name = 'Recipe'
        verbose_name_plural = 'Recipes'

    def clean(self):
        """Validate recipe data."""
        if self.title:
            self.title = self.title.strip()
            if not self.title:
                raise ValidationError('Recipe title cannot be empty or whitespace only.')
        
        if self.instructions:
            self.instructions = self.instructions.strip()
            if not self.instructions:
                raise ValidationError('Recipe instructions cannot be empty or whitespace only.')

    def save(self, *args, **kwargs):
        """Override save to ensure validation."""
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        """Return the URL to view this recipe."""
        return reverse('recipe_detail', kwargs={'pk': self.pk})

    def get_average_published_rating(self):
        """Calculate average of published ratings."""
        published_ratings = self.published_ratings.all()
        if not published_ratings:
            return None
        total = sum(rating.score for rating in published_ratings)
        return round(total / len(published_ratings), 2)

    def get_average_personal_rating(self):
        """Calculate average of personal ratings."""
        personal_ratings = self.personal_ratings.all()
        if not personal_ratings:
            return None
        total = sum(rating.score for rating in personal_ratings)
        return round(total / len(personal_ratings), 2)

    def get_user_personal_rating(self, user):
        """Get a specific user's personal rating for this recipe."""
        if not user.is_authenticated:
            return None
        try:
            return self.personal_ratings.get(user=user)
        except PersonalRating.DoesNotExist:
            return None


class RecipeIngredient(models.Model):
    """Junction table for Recipe-Ingredient relationship with quantity info."""
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE)
    ingredient = models.ForeignKey(Ingredient, on_delete=models.CASCADE)
    quantity = models.CharField(
        max_length=100,
        help_text='Amount and unit (e.g., "2 cups", "500g", "1 tablespoon")'
    )
    notes = models.CharField(max_length=200, blank=True, help_text='e.g., "chopped", "diced"')
    order = models.PositiveIntegerField(default=0, help_text='Display order in recipe')

    class Meta:
        ordering = ['order', 'ingredient__name']
        unique_together = ['recipe', 'ingredient']
        indexes = [
            models.Index(fields=['recipe', 'order']),
        ]
        verbose_name = 'Recipe Ingredient'
        verbose_name_plural = 'Recipe Ingredients'

    def __str__(self):
        return f"{self.quantity} {self.ingredient.name}"


class PublishedRating(models.Model):
    """Published/official ratings for recipes (e.g., from cookbooks, websites)."""
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name='published_ratings')
    score = models.IntegerField(
        validators=[MinValueValidator(MIN_RATING), MaxValueValidator(MAX_RATING)],
        help_text=f'Rating from {MIN_RATING} to {MAX_RATING}'
    )
    source = models.CharField(max_length=MAX_NAME_LENGTH, help_text='Source of the rating')
    review_text = models.TextField(blank=True)
    source_url = models.URLField(max_length=MAX_URL_LENGTH, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipe', 'score']),
            models.Index(fields=['-created_at']),
        ]
        verbose_name = 'Published Rating'
        verbose_name_plural = 'Published Ratings'

    def clean(self):
        """Validate rating fields."""
        if self.source:
            self.source = self.source.strip()
            if not self.source:
                raise ValidationError('Source cannot be empty or whitespace only.')

    def save(self, *args, **kwargs):
        """Override save to ensure validation."""
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.recipe.title} - {self.score}/5 by {self.source}"


class PersonalRating(models.Model):
    """Personal user ratings for recipes."""
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name='personal_ratings')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='recipe_ratings')
    score = models.IntegerField(
        validators=[MinValueValidator(MIN_RATING), MaxValueValidator(MAX_RATING)],
        help_text=f'Your rating from {MIN_RATING} to {MAX_RATING}'
    )
    notes = models.TextField(blank=True, help_text='Your personal notes about this recipe')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        ordering = ['-updated_at']
        unique_together = ['recipe', 'user']
        indexes = [
            models.Index(fields=['recipe', 'user']),
            models.Index(fields=['user', '-updated_at']),
            models.Index(fields=['recipe', 'score']),
        ]
        verbose_name = 'Personal Rating'
        verbose_name_plural = 'Personal Ratings'

    def __str__(self):
        return f"{self.recipe.title} - {self.score}/5 by {self.user.username}"


class RecipeURL(models.Model):
    """URL addresses associated with recipes."""
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name='urls')
    url = models.URLField(max_length=MAX_URL_LENGTH, validators=[URLValidator()])
    description = models.CharField(max_length=MAX_NAME_LENGTH, blank=True, help_text='Description of the URL')
    is_primary = models.BooleanField(default=False, help_text='Primary/official source URL')
    created_at = models.DateTimeField(auto_now_add=True)
    verified = models.BooleanField(default=False, help_text='URL has been verified to work')

    class Meta:
        ordering = ['-is_primary', '-created_at']
        indexes = [
            models.Index(fields=['recipe', '-is_primary']),
        ]
        verbose_name = 'Recipe URL'
        verbose_name_plural = 'Recipe URLs'

    def clean(self):
        """Validate URL fields."""
        if self.url:
            self.url = self.url.strip()
            if not self.url:
                raise ValidationError('URL cannot be empty or whitespace only.')

    def save(self, *args, **kwargs):
        """Override save to ensure validation."""
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        if self.description:
            return f"{self.recipe.title} - {self.description}"
        return f"{self.recipe.title} - {self.url[:50]}"
