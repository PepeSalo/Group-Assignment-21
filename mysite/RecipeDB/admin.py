from django.contrib import admin
from django.utils.html import format_html
from .models import (
    Author, Genre, Ingredient, Recipe, RecipeIngredient,
    PublishedRating, PersonalRating, RecipeURL
)


class RecipeIngredientInline(admin.TabularInline):
    """Inline admin for recipe ingredients."""
    model = RecipeIngredient
    extra = 3
    fields = ['ingredient', 'quantity', 'notes', 'order']
    autocomplete_fields = ['ingredient']


class RecipeURLInline(admin.TabularInline):
    """Inline admin for recipe URLs."""
    model = RecipeURL
    extra = 1
    fields = ['url', 'description', 'is_primary', 'verified']


class PublishedRatingInline(admin.TabularInline):
    """Inline admin for published ratings."""
    model = PublishedRating
    extra = 0
    fields = ['source', 'score', 'review_text', 'source_url']


@admin.register(Author)
class AuthorAdmin(admin.ModelAdmin):
    """Admin interface for Author model."""
    list_display = ['get_full_name', 'first_name', 'last_name', 'publisher_name', 'recipe_count', 'created_at']
    list_filter = ['created_at', 'updated_at']
    search_fields = ['first_name', 'last_name', 'publisher_name']
    date_hierarchy = 'created_at'
    ordering = ['last_name', 'first_name', 'publisher_name']
    
    fieldsets = (
        ('Personal Name', {
            'fields': ('first_name', 'last_name'),
            'description': 'For individual authors'
        }),
        ('Publisher/Organization', {
            'fields': ('publisher_name',),
            'description': 'For publisher or organization authors'
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    readonly_fields = ['created_at', 'updated_at']
    
    def recipe_count(self, obj):
        """Display number of recipes by this author."""
        count = obj.recipes.count()
        return format_html('<strong>{}</strong>', count)
    recipe_count.short_description = 'Recipes'
    
    def get_queryset(self, request):
        """Optimize queryset with annotations."""
        queryset = super().get_queryset(request)
        return queryset.prefetch_related('recipes')


@admin.register(Genre)
class GenreAdmin(admin.ModelAdmin):
    """Admin interface for Genre model."""
    list_display = ['name', 'recipe_count', 'created_at']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at']
    ordering = ['name']
    
    def recipe_count(self, obj):
        """Display number of recipes in this genre."""
        count = obj.recipes.count()
        return format_html('<strong>{}</strong>', count)
    recipe_count.short_description = 'Recipes'


@admin.register(Ingredient)
class IngredientAdmin(admin.ModelAdmin):
    """Admin interface for Ingredient model."""
    list_display = ['name', 'recipe_count', 'created_at']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at']
    ordering = ['name']
    
    def recipe_count(self, obj):
        """Display number of recipes using this ingredient."""
        count = obj.recipes.count()
        return format_html('<strong>{}</strong>', count)
    recipe_count.short_description = 'Used in'


@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):
    """Admin interface for Recipe model."""
    list_display = [
        'title', 'get_authors', 'get_genres', 'avg_published_rating', 
        'avg_personal_rating', 'ocr_confidence_display', 'created_at'
    ]
    list_filter = ['created_at', 'genres', 'authors', 'ocr_confidence']
    search_fields = ['title', 'instructions', 'authors__first_name', 'authors__last_name', 
                    'authors__publisher_name', 'ingredients__name']
    filter_horizontal = ['authors', 'genres']
    date_hierarchy = 'created_at'
    readonly_fields = ['created_at', 'updated_at', 'ocr_confidence', 'source_file', 
                      'get_avg_published', 'get_avg_personal', 'created_by']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('title', 'instructions', 'image')
        }),
        ('Relationships', {
            'fields': ('authors', 'genres')
        }),
        ('OCR Information', {
            'fields': ('source_file', 'ocr_confidence'),
            'classes': ('collapse',),
            'description': 'Information from OCR processing'
        }),
        ('Ratings', {
            'fields': ('get_avg_published', 'get_avg_personal'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    inlines = [RecipeIngredientInline, RecipeURLInline, PublishedRatingInline]
    
    def get_authors(self, obj):
        """Display comma-separated list of authors."""
        authors = obj.authors.all()
        if not authors:
            return '-'
        return ', '.join([author.get_full_name() for author in authors[:3]])
    get_authors.short_description = 'Authors'
    
    def get_genres(self, obj):
        """Display comma-separated list of genres."""
        genres = obj.genres.all()
        if not genres:
            return '-'
        return ', '.join([genre.name for genre in genres[:3]])
    get_genres.short_description = 'Genres'
    
    def avg_published_rating(self, obj):
        """Display average published rating."""
        avg = obj.get_average_published_rating()
        if avg is None:
            return '-'
        return format_html('<strong>★ {:.1f}</strong>', avg)
    avg_published_rating.short_description = 'Published'
    
    def avg_personal_rating(self, obj):
        """Display average personal rating."""
        avg = obj.get_average_personal_rating()
        if avg is None:
            return '-'
        return format_html('<strong>★ {:.1f}</strong>', avg)
    avg_personal_rating.short_description = 'Community'
    
    def ocr_confidence_display(self, obj):
        """Display OCR confidence with color coding."""
        if obj.ocr_confidence is None:
            return '-'
        
        percentage = obj.ocr_confidence * 100
        if percentage >= 80:
            color = 'green'
        elif percentage >= 60:
            color = 'orange'
        else:
            color = 'red'
        
        return format_html(
            '<span style="color: {}; font-weight: bold;">{:.1f}%</span>',
            color, percentage
        )
    ocr_confidence_display.short_description = 'OCR Conf.'
    
    def get_avg_published(self, obj):
        """Display average published rating in detail view."""
        avg = obj.get_average_published_rating()
        if avg is None:
            return 'No ratings'
        return f'{avg}/5'
    get_avg_published.short_description = 'Avg Published Rating'
    
    def get_avg_personal(self, obj):
        """Display average personal rating in detail view."""
        avg = obj.get_average_personal_rating()
        if avg is None:
            return 'No ratings'
        return f'{avg}/5'
    get_avg_personal.short_description = 'Avg Personal Rating'
    
    def save_model(self, request, obj, form, change):
        """Set created_by user if not set."""
        if not change:  # Creating new object
            if not obj.created_by:
                obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(RecipeIngredient)
class RecipeIngredientAdmin(admin.ModelAdmin):
    """Admin interface for RecipeIngredient model."""
    list_display = ['recipe', 'ingredient', 'quantity', 'notes', 'order']
    list_filter = ['ingredient']
    search_fields = ['recipe__title', 'ingredient__name', 'quantity', 'notes']
    autocomplete_fields = ['recipe', 'ingredient']
    ordering = ['recipe', 'order', 'ingredient']


@admin.register(PublishedRating)
class PublishedRatingAdmin(admin.ModelAdmin):
    """Admin interface for PublishedRating model."""
    list_display = ['recipe', 'source', 'score', 'has_review', 'has_url', 'created_at']
    list_filter = ['score', 'created_at']
    search_fields = ['recipe__title', 'source', 'review_text']
    autocomplete_fields = ['recipe']
    date_hierarchy = 'created_at'
    readonly_fields = ['created_at']
    ordering = ['-created_at']
    
    def has_review(self, obj):
        """Indicate if rating has review text."""
        return bool(obj.review_text)
    has_review.boolean = True
    has_review.short_description = 'Review'
    
    def has_url(self, obj):
        """Indicate if rating has source URL."""
        return bool(obj.source_url)
    has_url.boolean = True
    has_url.short_description = 'URL'


@admin.register(PersonalRating)
class PersonalRatingAdmin(admin.ModelAdmin):
    """Admin interface for PersonalRating model."""
    list_display = ['recipe', 'user', 'score', 'has_notes', 'created_at', 'updated_at']
    list_filter = ['score', 'created_at', 'updated_at']
    search_fields = ['recipe__title', 'user__username', 'notes']
    autocomplete_fields = ['recipe', 'user']
    date_hierarchy = 'updated_at'
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['-updated_at']
    
    def has_notes(self, obj):
        """Indicate if rating has personal notes."""
        return bool(obj.notes)
    has_notes.boolean = True
    has_notes.short_description = 'Notes'


@admin.register(RecipeURL)
class RecipeURLAdmin(admin.ModelAdmin):
    """Admin interface for RecipeURL model."""
    list_display = ['recipe', 'get_url_display', 'description', 'is_primary', 'verified', 'created_at']
    list_filter = ['is_primary', 'verified', 'created_at']
    search_fields = ['recipe__title', 'url', 'description']
    autocomplete_fields = ['recipe']
    readonly_fields = ['created_at']
    ordering = ['-is_primary', '-created_at']
    
    def get_url_display(self, obj):
        """Display URL as clickable link."""
        if len(obj.url) > 50:
            display_url = obj.url[:47] + '...'
        else:
            display_url = obj.url
        return format_html('<a href="{}" target="_blank">{}</a>', obj.url, display_url)
    get_url_display.short_description = 'URL'


# Customize admin site header
admin.site.site_header = 'RecipeDB Administration'
admin.site.site_title = 'RecipeDB Admin'
admin.site.index_title = 'Welcome to RecipeDB Administration'
