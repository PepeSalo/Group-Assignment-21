from django.test import TestCase, Client, override_settings
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys
import os
import tempfile
import shutil
import threading
import time
import urllib.error

from .models import (
    Author, Genre, Ingredient, Recipe, RecipeIngredient,
    PublishedRating, PersonalRating, RecipeURL,
    MAX_RATING, MIN_RATING, MAX_NAME_LENGTH, MAX_TITLE_LENGTH
)
from .forms import OCRUploadForm
from .views import (
    _save_ingredients_from_text, _save_authors_from_text,
    _save_genres_from_text, _save_source_url,
    _background_delete_file, extract_recipe_from_text,
    _extract_urls_from_text, _repair_ocr_url,
    _extract_jsonld_recipe, _parse_jsonld_recipe,
    _clean_html_text, _merge_recipe_data,
    _get_existing_recipe_data, _combine_ocr_and_url_data,
    _find_existing_recipe_by_url, _find_existing_recipe_by_title,
    _create_recipe_from_data, _save_ingredients_list,
    _add_author_by_name, _serialize_conflicts, _serialize_new_data,
    scrape_recipe_from_url,
)


class AuthorModelTest(TestCase):
    """Test Author model with various input types."""
    
    def test_author_with_chinese_name(self):
        """Test author with Chinese characters."""
        author = Author.objects.create(
            first_name='张',
            last_name='伟'
        )
        self.assertEqual(str(author), '张 伟')
        self.assertEqual(author.get_full_name(), '张 伟')
    
    def test_author_with_arabic_name(self):
        """Test author with Arabic characters."""
        author = Author.objects.create(
            first_name='محمد',
            last_name='علي'
        )
        self.assertEqual(str(author), 'محمد علي')
    
    def test_author_publisher_only(self):
        """Test author with only publisher name."""
        author = Author.objects.create(publisher_name='测试出版社')
        self.assertEqual(str(author), '测试出版社')
    
    def test_author_validation_all_empty(self):
        """Test that at least one name field is required."""
        author = Author()
        with self.assertRaises(ValidationError):
            author.save()
    
    def test_author_whitespace_cleanup(self):
        """Test that whitespace is properly cleaned."""
        author = Author.objects.create(
            first_name='  John  ',
            last_name='  Doe  '
        )
        self.assertEqual(author.first_name, 'John')
        self.assertEqual(author.last_name, 'Doe')
    
    def test_very_long_name(self):
        """Test with very long names."""
        long_name = 'A' * 100
        author = Author.objects.create(first_name=long_name)
        self.assertEqual(author.first_name, long_name)


class GenreModelTest(TestCase):
    """Test Genre model with various input types."""
    
    def test_genre_with_chinese_text(self):
        """Test genre with Chinese characters."""
        genre = Genre.objects.create(
            name='中式料理',
            description='传统中国菜'
        )
        self.assertEqual(genre.name, '中式料理')
        self.assertEqual(str(genre), '中式料理')
    
    def test_genre_with_arabic_text(self):
        """Test genre with Arabic characters."""
        genre = Genre.objects.create(
            name='المطبخ العربي',
            description='الطعام العربي التقليدي'
        )
        self.assertEqual(genre.name, 'المطبخ العربي')
    
    def test_genre_unique_constraint(self):
        """Test that genre names must be unique."""
        Genre.objects.create(name='Italian')
        with self.assertRaises(Exception):  # IntegrityError
            Genre.objects.create(name='Italian')
    
    def test_genre_empty_name_validation(self):
        """Test that empty genre name is not allowed."""
        genre = Genre(name='   ')
        with self.assertRaises(ValidationError):
            genre.save()


class IngredientModelTest(TestCase):
    """Test Ingredient model with various input types."""
    
    def test_ingredient_with_chinese_text(self):
        """Test ingredient with Chinese characters."""
        ingredient = Ingredient.objects.create(
            name='姜',
            description='新鲜的生姜'
        )
        self.assertEqual(ingredient.name, '姜')
    
    def test_ingredient_with_arabic_text(self):
        """Test ingredient with Arabic characters."""
        ingredient = Ingredient.objects.create(
            name='الزعفران',
            description='بهار ثمين'
        )
        self.assertEqual(ingredient.name, 'الزعفران')
    
    def test_ingredient_lowercase_conversion(self):
        """Test that ingredient names are converted to lowercase."""
        ingredient = Ingredient.objects.create(name='FLOUR')
        self.assertEqual(ingredient.name, 'flour')
    
    def test_ingredient_unique_constraint(self):
        """Test that ingredient names must be unique."""
        Ingredient.objects.create(name='salt')
        with self.assertRaises(Exception):  # IntegrityError
            Ingredient.objects.create(name='salt')


class RecipeModelTest(TestCase):
    """Test Recipe model with various input types."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user('testuser', 'test@test.com', 'password')
        self.author = Author.objects.create(first_name='Test', last_name='Author')
        self.genre = Genre.objects.create(name='Test Genre')
        self.ingredient = Ingredient.objects.create(name='test ingredient')
    
    def test_recipe_with_chinese_title(self):
        """Test recipe with Chinese title and instructions."""
        recipe = Recipe.objects.create(
            title='宫保鸡丁',
            instructions='先炒鸡肉，然后加入花生和辣椒',
            created_by=self.user
        )
        recipe.authors.add(self.author)
        self.assertEqual(recipe.title, '宫保鸡丁')
        self.assertEqual(str(recipe), '宫保鸡丁')
    
    def test_recipe_with_arabic_title(self):
        """Test recipe with Arabic title and instructions."""
        recipe = Recipe.objects.create(
            title='المندي',
            instructions='طريقة تحضير المندي اليمني',
            created_by=self.user
        )
        recipe.authors.add(self.author)
        self.assertEqual(recipe.title, 'المندي')
    
    def test_recipe_ocr_confidence_validation(self):
        """Test OCR confidence value validation."""
        # Valid confidence values
        recipe1 = Recipe.objects.create(
            title='Test',
            instructions='Test',
            ocr_confidence=0.0,
            created_by=self.user
        )
        recipe1.authors.add(self.author)
        self.assertEqual(recipe1.ocr_confidence, 0.0)
        
        recipe2 = Recipe.objects.create(
            title='Test2',
            instructions='Test',
            ocr_confidence=1.0,
            created_by=self.user
        )
        recipe2.authors.add(self.author)
        self.assertEqual(recipe2.ocr_confidence, 1.0)
        
        recipe3 = Recipe.objects.create(
            title='Test3',
            instructions='Test',
            ocr_confidence=0.5,
            created_by=self.user
        )
        recipe3.authors.add(self.author)
        self.assertEqual(recipe3.ocr_confidence, 0.5)
    
    def test_recipe_average_ratings(self):
        """Test average rating calculations."""
        recipe = Recipe.objects.create(
            title='Test Recipe',
            instructions='Test instructions',
            created_by=self.user
        )
        recipe.authors.add(self.author)
        
        # Add published ratings
        PublishedRating.objects.create(recipe=recipe, source='Source1', score=5)
        PublishedRating.objects.create(recipe=recipe, source='Source2', score=3)
        
        self.assertEqual(recipe.get_average_published_rating(), 4.0)
        
        # Add personal ratings
        user2 = User.objects.create_user('user2', 'user2@test.com', 'password')
        PersonalRating.objects.create(recipe=recipe, user=self.user, score=4)
        PersonalRating.objects.create(recipe=recipe, user=user2, score=5)
        
        self.assertEqual(recipe.get_average_personal_rating(), 4.5)
    
    def test_recipe_validation_empty_title(self):
        """Test that empty title is not allowed."""
        recipe = Recipe(title='   ', instructions='Test', created_by=self.user)
        with self.assertRaises(ValidationError):
            recipe.save()


class RecipeIngredientModelTest(TestCase):
    """Test RecipeIngredient model."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user('testuser', 'test@test.com', 'password')
        self.author = Author.objects.create(first_name='Test', last_name='Author')
        self.recipe = Recipe.objects.create(
            title='Test Recipe',
            instructions='Test',
            created_by=self.user
        )
        self.recipe.authors.add(self.author)
        self.ingredient = Ingredient.objects.create(name='flour')
    
    def test_recipe_ingredient_with_chinese_quantity(self):
        """Test ingredient with Chinese quantity."""
        ri = RecipeIngredient.objects.create(
            recipe=self.recipe,
            ingredient=self.ingredient,
            quantity='两杯',
            notes='过筛'
        )
        self.assertEqual(ri.quantity, '两杯')
        self.assertEqual(ri.notes, '过筛')
    
    def test_recipe_ingredient_with_arabic_quantity(self):
        """Test ingredient with Arabic quantity."""
        ri = RecipeIngredient.objects.create(
            recipe=self.recipe,
            ingredient=self.ingredient,
            quantity='كوبان',
            notes='منخول'
        )
        self.assertEqual(ri.quantity, 'كوبان')
    
    def test_recipe_ingredient_ordering(self):
        """Test ingredient ordering."""
        ri1 = RecipeIngredient.objects.create(
            recipe=self.recipe,
            ingredient=self.ingredient,
            quantity='1 cup',
            order=1
        )
        
        ingredient2 = Ingredient.objects.create(name='sugar')
        ri2 = RecipeIngredient.objects.create(
            recipe=self.recipe,
            ingredient=ingredient2,
            quantity='2 cups',
            order=0
        )
        
        ingredients = RecipeIngredient.objects.filter(recipe=self.recipe).order_by('order')
        self.assertEqual(list(ingredients), [ri2, ri1])


class RatingModelTest(TestCase):
    """Test Rating models with edge cases."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user('testuser', 'test@test.com', 'password')
        self.author = Author.objects.create(first_name='Test', last_name='Author')
        self.recipe = Recipe.objects.create(
            title='Test Recipe',
            instructions='Test',
            created_by=self.user
        )
        self.recipe.authors.add(self.author)
    
    def test_rating_min_max_values(self):
        """Test rating with minimum and maximum values."""
        # Test minimum rating
        rating1 = PublishedRating.objects.create(
            recipe=self.recipe,
            source='Test Source',
            score=MIN_RATING
        )
        self.assertEqual(rating1.score, MIN_RATING)
        
        # Test maximum rating
        rating2 = PublishedRating.objects.create(
            recipe=self.recipe,
            source='Test Source 2',
            score=MAX_RATING
        )
        self.assertEqual(rating2.score, MAX_RATING)
    
    def test_personal_rating_uniqueness(self):
        """Test that user can only rate a recipe once."""
        PersonalRating.objects.create(
            recipe=self.recipe,
            user=self.user,
            score=5
        )
        
        # Trying to create another rating should fail
        with self.assertRaises(Exception):  # IntegrityError
            PersonalRating.objects.create(
                recipe=self.recipe,
                user=self.user,
                score=3
            )
    
    def test_personal_rating_with_chinese_notes(self):
        """Test personal rating with Chinese notes."""
        rating = PersonalRating.objects.create(
            recipe=self.recipe,
            user=self.user,
            score=5,
            notes='非常好吃！我很喜欢这个食谱。'
        )
        self.assertEqual(rating.notes, '非常好吃！我很喜欢这个食谱。')
    
    def test_published_rating_with_arabic_review(self):
        """Test published rating with Arabic review."""
        rating = PublishedRating.objects.create(
            recipe=self.recipe,
            source='مصدر عربي',
            score=4,
            review_text='وصفة رائعة وسهلة التحضير'
        )
        self.assertEqual(rating.review_text, 'وصفة رائعة وسهلة التحضير')


class RecipeURLModelTest(TestCase):
    """Test RecipeURL model."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user('testuser', 'test@test.com', 'password')
        self.author = Author.objects.create(first_name='Test', last_name='Author')
        self.recipe = Recipe.objects.create(
            title='Test Recipe',
            instructions='Test',
            created_by=self.user
        )
        self.recipe.authors.add(self.author)
    
    def test_recipe_url_with_very_long_url(self):
        """Test with very long URL."""
        long_url = 'https://example.com/' + 'a' * 1900
        url = RecipeURL.objects.create(
            recipe=self.recipe,
            url=long_url,
            description='Test URL'
        )
        self.assertEqual(url.url, long_url)
    
    def test_recipe_url_with_chinese_description(self):
        """Test URL with Chinese description."""
        url = RecipeURL.objects.create(
            recipe=self.recipe,
            url='https://example.cn/recipe',
            description='中文食谱链接'
        )
        self.assertEqual(url.description, '中文食谱链接')


class ViewsTest(TestCase):
    """Test views and user interactions."""
    
    def setUp(self):
        """Set up test client and data."""
        self.client = Client()
        self.user = User.objects.create_user('testuser', 'test@test.com', 'testpass123')
        self.author = Author.objects.create(first_name='Test', last_name='Author')
        self.genre = Genre.objects.create(name='Test Genre')
        self.ingredient = Ingredient.objects.create(name='test ingredient')
    
    def test_home_page(self):
        """Test home page loads correctly."""
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'RecipeDB')
    
    def test_recipe_list_page(self):
        """Test recipe list page."""
        response = self.client.get(reverse('recipe_list'))
        self.assertEqual(response.status_code, 200)
    
    def test_login_view(self):
        """Test user login."""
        response = self.client.post(reverse('login'), {
            'username': 'testuser',
            'password': 'testpass123'
        })
        self.assertEqual(response.status_code, 302)  # Redirect after login
    
    def test_signup_view(self):
        """Test user registration."""
        response = self.client.post(reverse('signup'), {
            'username': 'newuser',
            'email': 'new@test.com',
            'password1': 'TestPass123!',
            'password2': 'TestPass123!'
        })
        self.assertEqual(response.status_code, 302)  # Redirect after signup
        self.assertTrue(User.objects.filter(username='newuser').exists())
    
    def test_recipe_create_requires_login(self):
        """Test that recipe creation requires login."""
        response = self.client.get(reverse('recipe_create'))
        self.assertEqual(response.status_code, 302)  # Redirect to login
    
    def test_recipe_detail_page(self):
        """Test recipe detail page."""
        recipe = Recipe.objects.create(
            title='Test Recipe',
            instructions='Test instructions',
            created_by=self.user
        )
        recipe.authors.add(self.author)
        
        response = self.client.get(reverse('recipe_detail', args=[recipe.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Test Recipe')
    
    def test_recipe_search_with_chinese(self):
        """Test recipe search with Chinese query."""
        recipe = Recipe.objects.create(
            title='北京烤鸭',
            instructions='传统北京烤鸭的做法',
            created_by=self.user
        )
        recipe.authors.add(self.author)
        
        response = self.client.get(reverse('recipe_list'), {'query': '北京'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '北京烤鸭')
    
    def test_recipe_search_with_arabic(self):
        """Test recipe search with Arabic query."""
        recipe = Recipe.objects.create(
            title='كبسة',
            instructions='طريقة عمل الكبسة',
            created_by=self.user
        )
        recipe.authors.add(self.author)
        
        response = self.client.get(reverse('recipe_list'), {'query': 'كبسة'})
        self.assertEqual(response.status_code, 200)
    
    def test_rate_recipe_requires_login(self):
        """Test that rating requires login."""
        recipe = Recipe.objects.create(
            title='Test Recipe',
            instructions='Test',
            created_by=self.user
        )
        recipe.authors.add(self.author)
        
        response = self.client.post(reverse('rate_recipe', args=[recipe.pk]), {
            'score': 5,
            'notes': 'Great!'
        })
        self.assertEqual(response.status_code, 302)  # Redirect to login


class LargeNumberTest(TestCase):
    """Test with very large and very small numbers."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user('testuser', 'test@test.com', 'password')
        self.author = Author.objects.create(first_name='Test', last_name='Author')
    
    def test_very_large_positive_number(self):
        """Test with very large positive numbers in quantity."""
        recipe = Recipe.objects.create(
            title='Test Recipe',
            instructions='Test',
            created_by=self.user
        )
        recipe.authors.add(self.author)
        
        ingredient = Ingredient.objects.create(name='flour')
        ri = RecipeIngredient.objects.create(
            recipe=recipe,
            ingredient=ingredient,
            quantity=f'{sys.maxsize} grams'
        )
        self.assertIn(str(sys.maxsize), ri.quantity)
    
    def test_very_small_decimal_number(self):
        """Test with very small decimal numbers."""
        recipe = Recipe.objects.create(
            title='Test Recipe',
            instructions='Test',
            ocr_confidence=0.0000001,
            created_by=self.user
        )
        recipe.authors.add(self.author)
        self.assertLess(recipe.ocr_confidence, 0.001)
    
    def test_negative_numbers_in_text(self):
        """Test with negative numbers in text fields."""
        recipe = Recipe.objects.create(
            title='Test Recipe',
            instructions='Cool to -20°C',
            created_by=self.user
        )
        recipe.authors.add(self.author)
        self.assertIn('-20', recipe.instructions)


class ErrorHandlingTest(TestCase):
    """Test error handling for database and file operations."""
    
    def test_duplicate_key_error(self):
        """Test handling of duplicate key errors."""
        Genre.objects.create(name='Italian')
        
        # Attempting to create duplicate should raise error
        with self.assertRaises(Exception):
            Genre.objects.create(name='Italian')
    
    def test_foreign_key_constraint(self):
        """Test foreign key constraints."""
        user = User.objects.create_user('testuser', 'test@test.com', 'password')
        author = Author.objects.create(first_name='Test', last_name='Author')
        recipe = Recipe.objects.create(
            title='Test',
            instructions='Test',
            created_by=user
        )
        recipe.authors.add(author)
        
        # Recipe should exist
        self.assertTrue(Recipe.objects.filter(pk=recipe.pk).exists())
    
    def test_missing_required_field(self):
        """Test that missing required fields raise errors."""
        with self.assertRaises(Exception):
            Recipe.objects.create(instructions='Test only')  # Missing title


class DecimaNumberTest(TestCase):
    """Test decimal number handling."""
    
    def setUp(self):
        """Set up test data."""
        self.user = User.objects.create_user('testuser', 'test@test.com', 'password')
        self.author = Author.objects.create(first_name='Test', last_name='Author')
    
    def test_decimal_ocr_confidence(self):
        """Test OCR confidence with decimal values."""
        test_values = [0.1, 0.25, 0.333333, 0.5, 0.666666, 0.75, 0.9, 0.99999]
        
        for i, value in enumerate(test_values):
            recipe = Recipe.objects.create(
                title=f'Test Recipe {i}',
                instructions='Test',
                ocr_confidence=value,
                created_by=self.user
            )
            recipe.authors.add(self.author)
            self.assertAlmostEqual(recipe.ocr_confidence, value, places=5)


# ============= Text-Based Ingredient Parsing Tests =============

class SaveIngredientsFromTextTest(TestCase):
    """Test _save_ingredients_from_text helper function."""

    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@test.com', 'password')
        self.recipe = Recipe.objects.create(
            title='Test Recipe', instructions='Test', created_by=self.user
        )

    def test_basic_quantity_name_format(self):
        """Test standard 'quantity - name' lines."""
        text = "2 cups - flour\n1 tsp - salt\n3 - eggs"
        _save_ingredients_from_text(self.recipe, text)
        ings = RecipeIngredient.objects.filter(recipe=self.recipe).order_by('order')
        self.assertEqual(ings.count(), 3)
        self.assertEqual(ings[0].quantity, '2 cups')
        self.assertEqual(ings[0].ingredient.name, 'flour')
        self.assertEqual(ings[2].ingredient.name, 'eggs')

    def test_ingredient_with_notes_in_parentheses(self):
        """Test parsing notes in parentheses at end."""
        text = "500g - chicken breast (boneless, skinless)"
        _save_ingredients_from_text(self.recipe, text)
        ri = RecipeIngredient.objects.get(recipe=self.recipe)
        self.assertEqual(ri.notes, 'boneless, skinless')
        self.assertEqual(ri.quantity, '500g')
        self.assertEqual(ri.ingredient.name, 'chicken breast')

    def test_chinese_ingredients(self):
        """Test parsing Chinese ingredient text."""
        text = "两杯 - 面粉\n一勺 - 酱油 (老抽)"
        _save_ingredients_from_text(self.recipe, text)
        ings = RecipeIngredient.objects.filter(recipe=self.recipe).order_by('order')
        self.assertEqual(ings.count(), 2)
        self.assertEqual(ings[0].ingredient.name, '面粉')
        self.assertEqual(ings[1].notes, '老抽')

    def test_arabic_ingredients(self):
        """Test parsing Arabic ingredient text."""
        text = "كوبان - دقيق\nملعقة - ملح"
        _save_ingredients_from_text(self.recipe, text)
        ings = RecipeIngredient.objects.filter(recipe=self.recipe).order_by('order')
        self.assertEqual(ings.count(), 2)
        self.assertEqual(ings[0].ingredient.name, 'دقيق')

    def test_empty_text(self):
        """Test empty/whitespace-only text clears ingredients."""
        # First add some
        _save_ingredients_from_text(self.recipe, "1 - flour")
        self.assertEqual(RecipeIngredient.objects.filter(recipe=self.recipe).count(), 1)
        # Now clear
        _save_ingredients_from_text(self.recipe, "   ")
        self.assertEqual(RecipeIngredient.objects.filter(recipe=self.recipe).count(), 0)

    def test_none_text(self):
        """Test None text clears ingredients."""
        _save_ingredients_from_text(self.recipe, None)
        self.assertEqual(RecipeIngredient.objects.filter(recipe=self.recipe).count(), 0)

    def test_name_only_no_dash(self):
        """Test ingredient line with no separator defaults to name only."""
        text = "salt"
        _save_ingredients_from_text(self.recipe, text)
        ri = RecipeIngredient.objects.get(recipe=self.recipe)
        self.assertEqual(ri.ingredient.name, 'salt')
        self.assertEqual(ri.quantity, '')

    def test_ingredient_name_lowercased(self):
        """Test ingredient names are lowercased."""
        text = "2 cups - FLOUR"
        _save_ingredients_from_text(self.recipe, text)
        ri = RecipeIngredient.objects.get(recipe=self.recipe)
        self.assertEqual(ri.ingredient.name, 'flour')

    def test_ordering_preserved(self):
        """Test ingredient order matches line order."""
        text = "a\nb\nc\nd"
        _save_ingredients_from_text(self.recipe, text)
        ings = RecipeIngredient.objects.filter(recipe=self.recipe).order_by('order')
        self.assertEqual([ri.order for ri in ings], [0, 1, 2, 3])

    def test_very_long_ingredient_name_truncated(self):
        """Test very long ingredient names are truncated to MAX_NAME_LENGTH."""
        long_name = 'x' * 500
        text = f"1 - {long_name}"
        _save_ingredients_from_text(self.recipe, text)
        ri = RecipeIngredient.objects.get(recipe=self.recipe)
        self.assertLessEqual(len(ri.ingredient.name), MAX_NAME_LENGTH)

    def test_blank_lines_skipped(self):
        """Test blank lines between ingredients are skipped."""
        text = "1 - flour\n\n\n2 - sugar\n  \n3 - salt"
        _save_ingredients_from_text(self.recipe, text)
        self.assertEqual(RecipeIngredient.objects.filter(recipe=self.recipe).count(), 3)


# ============= Text-Based Author Parsing Tests =============

class SaveAuthorsFromTextTest(TestCase):
    """Test _save_authors_from_text helper function."""

    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@test.com', 'password')
        self.recipe = Recipe.objects.create(
            title='Test Recipe', instructions='Test', created_by=self.user
        )

    def test_single_word_author_creates_publisher(self):
        """Test single-word name creates publisher_name author."""
        _save_authors_from_text(self.recipe, "Tasty")
        author = self.recipe.authors.first()
        self.assertEqual(author.publisher_name, 'Tasty')

    def test_two_word_author_splits_first_last(self):
        """Test two-word name splits into first/last."""
        _save_authors_from_text(self.recipe, "Julia Child")
        author = self.recipe.authors.first()
        self.assertEqual(author.first_name, 'Julia')
        self.assertEqual(author.last_name, 'Child')

    def test_chinese_author(self):
        """Test Chinese author name."""
        _save_authors_from_text(self.recipe, "张 伟")
        author = self.recipe.authors.first()
        self.assertIsNotNone(author)
        self.assertEqual(author.first_name, '张')
        self.assertEqual(author.last_name, '伟')

    def test_arabic_author(self):
        """Test Arabic author name as publisher."""
        _save_authors_from_text(self.recipe, "محمد")
        author = self.recipe.authors.first()
        self.assertEqual(author.publisher_name, 'محمد')

    def test_multiple_authors(self):
        """Test multiple authors on separate lines."""
        text = "Julia Child\nJacques Pépin\nBBC Good Food"
        _save_authors_from_text(self.recipe, text)
        self.assertEqual(self.recipe.authors.count(), 3)

    def test_empty_text_clears_authors(self):
        """Test empty text clears all authors."""
        author = Author.objects.create(publisher_name='Test')
        self.recipe.authors.add(author)
        _save_authors_from_text(self.recipe, "")
        self.assertEqual(self.recipe.authors.count(), 0)

    def test_existing_author_reused(self):
        """Test existing author is reused, not duplicated."""
        Author.objects.create(first_name='Julia', last_name='Child')
        _save_authors_from_text(self.recipe, "Julia Child")
        self.assertEqual(Author.objects.filter(first_name='Julia', last_name='Child').count(), 1)
        self.assertEqual(self.recipe.authors.count(), 1)


# ============= Text-Based Genre Parsing Tests =============

class SaveGenresFromTextTest(TestCase):
    """Test _save_genres_from_text helper function."""

    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@test.com', 'password')
        self.recipe = Recipe.objects.create(
            title='Test Recipe', instructions='Test', created_by=self.user
        )

    def test_single_genre(self):
        """Test adding a single genre."""
        _save_genres_from_text(self.recipe, "Italian")
        self.assertEqual(self.recipe.genres.count(), 1)
        self.assertEqual(self.recipe.genres.first().name, 'Italian')

    def test_multiple_genres(self):
        """Test adding multiple genres on separate lines."""
        text = "Italian\nDessert\nMain Course"
        _save_genres_from_text(self.recipe, text)
        self.assertEqual(self.recipe.genres.count(), 3)

    def test_case_insensitive_matching(self):
        """Test genre matching is case-insensitive."""
        Genre.objects.create(name='Italian')
        _save_genres_from_text(self.recipe, "italian")
        self.assertEqual(Genre.objects.filter(name__iexact='italian').count(), 1)
        self.assertEqual(self.recipe.genres.count(), 1)

    def test_chinese_genre(self):
        """Test Chinese genre text."""
        _save_genres_from_text(self.recipe, "中式料理")
        self.assertEqual(self.recipe.genres.first().name, '中式料理')

    def test_arabic_genre(self):
        """Test Arabic genre text."""
        _save_genres_from_text(self.recipe, "المطبخ العربي")
        self.assertEqual(self.recipe.genres.first().name, 'المطبخ العربي')

    def test_empty_text_clears_genres(self):
        """Test empty text clears all genres."""
        genre = Genre.objects.create(name='Test')
        self.recipe.genres.add(genre)
        _save_genres_from_text(self.recipe, "")
        self.assertEqual(self.recipe.genres.count(), 0)


# ============= Source URL Tests =============

class SaveSourceURLTest(TestCase):
    """Test _save_source_url helper function."""

    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@test.com', 'password')
        self.recipe = Recipe.objects.create(
            title='Test Recipe', instructions='Test', created_by=self.user
        )

    def test_creates_primary_url(self):
        """Test creates a primary URL entry."""
        _save_source_url(self.recipe, "https://example.com/recipe")
        url = RecipeURL.objects.get(recipe=self.recipe)
        self.assertEqual(url.url, "https://example.com/recipe")
        self.assertTrue(url.is_primary)

    def test_updates_existing_primary_url(self):
        """Test updates existing primary URL rather than creating duplicate."""
        _save_source_url(self.recipe, "https://old.com")
        _save_source_url(self.recipe, "https://new.com")
        self.assertEqual(RecipeURL.objects.filter(recipe=self.recipe, is_primary=True).count(), 1)
        self.assertEqual(
            RecipeURL.objects.get(recipe=self.recipe, is_primary=True).url,
            "https://new.com"
        )

    def test_empty_url_does_nothing(self):
        """Test empty URL does not create entry."""
        _save_source_url(self.recipe, "")
        self.assertEqual(RecipeURL.objects.filter(recipe=self.recipe).count(), 0)

    def test_none_url_does_nothing(self):
        """Test None URL does not create entry."""
        _save_source_url(self.recipe, None)
        self.assertEqual(RecipeURL.objects.filter(recipe=self.recipe).count(), 0)

    def test_very_long_url(self):
        """Test with a very long URL."""
        long_url = 'https://example.com/' + 'a' * 1900
        _save_source_url(self.recipe, long_url)
        url = RecipeURL.objects.get(recipe=self.recipe)
        self.assertEqual(url.url, long_url)


# ============= Background File Deletion Tests =============

class BackgroundDeleteFileTest(TestCase):
    """Test _background_delete_file helper function."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_deletes_existing_file(self):
        """Test that a file is eventually deleted by background thread."""
        test_file = Path(self.temp_dir) / 'test.txt'
        test_file.write_text('test content')
        self.assertTrue(test_file.exists())

        _background_delete_file(test_file)
        # Wait for background thread to finish
        time.sleep(3.0)
        self.assertFalse(test_file.exists())

    def test_nonexistent_file_no_error(self):
        """Test that deleting a non-existent file does not raise."""
        fake_path = Path(self.temp_dir) / 'nonexistent.txt'
        # Should not raise any exception
        _background_delete_file(fake_path)
        time.sleep(1.0)

    def test_file_with_unicode_name(self):
        """Test deleting a file with Unicode (Chinese/Arabic) characters in name."""
        test_file = Path(self.temp_dir) / '测试文件_اختبار.txt'
        test_file.write_text('unicode content')
        self.assertTrue(test_file.exists())

        _background_delete_file(test_file)
        time.sleep(3.0)
        self.assertFalse(test_file.exists())


# ============= OCR Extract Recipe Tests =============

class ExtractRecipeFromTextTest(TestCase):
    """Test extract_recipe_from_text function."""

    def test_first_line_is_title(self):
        """Test first line is used as recipe title."""
        text = "Chocolate Chip Cookies\nMix ingredients\nBake at 350F"
        result = extract_recipe_from_text(text)
        self.assertEqual(result['title'], 'Chocolate Chip Cookies')

    def test_ingredient_keywords_detected(self):
        """Test lines with measurement keywords become ingredients."""
        text = "My Recipe\n2 cup flour\n1 tablespoon sugar\nBake at 350F"
        result = extract_recipe_from_text(text)
        self.assertGreaterEqual(len(result['ingredients']), 1)

    def test_empty_text_returns_empty_title(self):
        """Test empty text returns empty title."""
        result = extract_recipe_from_text("")
        self.assertEqual(result['title'], '')
        self.assertEqual(result['ingredients'], [])

    def test_chinese_text(self):
        """Test Chinese text extraction."""
        text = "宫保鸡丁\n先炒鸡肉\n然后加入花生"
        result = extract_recipe_from_text(text)
        self.assertEqual(result['title'], '宫保鸡丁')

    def test_arabic_text(self):
        """Test Arabic text extraction."""
        text = "المندي\nطريقة تحضير المندي"
        result = extract_recipe_from_text(text)
        self.assertEqual(result['title'], 'المندي')

    def test_instructions_collected(self):
        """Test non-ingredient lines become instructions."""
        text = "My Recipe\nPreheat oven\nMix together\nServe warm"
        result = extract_recipe_from_text(text)
        self.assertIn('Preheat oven', result['instructions'])


# ============= Recipe Create/Edit View Tests =============

class RecipeCreateEditViewTest(TestCase):
    """Test recipe creation and editing with text-based fields."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user('testuser', 'test@test.com', 'testpass123')
        self.client.login(username='testuser', password='testpass123')

    def test_create_recipe_with_ingredients_text(self):
        """Test creating recipe with text-based ingredients."""
        response = self.client.post(reverse('recipe_create'), {
            'title': 'Test Recipe',
            'instructions': 'Mix and bake',
            'ingredients_text': '2 cups - flour\n1 tsp - salt',
            'authors_text': '',
            'genres_text': '',
            'source_url': '',
        })
        self.assertEqual(response.status_code, 302)  # Redirect on success
        recipe = Recipe.objects.get(title='Test Recipe')
        ings = RecipeIngredient.objects.filter(recipe=recipe).order_by('order')
        self.assertEqual(ings.count(), 2)
        self.assertEqual(ings[0].ingredient.name, 'flour')

    def test_create_recipe_with_all_text_fields(self):
        """Test creating recipe with all text-based fields populated."""
        response = self.client.post(reverse('recipe_create'), {
            'title': 'Full Recipe',
            'instructions': 'Step 1, Step 2',
            'ingredients_text': '1 - sugar',
            'authors_text': 'Test Author',
            'genres_text': 'Dessert',
            'source_url': 'https://example.com',
        })
        self.assertEqual(response.status_code, 302)
        recipe = Recipe.objects.get(title='Full Recipe')
        self.assertEqual(recipe.authors.count(), 1)
        self.assertEqual(recipe.genres.count(), 1)
        self.assertTrue(
            RecipeURL.objects.filter(recipe=recipe, is_primary=True).exists()
        )

    def test_create_recipe_with_chinese_content(self):
        """Test creating recipe with Chinese text in all fields."""
        response = self.client.post(reverse('recipe_create'), {
            'title': '宫保鸡丁',
            'instructions': '先炒鸡肉，然后加入花生和辣椒',
            'ingredients_text': '两杯 - 鸡肉\n一勺 - 花生',
            'authors_text': '张 伟',
            'genres_text': '中式料理',
            'source_url': '',
        })
        self.assertEqual(response.status_code, 302)
        recipe = Recipe.objects.get(title='宫保鸡丁')
        self.assertEqual(recipe.authors.count(), 1)
        self.assertEqual(recipe.genres.first().name, '中式料理')

    def test_create_recipe_with_arabic_content(self):
        """Test creating recipe with Arabic text in all fields."""
        response = self.client.post(reverse('recipe_create'), {
            'title': 'المندي',
            'instructions': 'طريقة تحضير المندي اليمني',
            'ingredients_text': 'كوبان - دقيق',
            'authors_text': 'محمد',
            'genres_text': 'المطبخ العربي',
            'source_url': '',
        })
        self.assertEqual(response.status_code, 302)
        recipe = Recipe.objects.get(title='المندي')
        self.assertEqual(recipe.genres.first().name, 'المطبخ العربي')

    def test_edit_recipe_updates_ingredients(self):
        """Test editing recipe replaces old ingredients with new ones."""
        recipe = Recipe.objects.create(
            title='Edit Test', instructions='Test', created_by=self.user
        )
        _save_ingredients_from_text(recipe, "1 - old ingredient")
        self.assertEqual(RecipeIngredient.objects.filter(recipe=recipe).count(), 1)

        response = self.client.post(reverse('recipe_update', args=[recipe.pk]), {
            'title': 'Edit Test',
            'instructions': 'Updated',
            'ingredients_text': '1 - new ingredient\n2 - another',
            'authors_text': '',
            'genres_text': '',
            'source_url': '',
        })
        self.assertEqual(response.status_code, 302)
        ings = RecipeIngredient.objects.filter(recipe=recipe)
        self.assertEqual(ings.count(), 2)
        names = [ri.ingredient.name for ri in ings]
        self.assertIn('new ingredient', names)
        self.assertNotIn('old ingredient', names)


# ============= OCR Upload View Tests =============

class OCRUploadViewTest(TestCase):
    """Test OCR upload view."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user('testuser', 'test@test.com', 'testpass123')

    def test_ocr_upload_requires_login(self):
        """Test that OCR upload requires authentication."""
        response = self.client.get(reverse('ocr_upload'))
        self.assertEqual(response.status_code, 302)  # Redirect to login

    def test_ocr_upload_page_loads(self):
        """Test OCR upload page loads for logged-in user."""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.get(reverse('ocr_upload'))
        self.assertEqual(response.status_code, 200)

    def test_ocr_upload_invalid_no_file(self):
        """Test OCR upload without file shows error."""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.post(reverse('ocr_upload'), {})
        self.assertEqual(response.status_code, 200)  # Re-renders form with errors


# ============= Rating View Tests =============

class RateRecipeViewTest(TestCase):
    """Test recipe rating view."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user('testuser', 'test@test.com', 'testpass123')
        self.recipe = Recipe.objects.create(
            title='Test Recipe', instructions='Test', created_by=self.user
        )

    def test_rate_recipe_creates_rating(self):
        """Test that rating a recipe creates a PersonalRating."""
        self.client.login(username='testuser', password='testpass123')
        response = self.client.post(reverse('rate_recipe', args=[self.recipe.pk]), {
            'score': 4,
            'notes': 'Great recipe!'
        })
        self.assertEqual(response.status_code, 302)
        rating = PersonalRating.objects.get(recipe=self.recipe, user=self.user)
        self.assertEqual(rating.score, 4)
        self.assertEqual(rating.notes, 'Great recipe!')

    def test_rate_recipe_updates_existing(self):
        """Test that re-rating updates the existing PersonalRating."""
        self.client.login(username='testuser', password='testpass123')
        PersonalRating.objects.create(
            recipe=self.recipe, user=self.user, score=3, notes='Good'
        )
        self.client.post(reverse('rate_recipe', args=[self.recipe.pk]), {
            'score': 5,
            'notes': 'Even better!'
        })
        rating = PersonalRating.objects.get(recipe=self.recipe, user=self.user)
        self.assertEqual(rating.score, 5)

    def test_rate_recipe_with_chinese_notes(self):
        """Test rating with Chinese notes."""
        self.client.login(username='testuser', password='testpass123')
        self.client.post(reverse('rate_recipe', args=[self.recipe.pk]), {
            'score': 5,
            'notes': '非常好吃！推荐给大家。'
        })
        rating = PersonalRating.objects.get(recipe=self.recipe, user=self.user)
        self.assertEqual(rating.notes, '非常好吃！推荐给大家。')

    def test_rate_recipe_with_arabic_notes(self):
        """Test rating with Arabic notes."""
        self.client.login(username='testuser', password='testpass123')
        self.client.post(reverse('rate_recipe', args=[self.recipe.pk]), {
            'score': 4,
            'notes': 'وصفة رائعة وسهلة التحضير'
        })
        rating = PersonalRating.objects.get(recipe=self.recipe, user=self.user)
        self.assertEqual(rating.notes, 'وصفة رائعة وسهلة التحضير')


# ============= File Management Tests =============

class FileManagementTest(TestCase):
    """Test file management for OCR uploads (ERR_ rename, delete on success)."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_err_rename_copy_and_delete(self):
        """Test the ERR_ rename flow: copy then background delete."""
        src = Path(self.temp_dir) / 'recipe.png'
        src.write_bytes(b'FAKE PNG DATA')
        err = Path(self.temp_dir) / 'ERR_recipe.png'

        # Simulate the OCR upload flow: copy then background delete
        shutil.copy2(str(src), str(err))
        self.assertTrue(err.exists())

        _background_delete_file(src)
        time.sleep(3.0)
        self.assertFalse(src.exists())
        self.assertTrue(err.exists())

    def test_err_rename_counter_avoids_overwrite(self):
        """Test ERR_ counter increment when file already exists."""
        images_folder = Path(self.temp_dir)
        src = images_folder / 'test.png'
        src.write_bytes(b'data')
        # Pre-create ERR files
        (images_folder / 'ERR_test.png').write_bytes(b'old')

        err_name = f"ERR_{src.name}"
        err_path = images_folder / err_name
        counter = 1
        while err_path.exists():
            stem = src.stem
            suffix = src.suffix
            err_name = f"ERR_{stem}_{counter}{suffix}"
            err_path = images_folder / err_name
            counter += 1

        shutil.copy2(str(src), str(err_path))
        self.assertTrue(err_path.exists())
        self.assertEqual(err_path.name, 'ERR_test_1.png')

    def test_delete_file_with_special_characters(self):
        """Test deleting a file with Finnish/special characters in name."""
        test_file = Path(self.temp_dir) / 'Näyttökuva 2026-02-17.png'
        test_file.write_bytes(b'test data')
        self.assertTrue(test_file.exists())

        _background_delete_file(test_file)
        time.sleep(3.0)
        self.assertFalse(test_file.exists())

    def test_success_flow_deletes_original(self):
        """Test success flow: original is deleted from IMAGES folder."""
        src = Path(self.temp_dir) / 'good_recipe.png'
        src.write_bytes(b'image data')

        _background_delete_file(src)
        time.sleep(3.0)
        self.assertFalse(src.exists())


# ============= RecipeForm Tests =============

class RecipeFormTest(TestCase):
    """Test RecipeForm initialization and pre-population."""

    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@test.com', 'password')
        self.recipe = Recipe.objects.create(
            title='Test Recipe', instructions='Test instructions', created_by=self.user
        )

    def test_form_prepopulates_ingredients(self):
        """Test form pre-populates ingredients_text from existing data."""
        from .forms import RecipeForm
        ingredient = Ingredient.objects.create(name='flour')
        RecipeIngredient.objects.create(
            recipe=self.recipe, ingredient=ingredient,
            quantity='2 cups', order=0
        )
        form = RecipeForm(instance=self.recipe)
        self.assertIn('2 cups - flour', form.fields['ingredients_text'].initial)

    def test_form_prepopulates_authors(self):
        """Test form pre-populates authors_text from existing data."""
        from .forms import RecipeForm
        author = Author.objects.create(first_name='Julia', last_name='Child')
        self.recipe.authors.add(author)
        form = RecipeForm(instance=self.recipe)
        self.assertIn('Julia Child', form.fields['authors_text'].initial)

    def test_form_prepopulates_genres(self):
        """Test form pre-populates genres_text from existing data."""
        from .forms import RecipeForm
        genre = Genre.objects.create(name='Italian')
        self.recipe.genres.add(genre)
        form = RecipeForm(instance=self.recipe)
        self.assertIn('Italian', form.fields['genres_text'].initial)

    def test_form_prepopulates_source_url(self):
        """Test form pre-populates source_url from existing RecipeURL."""
        from .forms import RecipeForm
        RecipeURL.objects.create(
            recipe=self.recipe, url='https://example.com', is_primary=True
        )
        form = RecipeForm(instance=self.recipe)
        self.assertEqual(form.fields['source_url'].initial, 'https://example.com')

    def test_new_form_has_empty_text_fields(self):
        """Test new form (no instance) has empty text fields."""
        from .forms import RecipeForm
        form = RecipeForm()
        self.assertIsNone(form.fields['ingredients_text'].initial)
        self.assertIsNone(form.fields['authors_text'].initial)


class RecipePermissionTest(TestCase):
    """Test permission-based access control for recipe edit/delete."""

    def setUp(self):
        """Set up test users and recipe."""
        from django.contrib.auth.models import Group, Permission
        from django.contrib.contenttypes.models import ContentType

        self.client = Client()
        self.owner = User.objects.create_user('owner', 'owner@test.com', 'pass123')
        self.other_user = User.objects.create_user('other', 'other@test.com', 'pass123')
        self.permitted_user = User.objects.create_user('permitted', 'perm@test.com', 'pass123')

        self.recipe = Recipe.objects.create(
            title='Owner Recipe',
            instructions='Test instructions',
            created_by=self.owner
        )

        # Grant delete + change permission to permitted_user via group
        ct = ContentType.objects.get_for_model(Recipe)
        delete_perm = Permission.objects.get(codename='delete_recipe', content_type=ct)
        change_perm = Permission.objects.get(codename='change_recipe', content_type=ct)
        group = Group.objects.create(name='Editors')
        group.permissions.add(delete_perm, change_perm)
        self.permitted_user.groups.add(group)

    def test_owner_can_delete(self):
        """Test recipe owner can delete their own recipe."""
        self.client.login(username='owner', password='pass123')
        response = self.client.post(reverse('recipe_delete', args=[self.recipe.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Recipe.objects.filter(pk=self.recipe.pk).exists())

    def test_other_user_cannot_delete(self):
        """Test non-owner without permission cannot delete recipe."""
        self.client.login(username='other', password='pass123')
        response = self.client.post(reverse('recipe_delete', args=[self.recipe.pk]))
        # Should redirect back (permission denied), recipe still exists
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Recipe.objects.filter(pk=self.recipe.pk).exists())

    def test_permitted_user_can_delete(self):
        """Test user with group permission can delete recipe."""
        self.client.login(username='permitted', password='pass123')
        # Refresh user to pick up group permissions
        self.permitted_user = User.objects.get(pk=self.permitted_user.pk)
        response = self.client.post(reverse('recipe_delete', args=[self.recipe.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Recipe.objects.filter(pk=self.recipe.pk).exists())

    def test_owner_can_edit(self):
        """Test recipe owner can access edit page."""
        self.client.login(username='owner', password='pass123')
        response = self.client.get(reverse('recipe_update', args=[self.recipe.pk]))
        self.assertEqual(response.status_code, 200)

    def test_other_user_cannot_edit(self):
        """Test non-owner without permission cannot edit recipe."""
        self.client.login(username='other', password='pass123')
        response = self.client.get(reverse('recipe_update', args=[self.recipe.pk]))
        # Should redirect (permission denied)
        self.assertEqual(response.status_code, 302)

    def test_permitted_user_can_edit(self):
        """Test user with group permission can access edit page."""
        self.client.login(username='permitted', password='pass123')
        response = self.client.get(reverse('recipe_update', args=[self.recipe.pk]))
        self.assertEqual(response.status_code, 200)

    def test_anonymous_user_redirected_to_login(self):
        """Test anonymous user is redirected to login."""
        response = self.client.get(reverse('recipe_delete', args=[self.recipe.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_delete_button_hidden_for_non_owner(self):
        """Test Delete button not shown to non-owner without permission."""
        self.client.login(username='other', password='pass123')
        response = self.client.get(reverse('recipe_detail', args=[self.recipe.pk]))
        self.assertNotContains(response, 'btn btn-danger')

    def test_delete_button_shown_for_owner(self):
        """Test Delete button shown to recipe owner."""
        self.client.login(username='owner', password='pass123')
        response = self.client.get(reverse('recipe_detail', args=[self.recipe.pk]))
        self.assertContains(response, 'Delete')

    def test_edit_button_hidden_for_non_owner(self):
        """Test Edit button not shown to non-owner without permission."""
        self.client.login(username='other', password='pass123')
        response = self.client.get(reverse('recipe_detail', args=[self.recipe.pk]))
        self.assertNotContains(response, 'recipe_update')

    def test_chinese_user_permission_check(self):
        """Test permission check works with Chinese username."""
        cn_user = User.objects.create_user('张伟', 'zhang@test.com', 'pass123')
        self.client.login(username='张伟', password='pass123')
        response = self.client.post(reverse('recipe_delete', args=[self.recipe.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Recipe.objects.filter(pk=self.recipe.pk).exists())

    def test_arabic_user_permission_check(self):
        """Test permission check works with Arabic username."""
        ar_user = User.objects.create_user('محمد', 'mohammed@test.com', 'pass123')
        self.client.login(username='محمد', password='pass123')
        response = self.client.post(reverse('recipe_delete', args=[self.recipe.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Recipe.objects.filter(pk=self.recipe.pk).exists())


# ============= URL Extraction & Repair Tests =============

class ExtractURLsFromTextTest(TestCase):
    """Test _extract_urls_from_text with various URL formats."""

    def test_clean_url_detected(self):
        """Test standard clean URL is found."""
        text = "Visit https://www.example.com/recipe for details."
        urls = _extract_urls_from_text(text)
        self.assertIn('https://www.example.com/recipe', urls)

    def test_multiple_urls_detected(self):
        """Test multiple URLs in text are all found."""
        text = "See https://a.com and http://b.org/page?x=1 for info."
        urls = _extract_urls_from_text(text)
        self.assertGreaterEqual(len(urls), 2)

    def test_url_with_path_and_query(self):
        """Test URL with path, query, and fragment is preserved."""
        text = "Link: https://example.com/recipes/123?lang=fi&sort=new"
        urls = _extract_urls_from_text(text)
        self.assertTrue(any('example.com/recipes/123' in u for u in urls))

    def test_ocr_garbled_url_repaired(self):
        """Test OCR-garbled URL (missing ://) is repaired."""
        text = "© https /Awww.feastingathome.com/thai-coconut-soup/"
        urls = _extract_urls_from_text(text)
        self.assertTrue(
            any('feastingathome.com' in u for u in urls),
            f"Expected feastingathome.com in {urls}"
        )

    def test_ocr_garbled_url_scheme_spaces(self):
        """Test OCR artifact: spaces in scheme."""
        text = "Check http ://www.example.com/recipe"
        urls = _extract_urls_from_text(text)
        self.assertTrue(any('example.com' in u for u in urls))

    def test_www_without_scheme(self):
        """Test bare www. domain gets https:// prepended."""
        text = "Go to www.recipes.fi/page for more"
        urls = _extract_urls_from_text(text)
        self.assertTrue(any('https://www.recipes.fi' in u for u in urls))

    def test_empty_text_returns_empty(self):
        """Test empty text returns empty list."""
        self.assertEqual(_extract_urls_from_text(''), [])

    def test_none_text_returns_empty(self):
        """Test None text returns empty list."""
        self.assertEqual(_extract_urls_from_text(None), [])

    def test_no_urls_in_text(self):
        """Test text without URLs returns empty list."""
        self.assertEqual(
            _extract_urls_from_text('This is a recipe for chocolate cake.'),
            []
        )

    def test_url_trailing_punctuation_stripped(self):
        """Test trailing punctuation is stripped from URLs."""
        text = "Recipe at https://site.com/recipe."
        urls = _extract_urls_from_text(text)
        # URL should not end with period
        for u in urls:
            self.assertFalse(u.endswith('.'), f"URL ends with period: {u}")

    def test_chinese_text_with_url(self):
        """Test URL extraction from Chinese text."""
        text = "食谱链接: https://example.cn/recipe/宫保鸡丁 请查看"
        urls = _extract_urls_from_text(text)
        self.assertTrue(any('example.cn' in u for u in urls))

    def test_arabic_text_with_url(self):
        """Test URL extraction from Arabic text."""
        text = "الرابط https://example.com/المندي اطبخ"
        urls = _extract_urls_from_text(text)
        self.assertTrue(any('example.com' in u for u in urls))

    def test_very_short_urls_filtered_out(self):
        """Test that very short URL fragments are filtered out."""
        text = "http://a.b"
        urls = _extract_urls_from_text(text)
        # Should be filtered: length <= 10
        self.assertEqual(len(urls), 0)


class RepairOCRUrlTest(TestCase):
    """Test _repair_ocr_url with various OCR artifacts."""

    def test_missing_colon_slash(self):
        """Test repair of missing :// separator."""
        result = _repair_ocr_url("https //www.example.com/recipe")
        self.assertTrue(result.startswith('https://'))
        self.assertIn('example.com', result)

    def test_uppercase_a_before_www(self):
        """Test repair of OCR artifact: capital letter before www."""
        result = _repair_ocr_url("https://Awww.example.com/page")
        self.assertIn('www.example.com', result)
        self.assertNotIn('Awww', result)

    def test_spaces_in_url(self):
        """Test spaces inside URL are removed."""
        result = _repair_ocr_url("https :// www.example.com /recipe")
        self.assertNotIn(' ', result)
        self.assertIn('example.com/recipe', result)

    def test_backslash_in_scheme(self):
        """Test backslash in scheme is handled."""
        result = _repair_ocr_url("https:\\\\www.example.com\\page")
        self.assertTrue(result.startswith('https://'))

    def test_none_input(self):
        """Test None input returns None."""
        self.assertIsNone(_repair_ocr_url(None))

    def test_empty_string(self):
        """Test empty string returns None."""
        self.assertIsNone(_repair_ocr_url(''))

    def test_unrepairable_garbage(self):
        """Test truly unrepairable text returns None."""
        self.assertIsNone(_repair_ocr_url('just random text'))

    def test_leading_garbage_removed(self):
        """Test leading non-URL characters before https are removed."""
        result = _repair_ocr_url("© https://www.example.com/page")
        self.assertTrue(result.startswith('https://'))

    def test_combined_ocr_artifacts(self):
        """Test repair with multiple OCR artifacts combined."""
        result = _repair_ocr_url("https /Awww.feastingathome.com/recipe/")
        self.assertIsNotNone(result)
        self.assertIn('feastingathome.com', result)
        self.assertTrue(result.startswith('https://'))


# ============= Clean HTML Text Tests =============

class CleanHTMLTextTest(TestCase):
    """Test _clean_html_text helper."""

    def test_strips_html_tags(self):
        """Test HTML tags are removed."""
        self.assertEqual(_clean_html_text('<b>Bold</b> text'), 'Bold text')

    def test_decodes_entities(self):
        """Test common HTML entities are decoded."""
        self.assertEqual(_clean_html_text('fish &amp; chips'), 'fish & chips')
        self.assertEqual(_clean_html_text('&lt;tag&gt;'), '<tag>')

    def test_collapses_whitespace(self):
        """Test multiple whitespace is collapsed."""
        result = _clean_html_text('  hello   world  ')
        self.assertEqual(result, 'hello world')

    def test_empty_input(self):
        """Test empty input returns empty string."""
        self.assertEqual(_clean_html_text(''), '')
        self.assertEqual(_clean_html_text(None), '')

    def test_chinese_html(self):
        """Test Chinese text with HTML tags."""
        self.assertEqual(_clean_html_text('<p>你好世界</p>'), '你好世界')

    def test_arabic_html(self):
        """Test Arabic text with HTML tags."""
        self.assertEqual(_clean_html_text('<span>مرحبا بالعالم</span>'), 'مرحبا بالعالم')

    def test_nested_tags(self):
        """Test nested HTML tags stripped."""
        result = _clean_html_text('<div><p><strong>Recipe</strong></p></div>')
        self.assertEqual(result, 'Recipe')


# ============= JSON-LD Extraction Tests =============

class ExtractJsonLDRecipeTest(TestCase):
    """Test _extract_jsonld_recipe with various JSON-LD formats."""

    SAMPLE_RECIPE_JSONLD = '''
    <html><head>
    <script type="application/ld+json">
    {
        "@type": "Recipe",
        "name": "Test Recipe",
        "description": "A simple test recipe",
        "recipeIngredient": ["2 cups flour", "1 tsp salt"],
        "recipeInstructions": [
            {"@type": "HowToStep", "text": "Mix flour and salt."},
            {"@type": "HowToStep", "text": "Add water and knead."}
        ],
        "author": {"@type": "Person", "name": "Test Chef"},
        "recipeCategory": "Bread",
        "recipeCuisine": "Italian",
        "image": "https://example.com/image.jpg"
    }
    </script></head><body></body></html>
    '''

    def test_basic_recipe_extraction(self):
        """Test basic JSON-LD recipe extraction."""
        result = _extract_jsonld_recipe(self.SAMPLE_RECIPE_JSONLD)
        self.assertIsNotNone(result)
        self.assertEqual(result['title'], 'Test Recipe')
        self.assertEqual(result['description'], 'A simple test recipe')

    def test_ingredients_extracted(self):
        """Test ingredients are parsed from JSON-LD."""
        result = _extract_jsonld_recipe(self.SAMPLE_RECIPE_JSONLD)
        self.assertEqual(len(result['ingredients']), 2)
        # First ingredient: "2 cups flour" → quantity="2", name="cups flour"
        self.assertTrue(any('flour' in str(i['name']).lower() for i in result['ingredients']))

    def test_instructions_extracted(self):
        """Test instructions are parsed from HowToStep objects."""
        result = _extract_jsonld_recipe(self.SAMPLE_RECIPE_JSONLD)
        self.assertIn('Mix flour and salt', result['instructions'])
        self.assertIn('Add water and knead', result['instructions'])

    def test_author_extracted(self):
        """Test author name is extracted."""
        result = _extract_jsonld_recipe(self.SAMPLE_RECIPE_JSONLD)
        self.assertIn('Test Chef', result['authors'])

    def test_genres_extracted(self):
        """Test categories and cuisines become genres."""
        result = _extract_jsonld_recipe(self.SAMPLE_RECIPE_JSONLD)
        self.assertIn('Bread', result['genres'])
        self.assertIn('Italian', result['genres'])

    def test_image_extracted(self):
        """Test image URL is extracted."""
        result = _extract_jsonld_recipe(self.SAMPLE_RECIPE_JSONLD)
        self.assertEqual(result['image_url'], 'https://example.com/image.jpg')

    def test_no_recipe_returns_none(self):
        """Test HTML without JSON-LD returns None."""
        html = '<html><body><p>No recipe here</p></body></html>'
        self.assertIsNone(_extract_jsonld_recipe(html))

    def test_non_recipe_jsonld_skipped(self):
        """Test non-Recipe JSON-LD types are skipped."""
        html = '''
        <html><script type="application/ld+json">
        {"@type": "Article", "name": "News Article"}
        </script></html>
        '''
        self.assertIsNone(_extract_jsonld_recipe(html))

    def test_graph_format(self):
        """Test JSON-LD @graph array format."""
        html = '''
        <html><script type="application/ld+json">
        {"@graph": [
            {"@type": "WebPage", "name": "Page"},
            {"@type": "Recipe", "name": "Graph Recipe",
             "recipeIngredient": ["1 cup sugar"]}
        ]}
        </script></html>
        '''
        result = _extract_jsonld_recipe(html)
        self.assertIsNotNone(result)
        self.assertEqual(result['title'], 'Graph Recipe')

    def test_recipe_type_as_list(self):
        """Test @type specified as list ["Recipe"]."""
        html = '''
        <html><script type="application/ld+json">
        {"@type": ["Recipe"], "name": "List Type Recipe",
         "recipeIngredient": ["water"]}
        </script></html>
        '''
        result = _extract_jsonld_recipe(html)
        self.assertIsNotNone(result)
        self.assertEqual(result['title'], 'List Type Recipe')

    def test_malformed_json_skipped(self):
        """Test malformed JSON doesn't crash."""
        html = '<html><script type="application/ld+json">{not valid json</script></html>'
        result = _extract_jsonld_recipe(html)
        self.assertIsNone(result)

    def test_chinese_recipe_jsonld(self):
        """Test JSON-LD with Chinese text."""
        html = '''
        <html><script type="application/ld+json">
        {"@type": "Recipe", "name": "宫保鸡丁",
         "description": "经典川菜",
         "recipeIngredient": ["两杯 鸡肉", "一勺 花生"],
         "author": {"name": "张三"}}
        </script></html>
        '''
        result = _extract_jsonld_recipe(html)
        self.assertEqual(result['title'], '宫保鸡丁')
        self.assertIn('张三', result['authors'])

    def test_arabic_recipe_jsonld(self):
        """Test JSON-LD with Arabic text."""
        html = '''
        <html><script type="application/ld+json">
        {"@type": "Recipe", "name": "المندي",
         "description": "طبق يمني شهير",
         "recipeIngredient": ["كوبان دقيق"],
         "author": {"name": "محمد"}}
        </script></html>
        '''
        result = _extract_jsonld_recipe(html)
        self.assertEqual(result['title'], 'المندي')
        self.assertIn('محمد', result['authors'])

    def test_instructions_as_plain_strings(self):
        """Test instructions as list of plain strings."""
        html = '''
        <html><script type="application/ld+json">
        {"@type": "Recipe", "name": "Simple",
         "recipeInstructions": ["Step one.", "Step two."]}
        </script></html>
        '''
        result = _extract_jsonld_recipe(html)
        self.assertIn('Step one', result['instructions'])

    def test_instructions_as_single_string(self):
        """Test instructions as a single string."""
        html = '''
        <html><script type="application/ld+json">
        {"@type": "Recipe", "name": "Single",
         "recipeInstructions": "Mix everything together and bake."}
        </script></html>
        '''
        result = _extract_jsonld_recipe(html)
        self.assertIn('Mix everything', result['instructions'])

    def test_image_as_list(self):
        """Test image field as list of URLs."""
        html = '''
        <html><script type="application/ld+json">
        {"@type": "Recipe", "name": "Img",
         "image": ["https://a.com/1.jpg", "https://a.com/2.jpg"]}
        </script></html>
        '''
        result = _extract_jsonld_recipe(html)
        self.assertEqual(result['image_url'], 'https://a.com/1.jpg')

    def test_image_as_object(self):
        """Test image field as ImageObject."""
        html = '''
        <html><script type="application/ld+json">
        {"@type": "Recipe", "name": "Img",
         "image": {"@type": "ImageObject", "url": "https://a.com/photo.jpg"}}
        </script></html>
        '''
        result = _extract_jsonld_recipe(html)
        self.assertEqual(result['image_url'], 'https://a.com/photo.jpg')

    def test_multiple_authors(self):
        """Test multiple authors extracted."""
        html = '''
        <html><script type="application/ld+json">
        {"@type": "Recipe", "name": "Multi",
         "author": [
            {"@type": "Person", "name": "Alice"},
            {"@type": "Person", "name": "Bob"}
         ]}
        </script></html>
        '''
        result = _extract_jsonld_recipe(html)
        self.assertEqual(len(result['authors']), 2)
        self.assertIn('Alice', result['authors'])
        self.assertIn('Bob', result['authors'])


# ============= Merge Recipe Data Tests =============

class MergeRecipeDataTest(TestCase):
    """Test _merge_recipe_data for conflict detection."""

    def test_empty_existing_all_auto_updated(self):
        """Test all fields auto-updated when existing is empty."""
        existing = {'title': '', 'instructions': '', 'ingredients': [], 'authors': []}
        new = {'title': 'New Title', 'instructions': 'Step 1', 'ingredients': ['flour'],
               'authors': ['Chef']}
        auto, conflicts = _merge_recipe_data(existing, new)
        self.assertIn('title', auto)
        self.assertIn('instructions', auto)
        self.assertEqual(len(conflicts), 0)

    def test_same_data_no_conflicts(self):
        """Test identical data produces no conflicts or auto-updates."""
        data = {'title': 'Same', 'instructions': 'Same', 'ingredients': [], 'authors': []}
        auto, conflicts = _merge_recipe_data(data, data)
        self.assertEqual(len(auto), 0)
        self.assertEqual(len(conflicts), 0)

    def test_different_title_creates_conflict(self):
        """Test different titles create a conflict."""
        existing = {'title': 'Old Title', 'instructions': ''}
        new = {'title': 'New Title', 'instructions': ''}
        auto, conflicts = _merge_recipe_data(existing, new)
        self.assertIn('title', conflicts)
        self.assertEqual(conflicts['title']['existing'], 'Old Title')
        self.assertEqual(conflicts['title']['new'], 'New Title')

    def test_new_data_empty_no_updates(self):
        """Test empty new data causes no updates."""
        existing = {'title': 'Existing', 'instructions': 'Steps'}
        new = {'title': '', 'instructions': ''}
        auto, conflicts = _merge_recipe_data(existing, new)
        self.assertEqual(len(auto), 0)
        self.assertEqual(len(conflicts), 0)

    def test_mixed_auto_and_conflicts(self):
        """Test some fields auto-update and others conflict."""
        existing = {'title': 'Recipe A', 'instructions': '', 'source_url': ''}
        new = {'title': 'Recipe B', 'instructions': 'New steps', 'source_url': 'https://a.com'}
        auto, conflicts = _merge_recipe_data(existing, new)
        self.assertIn('title', conflicts)      # both have values
        self.assertIn('instructions', auto)     # existing is empty
        self.assertIn('source_url', auto)       # existing is empty

    def test_list_fields_compared(self):
        """Test list fields (ingredients, authors, genres) compared."""
        existing = {'ingredients': ['flour', 'sugar'], 'authors': [], 'genres': []}
        new = {'ingredients': ['flour', 'butter'], 'authors': ['Chef'], 'genres': []}
        auto, conflicts = _merge_recipe_data(existing, new)
        self.assertIn('ingredients', conflicts)
        self.assertIn('authors', auto)

    def test_chinese_data_merge(self):
        """Test merge with Chinese text data."""
        existing = {'title': '宫保鸡丁', 'instructions': ''}
        new = {'title': '宫保鸡丁', 'instructions': '先炒鸡肉'}
        auto, conflicts = _merge_recipe_data(existing, new)
        self.assertIn('instructions', auto)
        self.assertEqual(len(conflicts), 0)

    def test_arabic_data_merge(self):
        """Test merge with Arabic text data."""
        existing = {'title': 'المندي', 'instructions': 'الخطوة الأولى'}
        new = {'title': 'المندي', 'instructions': 'الطريقة الجديدة'}
        auto, conflicts = _merge_recipe_data(existing, new)
        self.assertIn('instructions', conflicts)


# ============= Combine OCR and URL Data Tests =============

class CombineOCRAndURLDataTest(TestCase):
    """Test _combine_ocr_and_url_data merging."""

    def test_both_none_returns_none(self):
        """Test both None returns None."""
        self.assertIsNone(_combine_ocr_and_url_data(None, None))

    def test_only_ocr_data(self):
        """Test only OCR data returns OCR data."""
        ocr = {'title': 'OCR Title', 'instructions': 'OCR steps'}
        result = _combine_ocr_and_url_data(ocr, None)
        self.assertEqual(result['title'], 'OCR Title')

    def test_only_url_data(self):
        """Test only URL data returns URL data."""
        url = {'title': 'URL Title', 'instructions': 'URL steps', 'success': True}
        result = _combine_ocr_and_url_data(None, url)
        self.assertEqual(result['title'], 'URL Title')

    def test_url_data_preferred(self):
        """Test URL data is preferred over OCR data."""
        ocr = {'title': 'OCR Title', 'instructions': ''}
        url = {'title': 'URL Title', 'instructions': 'URL steps', 'success': True}
        result = _combine_ocr_and_url_data(ocr, url)
        self.assertEqual(result['title'], 'URL Title')
        self.assertEqual(result['instructions'], 'URL steps')

    def test_ocr_fallback_when_url_empty(self):
        """Test OCR data used as fallback when URL field is empty."""
        ocr = {'title': 'OCR Title', 'instructions': 'OCR steps'}
        url = {'title': '', 'instructions': 'URL steps', 'success': True}
        result = _combine_ocr_and_url_data(ocr, url)
        self.assertEqual(result['title'], 'OCR Title')
        self.assertEqual(result['instructions'], 'URL steps')

    def test_unsuccessful_url_data_ignored(self):
        """Test URL data with success=False is ignored."""
        ocr = {'title': 'OCR Title', 'instructions': 'OCR steps'}
        url = {'title': 'URL Title', 'success': False}
        result = _combine_ocr_and_url_data(ocr, url)
        self.assertEqual(result['title'], 'OCR Title')


# ============= Find Existing Recipe Tests =============

class FindExistingRecipeTest(TestCase):
    """Test _find_existing_recipe_by_url and _find_existing_recipe_by_title."""

    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@test.com', 'password')
        self.recipe = Recipe.objects.create(
            title='Test Recipe', instructions='Test', created_by=self.user
        )

    def test_find_by_url(self):
        """Test finding recipe by URL."""
        RecipeURL.objects.create(
            recipe=self.recipe, url='https://example.com/recipe', is_primary=True
        )
        found = _find_existing_recipe_by_url('https://example.com/recipe')
        self.assertEqual(found.pk, self.recipe.pk)

    def test_find_by_url_not_found(self):
        """Test finding recipe by non-existent URL."""
        found = _find_existing_recipe_by_url('https://nonexistent.com/recipe')
        self.assertIsNone(found)

    def test_find_by_title(self):
        """Test finding recipe by title (case-insensitive)."""
        found = _find_existing_recipe_by_title('test recipe')
        self.assertEqual(found.pk, self.recipe.pk)

    def test_find_by_title_case_insensitive(self):
        """Test title search is case-insensitive."""
        found = _find_existing_recipe_by_title('TEST RECIPE')
        self.assertEqual(found.pk, self.recipe.pk)

    def test_find_by_title_not_found(self):
        """Test finding recipe by non-existent title."""
        found = _find_existing_recipe_by_title('Nonexistent Recipe')
        self.assertIsNone(found)

    def test_find_by_empty_title(self):
        """Test empty title returns None."""
        self.assertIsNone(_find_existing_recipe_by_title(''))
        self.assertIsNone(_find_existing_recipe_by_title(None))

    def test_find_by_chinese_title(self):
        """Test finding recipe by Chinese title."""
        recipe = Recipe.objects.create(
            title='宫保鸡丁', instructions='Test', created_by=self.user
        )
        found = _find_existing_recipe_by_title('宫保鸡丁')
        self.assertEqual(found.pk, recipe.pk)

    def test_find_by_arabic_title(self):
        """Test finding recipe by Arabic title."""
        recipe = Recipe.objects.create(
            title='المندي', instructions='Test', created_by=self.user
        )
        found = _find_existing_recipe_by_title('المندي')
        self.assertEqual(found.pk, recipe.pk)


# ============= Get Existing Recipe Data Tests =============

class GetExistingRecipeDataTest(TestCase):
    """Test _get_existing_recipe_data."""

    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@test.com', 'password')
        self.recipe = Recipe.objects.create(
            title='Full Recipe',
            instructions='Mix and bake',
            created_by=self.user
        )

    def test_basic_fields(self):
        """Test title and instructions are returned."""
        data = _get_existing_recipe_data(self.recipe)
        self.assertEqual(data['title'], 'Full Recipe')
        self.assertEqual(data['instructions'], 'Mix and bake')

    def test_ingredients_included(self):
        """Test ingredients are formatted as text list."""
        ingredient = Ingredient.objects.create(name='flour')
        RecipeIngredient.objects.create(
            recipe=self.recipe, ingredient=ingredient,
            quantity='2 cups', order=0
        )
        data = _get_existing_recipe_data(self.recipe)
        self.assertIn('2 cups - flour', data['ingredients'])

    def test_authors_included(self):
        """Test authors are returned as string list."""
        author = Author.objects.create(first_name='Julia', last_name='Child')
        self.recipe.authors.add(author)
        data = _get_existing_recipe_data(self.recipe)
        self.assertTrue(any('Julia' in a for a in data['authors']))

    def test_genres_included(self):
        """Test genres are returned."""
        genre = Genre.objects.create(name='Italian')
        self.recipe.genres.add(genre)
        data = _get_existing_recipe_data(self.recipe)
        self.assertIn('Italian', data['genres'])

    def test_source_url_included(self):
        """Test primary URL is returned."""
        RecipeURL.objects.create(
            recipe=self.recipe, url='https://example.com', is_primary=True
        )
        data = _get_existing_recipe_data(self.recipe)
        self.assertEqual(data['source_url'], 'https://example.com')


# ============= Create Recipe From Data Tests =============

class CreateRecipeFromDataTest(TestCase):
    """Test _create_recipe_from_data."""

    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@test.com', 'password')

    def test_basic_creation(self):
        """Test basic recipe creation from data dict."""
        data = {
            'title': 'New Recipe',
            'instructions': 'Step 1: Cook.',
            'ingredients': [{'name': 'flour', 'quantity': '2 cups', 'order': 0}],
            'authors': ['Test Chef'],
            'genres': ['Italian'],
            'source_url': 'https://example.com',
        }
        recipe = _create_recipe_from_data(data, self.user)
        self.assertEqual(recipe.title, 'New Recipe')
        self.assertEqual(recipe.instructions, 'Step 1: Cook.')
        self.assertEqual(recipe.created_by, self.user)
        self.assertTrue(recipe.authors.exists())
        self.assertTrue(recipe.genres.exists())
        self.assertTrue(RecipeURL.objects.filter(recipe=recipe).exists())

    def test_creation_with_empty_instructions_uses_description(self):
        """Test description is used when instructions are empty."""
        data = {
            'title': 'Desc Recipe',
            'instructions': '',
            'description': 'A delicious recipe for testing.',
        }
        recipe = _create_recipe_from_data(data, self.user)
        self.assertEqual(recipe.instructions, 'A delicious recipe for testing.')

    def test_creation_with_no_instructions_fallback(self):
        """Test fallback text when both instructions and description empty."""
        data = {'title': 'Empty Recipe'}
        recipe = _create_recipe_from_data(data, self.user)
        self.assertEqual(recipe.instructions, 'No instructions available.')

    def test_chinese_recipe_creation(self):
        """Test creating recipe with Chinese content."""
        data = {
            'title': '宫保鸡丁',
            'instructions': '先炒鸡肉，然后加入花生',
            'authors': ['张三'],
            'genres': ['中式料理'],
        }
        recipe = _create_recipe_from_data(data, self.user)
        self.assertEqual(recipe.title, '宫保鸡丁')

    def test_arabic_recipe_creation(self):
        """Test creating recipe with Arabic content."""
        data = {
            'title': 'المندي',
            'instructions': 'طريقة تحضير المندي',
            'authors': ['محمد'],
        }
        recipe = _create_recipe_from_data(data, self.user)
        self.assertEqual(recipe.title, 'المندي')

    def test_ingredients_saved(self):
        """Test ingredients from data are saved to recipe."""
        data = {
            'title': 'Ing Recipe',
            'instructions': 'Cook',
            'ingredients': [
                {'name': 'flour', 'quantity': '2 cups', 'order': 0},
                {'name': 'sugar', 'quantity': '1 cup', 'order': 1},
            ],
        }
        recipe = _create_recipe_from_data(data, self.user)
        ris = RecipeIngredient.objects.filter(recipe=recipe)
        self.assertEqual(ris.count(), 2)

    def test_very_long_title_truncated(self):
        """Test very long title is truncated."""
        data = {'title': 'T' * 1000, 'instructions': 'Test'}
        recipe = _create_recipe_from_data(data, self.user)
        self.assertLessEqual(len(recipe.title), MAX_TITLE_LENGTH)


# ============= Save Ingredients List Tests =============

class SaveIngredientsListTest(TestCase):
    """Test _save_ingredients_list."""

    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@test.com', 'password')
        self.recipe = Recipe.objects.create(
            title='Test', instructions='Test', created_by=self.user
        )

    def test_save_from_dict_list(self):
        """Test saving ingredients from list of dicts."""
        ingredients = [
            {'name': 'flour', 'quantity': '2 cups', 'order': 0},
            {'name': 'salt', 'quantity': '1 tsp', 'order': 1},
        ]
        _save_ingredients_list(self.recipe, ingredients)
        ris = RecipeIngredient.objects.filter(recipe=self.recipe)
        self.assertEqual(ris.count(), 2)

    def test_save_from_string_list(self):
        """Test saving ingredients from list of strings."""
        ingredients = ['2 cups - flour', '1 tsp - salt']
        _save_ingredients_list(self.recipe, ingredients)
        ris = RecipeIngredient.objects.filter(recipe=self.recipe)
        self.assertEqual(ris.count(), 2)

    def test_empty_list_no_error(self):
        """Test empty list doesn't cause error."""
        _save_ingredients_list(self.recipe, [])
        self.assertEqual(RecipeIngredient.objects.filter(recipe=self.recipe).count(), 0)

    def test_skip_empty_names(self):
        """Test empty ingredient names are skipped."""
        ingredients = [{'name': '', 'quantity': '1 cup', 'order': 0}]
        _save_ingredients_list(self.recipe, ingredients)
        self.assertEqual(RecipeIngredient.objects.filter(recipe=self.recipe).count(), 0)


# ============= Add Author By Name Tests =============

class AddAuthorByNameTest(TestCase):
    """Test _add_author_by_name."""

    def setUp(self):
        self.user = User.objects.create_user('testuser', 'test@test.com', 'password')
        self.recipe = Recipe.objects.create(
            title='Test', instructions='Test', created_by=self.user
        )

    def test_single_word_creates_publisher(self):
        """Test single-word name creates publisher."""
        _add_author_by_name(self.recipe, 'Tasty')
        author = self.recipe.authors.first()
        self.assertEqual(author.publisher_name, 'Tasty')

    def test_two_words_creates_first_last(self):
        """Test two-word name splits into first/last."""
        _add_author_by_name(self.recipe, 'Julia Child')
        author = self.recipe.authors.first()
        self.assertEqual(author.first_name, 'Julia')
        self.assertEqual(author.last_name, 'Child')

    def test_reuses_existing_author(self):
        """Test existing author is reused, not duplicated."""
        Author.objects.create(publisher_name='Tasty')
        _add_author_by_name(self.recipe, 'Tasty')
        self.assertEqual(Author.objects.filter(publisher_name='Tasty').count(), 1)

    def test_empty_name_skipped(self):
        """Test empty name doesn't create author."""
        _add_author_by_name(self.recipe, '')
        self.assertEqual(self.recipe.authors.count(), 0)

    def test_chinese_author(self):
        """Test Chinese author name."""
        _add_author_by_name(self.recipe, '张 伟')
        author = self.recipe.authors.first()
        self.assertIsNotNone(author)

    def test_arabic_author(self):
        """Test Arabic author name."""
        _add_author_by_name(self.recipe, 'محمد')
        author = self.recipe.authors.first()
        self.assertEqual(author.publisher_name, 'محمد')


# ============= Serialize Functions Tests =============

class SerializeTest(TestCase):
    """Test _serialize_conflicts and _serialize_new_data."""

    def test_serialize_conflicts_text(self):
        """Test serializing text conflicts."""
        conflicts = {
            'title': {'existing': 'Old', 'new': 'New'},
        }
        result = _serialize_conflicts(conflicts)
        self.assertEqual(result['title']['existing'], 'Old')
        self.assertEqual(result['title']['new'], 'New')

    def test_serialize_conflicts_list(self):
        """Test serializing list conflicts (converted to str)."""
        conflicts = {
            'ingredients': {'existing': ['flour', 'sugar'], 'new': ['butter']},
        }
        result = _serialize_conflicts(conflicts)
        self.assertIn('flour', result['ingredients']['existing'])

    def test_serialize_new_data(self):
        """Test serializing scraped data for session."""
        data = {
            'title': 'Test',
            'ingredients': [{'name': 'flour', 'qty': '1 cup'}],
            'success': True,
            'confidence': 0.85,
        }
        result = _serialize_new_data(data)
        self.assertEqual(result['title'], 'Test')
        self.assertEqual(result['confidence'], 0.85)
        self.assertTrue(result['success'])

    def test_serialize_chinese_text(self):
        """Test serializing Chinese text."""
        data = {'title': '宫保鸡丁', 'instructions': '先炒鸡肉'}
        result = _serialize_new_data(data)
        self.assertEqual(result['title'], '宫保鸡丁')

    def test_serialize_arabic_text(self):
        """Test serializing Arabic text."""
        data = {'title': 'المندي', 'instructions': 'طريقة التحضير'}
        result = _serialize_new_data(data)
        self.assertEqual(result['title'], 'المندي')


# ============= Scrape Recipe From URL Tests (Mocked) =============

class ScrapeRecipeFromURLTest(TestCase):
    """Test scrape_recipe_from_url with mocked HTTP responses."""

    MOCK_JSONLD_HTML = '''
    <html><head>
    <script type="application/ld+json">
    {"@type": "Recipe", "name": "Mocked Recipe",
     "description": "A mocked recipe for testing",
     "recipeIngredient": ["1 cup flour", "2 eggs"],
     "recipeInstructions": [{"text": "Mix."}],
     "author": {"name": "Mock Chef"},
     "recipeCategory": "Dessert",
     "image": "https://example.com/photo.jpg"}
    </script>
    </head><body></body></html>
    '''

    MOCK_PLAIN_HTML = '''
    <html><head>
    <title>Plain Page Title</title>
    <meta property="og:title" content="OG Title" />
    <meta name="description" content="A plain page description" />
    <meta name="author" content="Plain Author" />
    </head><body><p>Some content</p></body></html>
    '''

    @patch('RecipeDB.views.urllib.request.urlopen')
    def test_jsonld_scraping(self, mock_urlopen):
        """Test scraping a page with JSON-LD Recipe data."""
        mock_response = MagicMock()
        mock_response.read.return_value = self.MOCK_JSONLD_HTML.encode('utf-8')
        mock_response.headers = {'Content-Type': 'text/html; charset=utf-8'}
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = scrape_recipe_from_url('https://example.com/recipe')
        self.assertTrue(result['success'])
        self.assertEqual(result['title'], 'Mocked Recipe')
        self.assertEqual(len(result['ingredients']), 2)
        self.assertIn('Mock Chef', result['authors'])
        self.assertIn('Dessert', result['genres'])

    @patch('RecipeDB.views.urllib.request.urlopen')
    def test_fallback_scraping(self, mock_urlopen):
        """Test scraping a page without JSON-LD falls back to meta tags."""
        mock_response = MagicMock()
        mock_response.read.return_value = self.MOCK_PLAIN_HTML.encode('utf-8')
        mock_response.headers = {'Content-Type': 'text/html; charset=utf-8'}
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = scrape_recipe_from_url('https://example.com/page')
        # Should have at least a title from meta/og tags
        self.assertTrue(result.get('title'))

    @patch('RecipeDB.views.urllib.request.urlopen')
    def test_http_error_handled(self, mock_urlopen):
        """Test HTTP error is handled gracefully."""
        mock_urlopen.side_effect = urllib.error.HTTPError(
            'https://example.com', 404, 'Not Found', {}, None
        )
        result = scrape_recipe_from_url('https://example.com/missing')
        self.assertFalse(result['success'])
        self.assertIn('404', result['error'])

    @patch('RecipeDB.views.urllib.request.urlopen')
    def test_url_error_handled(self, mock_urlopen):
        """Test URL/connection error is handled gracefully."""
        mock_urlopen.side_effect = urllib.error.URLError('Connection refused')
        result = scrape_recipe_from_url('https://unreachable.invalid/')
        self.assertFalse(result['success'])
        self.assertIn('URL error', result['error'])

    @patch('RecipeDB.views.urllib.request.urlopen')
    def test_empty_response_handled(self, mock_urlopen):
        """Test empty response is handled gracefully."""
        mock_response = MagicMock()
        mock_response.read.return_value = b''
        mock_response.headers = {'Content-Type': 'text/html'}
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = scrape_recipe_from_url('https://example.com/empty')
        self.assertFalse(result['success'])

    @patch('RecipeDB.views.urllib.request.urlopen')
    def test_source_url_preserved(self, mock_urlopen):
        """Test source URL is preserved in result."""
        mock_response = MagicMock()
        mock_response.read.return_value = self.MOCK_JSONLD_HTML.encode('utf-8')
        mock_response.headers = {'Content-Type': 'text/html; charset=utf-8'}
        mock_response.__enter__ = MagicMock(return_value=mock_response)
        mock_response.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_response

        result = scrape_recipe_from_url('https://example.com/my-recipe')
        self.assertEqual(result['source_url'], 'https://example.com/my-recipe')


# ============= OCR Upload Form Tests =============

class OCRUploadFormTest(TestCase):
    """Test OCRUploadForm validation."""

    def test_form_valid_with_url_only(self):
        """Test form is valid with only recipe_url."""
        form = OCRUploadForm(data={
            'recipe_url': 'https://example.com/recipe',
            'auto_search_web': False,
        })
        self.assertTrue(form.is_valid())

    def test_form_invalid_with_nothing(self):
        """Test form is invalid without image or URL."""
        form = OCRUploadForm(data={
            'recipe_url': '',
            'auto_search_web': False,
        })
        self.assertFalse(form.is_valid())

    def test_form_invalid_url_format(self):
        """Test form rejects invalid URL format."""
        form = OCRUploadForm(data={
            'recipe_url': 'not-a-valid-url',
            'auto_search_web': False,
        })
        self.assertFalse(form.is_valid())

    def test_form_valid_with_image_only(self):
        """Test form is valid with only image file."""
        # Create a minimal valid image file in memory
        from io import BytesIO
        from PIL import Image as PILImage
        img_io = BytesIO()
        img = PILImage.new('RGB', (10, 10), color='red')
        img.save(img_io, format='PNG')
        img_io.seek(0)

        image = SimpleUploadedFile('test.png', img_io.read(), content_type='image/png')
        form = OCRUploadForm(
            data={'recipe_url': '', 'auto_search_web': False},
            files={'image_file': image}
        )
        self.assertTrue(form.is_valid())

    def test_form_valid_with_both(self):
        """Test form is valid with both image and URL."""
        from io import BytesIO
        from PIL import Image as PILImage
        img_io = BytesIO()
        img = PILImage.new('RGB', (10, 10), color='blue')
        img.save(img_io, format='PNG')
        img_io.seek(0)

        image = SimpleUploadedFile('test.png', img_io.read(), content_type='image/png')
        form = OCRUploadForm(
            data={'recipe_url': 'https://example.com/recipe', 'auto_search_web': True},
            files={'image_file': image}
        )
        self.assertTrue(form.is_valid())


# ============= OCR Upload View URL Scraping Tests =============

class OCRUploadURLScrapingViewTest(TestCase):
    """Test OCR upload view with URL-only scraping."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user('testuser', 'test@test.com', 'testpass123')
        self.client.login(username='testuser', password='testpass123')

    @patch('RecipeDB.views.scrape_recipe_from_url')
    def test_url_only_creates_recipe(self, mock_scrape):
        """Test URL-only submission creates a new recipe."""
        mock_scrape.return_value = {
            'title': 'Scraped Recipe',
            'instructions': 'Step 1: Cook.',
            'ingredients': [{'name': 'flour', 'quantity': '1 cup', 'order': 0}],
            'authors': ['Web Chef'],
            'genres': ['Italian'],
            'image_url': '',
            'source_url': 'https://example.com/recipe',
            'description': 'A test recipe',
            'success': True,
            'error': '',
        }

        response = self.client.post(reverse('ocr_upload'), {
            'recipe_url': 'https://example.com/recipe',
            'auto_search_web': False,
        })
        self.assertEqual(response.status_code, 302)
        recipe = Recipe.objects.get(title='Scraped Recipe')
        self.assertEqual(recipe.created_by, self.user)

    @patch('RecipeDB.views.scrape_recipe_from_url')
    def test_url_scrape_failure_shows_error(self, mock_scrape):
        """Test URL scrape failure shows error message."""
        mock_scrape.return_value = {
            'title': '',
            'instructions': '',
            'ingredients': [],
            'authors': [],
            'genres': [],
            'image_url': '',
            'source_url': 'https://example.com/missing',
            'description': '',
            'success': False,
            'error': 'HTTP error 404',
        }

        response = self.client.post(reverse('ocr_upload'), {
            'recipe_url': 'https://example.com/missing',
            'auto_search_web': False,
        })
        # Should re-render form with error
        self.assertEqual(response.status_code, 200)

    @patch('RecipeDB.views.scrape_recipe_from_url')
    def test_url_matching_existing_recipe_merges(self, mock_scrape):
        """Test URL scraping that matches existing recipe triggers merge flow."""
        # Create existing recipe with a URL
        recipe = Recipe.objects.create(
            title='Existing Recipe',
            instructions='Old instructions',
            created_by=self.user,
        )
        RecipeURL.objects.create(
            recipe=recipe, url='https://example.com/recipe', is_primary=True
        )

        mock_scrape.return_value = {
            'title': 'Existing Recipe',
            'instructions': 'New instructions from URL',
            'ingredients': [],
            'authors': [],
            'genres': [],
            'image_url': '',
            'source_url': 'https://example.com/recipe',
            'description': '',
            'success': True,
            'error': '',
        }

        response = self.client.post(reverse('ocr_upload'), {
            'recipe_url': 'https://example.com/recipe',
            'auto_search_web': False,
        })
        # Should redirect to merge confirm since instructions conflict
        self.assertEqual(response.status_code, 302)


# ============= Recipe Merge Confirm View Tests =============

class RecipeMergeConfirmViewTest(TestCase):
    """Test recipe_merge_confirm view."""

    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user('testuser', 'test@test.com', 'testpass123')
        self.client.login(username='testuser', password='testpass123')
        self.recipe = Recipe.objects.create(
            title='Merge Test Recipe',
            instructions='Old instructions',
            created_by=self.user,
        )

    def test_get_merge_page_with_session_data(self):
        """Test GET merge confirm page renders with session data."""
        session = self.client.session
        session['merge_recipe_id'] = self.recipe.pk
        session['merge_conflicts'] = {
            'instructions': {'existing': 'Old instructions', 'new': 'New instructions'},
        }
        session['merge_new_data'] = {'instructions': 'New instructions'}
        session.save()

        response = self.client.get(reverse('recipe_merge_confirm'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Old instructions')
        self.assertContains(response, 'New instructions')

    def test_get_merge_page_without_session_redirects(self):
        """Test GET merge confirm without session data redirects."""
        response = self.client.get(reverse('recipe_merge_confirm'))
        self.assertEqual(response.status_code, 302)

    def test_post_keep_existing(self):
        """Test POST with 'keep' choice keeps existing data."""
        session = self.client.session
        session['merge_recipe_id'] = self.recipe.pk
        session['merge_conflicts'] = {
            'instructions': {'existing': 'Old instructions', 'new': 'New instructions'},
        }
        session['merge_new_data'] = {'instructions': 'New instructions'}
        session.save()

        response = self.client.post(reverse('recipe_merge_confirm'), {
            'choice_instructions': 'keep',
        })
        self.assertEqual(response.status_code, 302)
        self.recipe.refresh_from_db()
        self.assertEqual(self.recipe.instructions, 'Old instructions')

    def test_post_replace_with_new(self):
        """Test POST with 'replace' choice updates data."""
        session = self.client.session
        session['merge_recipe_id'] = self.recipe.pk
        session['merge_conflicts'] = {
            'instructions': {'existing': 'Old instructions', 'new': 'New instructions'},
        }
        session['merge_new_data'] = {'instructions': 'New instructions'}
        session.save()

        response = self.client.post(reverse('recipe_merge_confirm'), {
            'choice_instructions': 'replace',
        })
        self.assertEqual(response.status_code, 302)
        self.recipe.refresh_from_db()
        self.assertEqual(self.recipe.instructions, 'New instructions')

    def test_post_replace_title(self):
        """Test POST replacing title."""
        session = self.client.session
        session['merge_recipe_id'] = self.recipe.pk
        session['merge_conflicts'] = {
            'title': {'existing': 'Merge Test Recipe', 'new': 'Updated Title'},
        }
        session['merge_new_data'] = {'title': 'Updated Title'}
        session.save()

        response = self.client.post(reverse('recipe_merge_confirm'), {
            'choice_title': 'replace',
        })
        self.recipe.refresh_from_db()
        self.assertEqual(self.recipe.title, 'Updated Title')

    def test_post_replace_source_url(self):
        """Test POST replacing source URL."""
        session = self.client.session
        session['merge_recipe_id'] = self.recipe.pk
        session['merge_conflicts'] = {
            'source_url': {'existing': 'https://old.com', 'new': 'https://new.com'},
        }
        session['merge_new_data'] = {'source_url': 'https://new.com'}
        session.save()

        response = self.client.post(reverse('recipe_merge_confirm'), {
            'choice_source_url': 'replace',
        })
        self.assertEqual(response.status_code, 302)

    def test_session_cleared_after_merge(self):
        """Test session keys are cleared after merge POST."""
        session = self.client.session
        session['merge_recipe_id'] = self.recipe.pk
        session['merge_conflicts'] = {
            'instructions': {'existing': 'Old', 'new': 'New'},
        }
        session['merge_new_data'] = {'instructions': 'New'}
        session.save()

        self.client.post(reverse('recipe_merge_confirm'), {
            'choice_instructions': 'keep',
        })
        session = self.client.session
        self.assertNotIn('merge_recipe_id', session)
        self.assertNotIn('merge_conflicts', session)
        self.assertNotIn('merge_new_data', session)

    def test_merge_requires_login(self):
        """Test merge confirm view requires authentication."""
        self.client.logout()
        response = self.client.get(reverse('recipe_merge_confirm'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url)

    def test_merge_with_chinese_data(self):
        """Test merge with Chinese text in conflicts."""
        self.recipe.title = '旧标题'
        self.recipe.save()

        session = self.client.session
        session['merge_recipe_id'] = self.recipe.pk
        session['merge_conflicts'] = {
            'title': {'existing': '旧标题', 'new': '新标题'},
        }
        session['merge_new_data'] = {'title': '新标题'}
        session.save()

        response = self.client.post(reverse('recipe_merge_confirm'), {
            'choice_title': 'replace',
        })
        self.recipe.refresh_from_db()
        self.assertEqual(self.recipe.title, '新标题')

    def test_merge_with_arabic_data(self):
        """Test merge with Arabic text in conflicts."""
        self.recipe.title = 'العنوان القديم'
        self.recipe.save()

        session = self.client.session
        session['merge_recipe_id'] = self.recipe.pk
        session['merge_conflicts'] = {
            'title': {'existing': 'العنوان القديم', 'new': 'العنوان الجديد'},
        }
        session['merge_new_data'] = {'title': 'العنوان الجديد'}
        session.save()

        response = self.client.post(reverse('recipe_merge_confirm'), {
            'choice_title': 'replace',
        })
        self.recipe.refresh_from_db()
        self.assertEqual(self.recipe.title, 'العنوان الجديد')
