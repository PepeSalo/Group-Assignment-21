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

from .models import (
    Author, Genre, Ingredient, Recipe, RecipeIngredient,
    PublishedRating, PersonalRating, RecipeURL,
    MAX_RATING, MIN_RATING, MAX_NAME_LENGTH, MAX_TITLE_LENGTH
)
from .views import (
    _save_ingredients_from_text, _save_authors_from_text,
    _save_genres_from_text, _save_source_url,
    _background_delete_file, extract_recipe_from_text,
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
