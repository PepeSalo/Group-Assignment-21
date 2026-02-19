import os
import logging
import re
import shutil
import subprocess
import threading
import time
import gc
import json
import urllib.request
import urllib.parse
import urllib.error
from html.parser import HTMLParser
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

try:
    from bs4 import BeautifulSoup
    HAS_BS4 = True
except ImportError:
    HAS_BS4 = False

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

# Constants for web scraping
SCRAPE_TIMEOUT = 15  # seconds
SCRAPE_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 RecipeDB/1.0'
URL_REGEX = re.compile(
    r'https?://[^\s<>"\')\]},;]+',
    re.IGNORECASE
)

# Pattern for OCR-garbled URLs (missing ://, extra spaces, etc.)
OCR_URL_REGEX = re.compile(
    r'https?\s*[:/\\]+\s*[/\\]?\s*[A-Za-z]?(?:www\.)?[a-zA-Z0-9][a-zA-Z0-9._-]*\.[a-zA-Z]{2,}[^\s<>"\']*',
    re.IGNORECASE
)

# Known recipe website brands → search URL templates
# Maps OCR-detected branding text to site search URLs
KNOWN_RECIPE_SITES = {
    'food< wine': 'https://www.foodandwine.com/?s={}',
    'food & wine': 'https://www.foodandwine.com/?s={}',
    'food and wine': 'https://www.foodandwine.com/?s={}',
    'foodandwine': 'https://www.foodandwine.com/?s={}',
    'allrecipes': 'https://www.allrecipes.com/search?q={}',
    'bon appetit': 'https://www.bonappetit.com/search?q={}',
    'bon appétit': 'https://www.bonappetit.com/search?q={}',
    'epicurious': 'https://www.epicurious.com/search?q={}',
    'simplyrecipes': 'https://www.simplyrecipes.com/?s={}',
    'simply recipes': 'https://www.simplyrecipes.com/?s={}',
    'tasty': 'https://tasty.co/search?q={}',
    'delish': 'https://www.delish.com/search/?q={}',
    'serious eats': 'https://www.seriouseats.com/search?q={}',
    'seriouseats': 'https://www.seriouseats.com/search?q={}',
    'feasting at home': 'https://www.feastingathome.com/?s={}',
    'feastingathome': 'https://www.feastingathome.com/?s={}',
    'nyt cooking': 'https://cooking.nytimes.com/search?q={}',
    'kotiliesi': 'https://kotiliesi.fi/?s={}',
    'makuja': 'https://www.mtvuutiset.fi/makuja/?s={}',
}

# Known recipe URL path patterns per domain (for slug-based guessing)
# Each domain maps to a list of URL templates where {} is the slug
KNOWN_RECIPE_URL_PATTERNS = {
    'www.foodandwine.com': [
        'https://www.foodandwine.com/recipes/{}',
        'https://www.foodandwine.com/{}',
    ],
    'www.allrecipes.com': [
        'https://www.allrecipes.com/recipe/{}/',
    ],
    'www.bonappetit.com': [
        'https://www.bonappetit.com/recipe/{}',
    ],
    'www.epicurious.com': [
        'https://www.epicurious.com/recipes/food/views/{}',
    ],
    'www.simplyrecipes.com': [
        'https://www.simplyrecipes.com/recipes/{}/',
        'https://www.simplyrecipes.com/{}/',
    ],
    'www.seriouseats.com': [
        'https://www.seriouseats.com/{}',
        'https://www.seriouseats.com/recipes/{}',
    ],
}


def _detect_recipe_site(text):
    """
    Detect a known recipe website from OCR text branding.

    Args:
        text: raw OCR text

    Returns:
        (site_name, search_url_template) or (None, None)
    """
    lower = text.lower()
    for brand, search_template in KNOWN_RECIPE_SITES.items():
        if brand in lower:
            return brand, search_template
    return None, None


def _title_to_slug(title):
    """
    Convert a recipe title to a URL slug.

    Removes parenthetical text to generate multiple slug variants:
    full title, inner parenthetical, and title without parenthetical.

    Args:
        title: Recipe title string

    Returns:
        list of slug variants to try
    """
    import re

    slugs = []

    # Helper: convert text to slug
    def _slugify(text):
        text = text.lower().strip()
        text = re.sub(r'[^\w\s-]', '', text)  # Remove special chars
        text = re.sub(r'[\s_]+', '-', text)   # Spaces/underscores to hyphens
        text = re.sub(r'-+', '-', text)        # Collapse multiple hyphens
        return text.strip('-')

    # Full title as slug
    full_slug = _slugify(title)
    if full_slug:
        slugs.append(full_slug)

    # If title has parenthetical, try variants
    paren_match = re.search(r'\(([^)]+)\)', title)
    if paren_match:
        inner = paren_match.group(1)
        outer = re.sub(r'\([^)]+\)', '', title).strip()
        inner_slug = _slugify(inner)
        outer_slug = _slugify(outer)
        if inner_slug and inner_slug != full_slug:
            slugs.append(inner_slug)
        if outer_slug and outer_slug != full_slug:
            slugs.append(outer_slug)

    return slugs


def _guess_recipe_url_by_slug(title, search_url_template):
    """
    Try to find a recipe page by constructing slug-based URLs.

    Uses known URL patterns for the detected site and checks
    whether those URLs exist (return HTTP 200).

    Args:
        title: Recipe title
        search_url_template: The site's search URL template (used to
            extract the domain)

    Returns:
        str URL if found, else None
    """
    import urllib.request
    import urllib.parse

    parsed = urllib.parse.urlparse(search_url_template)
    domain = parsed.netloc
    if not domain:
        return None

    url_patterns = KNOWN_RECIPE_URL_PATTERNS.get(domain, [])
    if not url_patterns:
        return None

    slugs = _title_to_slug(title)
    if not slugs:
        return None

    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/120.0.0.0 Safari/537.36'
        ),
    }

    for slug in slugs:
        for pattern in url_patterns:
            candidate_url = pattern.format(slug)
            try:
                req = urllib.request.Request(
                    candidate_url, method='HEAD', headers=headers,
                )
                with urllib.request.urlopen(req, timeout=10) as response:
                    if response.status == 200:
                        logger.info(
                            f"Slug-based URL found: {candidate_url}"
                        )
                        return candidate_url
            except Exception:
                # URL doesn't exist, try next
                continue

    logger.info(f"No slug-based URL found for '{title}' on {domain}")
    return None


def _extract_urls_from_text(text):
    """
    Extract URLs from OCR text using regex.
    Handles both clean URLs and OCR-garbled URLs with common artifacts.

    Args:
        text: Raw text (from OCR or any source)

    Returns:
        list of URL strings found in the text
    """
    if not text:
        return []

    urls = set()

    # Strategy 1: Clean URL regex
    for url in URL_REGEX.findall(text):
        url = url.rstrip('.,;:!?)')
        if len(url) > 10:
            urls.add(url)

    # Strategy 2: OCR-garbled URL repair
    for match in OCR_URL_REGEX.finditer(text):
        raw = match.group(0)
        repaired = _repair_ocr_url(raw)
        if repaired:
            repaired = repaired.rstrip('.,;:!?)')
            if len(repaired) > 10:
                urls.add(repaired)

    # Strategy 3: Look for domain-like patterns without scheme
    domain_pattern = re.compile(
        r'(?:www\.)[a-zA-Z0-9][a-zA-Z0-9._-]*\.[a-zA-Z]{2,}[^\s<>"\']*',
        re.IGNORECASE
    )
    for match in domain_pattern.finditer(text):
        raw = match.group(0).rstrip('.,;:!?)')
        if len(raw) > 10:
            urls.add('https://' + raw)

    return list(urls)


def _repair_ocr_url(raw_url):
    """
    Attempt to repair a URL that was garbled by OCR.
    Common OCR errors:
    - 'https /Awww.' instead of 'https://www.'
    - Missing '://'
    - Extra spaces
    - 'l' vs '1', 'O' vs '0', etc.

    Args:
        raw_url: Raw string that might be a garbled URL

    Returns:
        Repaired URL string or None if unrepairable
    """
    if not raw_url:
        return None

    url = raw_url.strip()

    # Remove leading non-URL characters
    url = re.sub(r'^[^hH]*(?=https?)', '', url)

    # Fix scheme: 'https //' → 'https://', 'https /' → 'https://'
    url = re.sub(r'^(https?)\s*[:/\\]+\s*[/\\]?\s*', r'\1://', url, flags=re.IGNORECASE)

    # Remove accidental uppercase after scheme (OCR artifact: 'https://Awww' → 'https://www')
    url = re.sub(r'^(https?://)([A-Z])(?=www\.)', r'\1', url, flags=re.IGNORECASE)

    # Remove spaces within URL
    parts = url.split('://', 1)
    if len(parts) == 2:
        url = parts[0] + '://' + parts[1].replace(' ', '')

    # Validate basic URL structure
    if re.match(r'^https?://[a-zA-Z0-9]', url):
        return url

    return None


def scrape_recipe_from_url(url):
    """
    Scrape recipe data from a URL.

    Tries multiple strategies:
    1. JSON-LD structured data (schema.org Recipe)
    2. Open Graph / meta tags
    3. BeautifulSoup HTML parsing (headings, lists)
    4. Fallback plain text extraction

    Args:
        url: URL string to scrape

    Returns:
        dict with keys: title, instructions, ingredients (list of dicts),
        authors (list of strings), genres (list of strings),
        image_url, source_url, description, success, error
    """
    result = {
        'title': '',
        'instructions': '',
        'ingredients': [],
        'authors': [],
        'genres': [],
        'image_url': '',
        'source_url': url,
        'description': '',
        'success': False,
        'error': '',
    }

    try:
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': SCRAPE_USER_AGENT,
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.9,fi;q=0.8',
            }
        )
        with urllib.request.urlopen(req, timeout=SCRAPE_TIMEOUT) as response:
            content_type = response.headers.get('Content-Type', '')
            encoding = 'utf-8'
            if 'charset=' in content_type:
                encoding = content_type.split('charset=')[-1].split(';')[0].strip()
            html_bytes = response.read()
            html = html_bytes.decode(encoding, errors='replace')

        if not html.strip():
            result['error'] = 'Empty response from URL'
            return result

        # Strategy 1: JSON-LD structured data
        jsonld_data = _extract_jsonld_recipe(html)
        if jsonld_data:
            result.update(jsonld_data)
            result['success'] = True
            result['source_url'] = url
            logger.info(f"Scraped recipe via JSON-LD from {url}")
            return result

        # Strategy 2: Parse with BeautifulSoup (or fallback)
        if HAS_BS4:
            parsed = _extract_recipe_bs4(html, url)
        else:
            parsed = _extract_recipe_fallback(html, url)

        if parsed.get('title'):
            result.update(parsed)
            result['success'] = True
            result['source_url'] = url
            logger.info(f"Scraped recipe via HTML parsing from {url}")
        else:
            result['error'] = 'Could not extract recipe data from URL'

    except urllib.error.HTTPError as e:
        result['error'] = f'HTTP error {e.code}: {e.reason}'
        logger.warning(f"HTTP error scraping {url}: {e}")
    except urllib.error.URLError as e:
        result['error'] = f'URL error: {e.reason}'
        logger.warning(f"URL error scraping {url}: {e}")
    except Exception as e:
        result['error'] = f'Scraping error: {str(e)}'
        logger.error(f"Error scraping {url}: {e}")

    return result


def _extract_jsonld_recipe(html):
    """
    Extract recipe data from JSON-LD script tags.

    Args:
        html: Raw HTML string

    Returns:
        dict with recipe data or None if no recipe JSON-LD found
    """
    try:
        # Find all JSON-LD script blocks
        pattern = re.compile(
            r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
            re.DOTALL | re.IGNORECASE
        )
        matches = pattern.findall(html)

        for match in matches:
            try:
                data = json.loads(match.strip())
            except json.JSONDecodeError:
                continue

            # Handle both single object and @graph array
            recipes = []
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict):
                        if item.get('@type') == 'Recipe' or (
                            isinstance(item.get('@type'), list) and 'Recipe' in item['@type']
                        ):
                            recipes.append(item)
                        if '@graph' in item:
                            for g in item['@graph']:
                                if isinstance(g, dict) and (
                                    g.get('@type') == 'Recipe' or
                                    (isinstance(g.get('@type'), list) and 'Recipe' in g['@type'])
                                ):
                                    recipes.append(g)
            elif isinstance(data, dict):
                if data.get('@type') == 'Recipe' or (
                    isinstance(data.get('@type'), list) and 'Recipe' in data['@type']
                ):
                    recipes.append(data)
                if '@graph' in data:
                    for g in data['@graph']:
                        if isinstance(g, dict) and (
                            g.get('@type') == 'Recipe' or
                            (isinstance(g.get('@type'), list) and 'Recipe' in g['@type'])
                        ):
                            recipes.append(g)

            for recipe in recipes:
                return _parse_jsonld_recipe(recipe)

    except Exception as e:
        logger.debug(f"JSON-LD extraction failed: {e}")

    return None


def _parse_jsonld_recipe(data):
    """
    Parse a JSON-LD Recipe object into our standard dict format.

    Args:
        data: dict from parsed JSON-LD

    Returns:
        dict with recipe data
    """
    result = {
        'title': '',
        'instructions': '',
        'ingredients': [],
        'authors': [],
        'genres': [],
        'image_url': '',
        'description': '',
    }

    # Title
    result['title'] = _clean_html_text(str(data.get('name', '')))

    # Description
    result['description'] = _clean_html_text(str(data.get('description', '')))

    # Instructions
    instructions = data.get('recipeInstructions', '')
    if isinstance(instructions, list):
        steps = []
        for item in instructions:
            if isinstance(item, str):
                steps.append(_clean_html_text(item))
            elif isinstance(item, dict):
                text = item.get('text', item.get('name', ''))
                if text:
                    steps.append(_clean_html_text(str(text)))
        result['instructions'] = '\n'.join(steps)
    elif isinstance(instructions, str):
        result['instructions'] = _clean_html_text(instructions)

    # Ingredients
    ingredients = data.get('recipeIngredient', [])
    if isinstance(ingredients, list):
        for i, ing in enumerate(ingredients):
            ing_text = _clean_html_text(str(ing))
            # Try to parse "quantity name" format
            parts = ing_text.split(None, 1)
            if len(parts) == 2 and any(c.isdigit() for c in parts[0]):
                result['ingredients'].append({
                    'name': parts[1],
                    'quantity': parts[0],
                    'order': i,
                })
            else:
                result['ingredients'].append({
                    'name': ing_text,
                    'quantity': '',
                    'order': i,
                })

    # Authors
    author = data.get('author', [])
    if isinstance(author, dict):
        author = [author]
    elif isinstance(author, str):
        author = [{'name': author}]
    if isinstance(author, list):
        for a in author:
            if isinstance(a, dict):
                name = a.get('name', '')
                if name:
                    result['authors'].append(_clean_html_text(str(name)))
            elif isinstance(a, str):
                result['authors'].append(_clean_html_text(a))

    # Genres / categories
    category = data.get('recipeCategory', [])
    cuisine = data.get('recipeCuisine', [])
    if isinstance(category, str):
        category = [category]
    if isinstance(cuisine, str):
        cuisine = [cuisine]
    for cat in (category or []):
        result['genres'].append(_clean_html_text(str(cat)))
    for cuis in (cuisine or []):
        result['genres'].append(_clean_html_text(str(cuis)))

    # Image
    image = data.get('image', '')
    if isinstance(image, list) and image:
        image = image[0]
    if isinstance(image, dict):
        image = image.get('url', '')
    result['image_url'] = str(image) if image else ''

    return result


def _extract_recipe_bs4(html, url):
    """
    Extract recipe data using BeautifulSoup HTML parsing.

    Args:
        html: Raw HTML string
        url: Source URL (for context)

    Returns:
        dict with recipe data
    """
    result = {
        'title': '',
        'instructions': '',
        'ingredients': [],
        'authors': [],
        'genres': [],
        'image_url': '',
        'description': '',
    }

    try:
        soup = BeautifulSoup(html, 'html.parser')

        # Title: try meta og:title, then <title>, then <h1>
        og_title = soup.find('meta', property='og:title')
        if og_title and og_title.get('content'):
            result['title'] = og_title['content'].strip()
        elif soup.title and soup.title.string:
            result['title'] = soup.title.string.strip()
        elif soup.h1:
            result['title'] = soup.h1.get_text(strip=True)

        # Description: try meta description
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc and meta_desc.get('content'):
            result['description'] = meta_desc['content'].strip()
        og_desc = soup.find('meta', property='og:description')
        if og_desc and og_desc.get('content') and not result['description']:
            result['description'] = og_desc['content'].strip()

        # Image: try meta og:image
        og_img = soup.find('meta', property='og:image')
        if og_img and og_img.get('content'):
            result['image_url'] = og_img['content'].strip()

        # Author
        meta_author = soup.find('meta', attrs={'name': 'author'})
        if meta_author and meta_author.get('content'):
            result['authors'].append(meta_author['content'].strip())

        # Try to find ingredient lists (common CSS classes)
        ingredient_selectors = [
            'recipe-ingredient', 'ingredient', 'ingredients',
            'wprm-recipe-ingredient', 'tasty-recipes-ingredients',
        ]
        for sel in ingredient_selectors:
            items = soup.find_all(class_=re.compile(sel, re.IGNORECASE))
            if items:
                for i, item in enumerate(items):
                    text = item.get_text(strip=True)
                    if text and len(text) > 1:
                        result['ingredients'].append({
                            'name': text,
                            'quantity': '',
                            'order': i,
                        })
                if result['ingredients']:
                    break

        # Try to find instructions
        instruction_selectors = [
            'recipe-instruction', 'instruction', 'instructions',
            'wprm-recipe-instruction', 'tasty-recipes-instructions',
            'recipe-directions', 'directions', 'method', 'steps',
        ]
        for sel in instruction_selectors:
            items = soup.find_all(class_=re.compile(sel, re.IGNORECASE))
            if items:
                steps = []
                for item in items:
                    text = item.get_text(strip=True)
                    if text and len(text) > 5:
                        steps.append(text)
                if steps:
                    result['instructions'] = '\n'.join(steps)
                    break

        # Fallback: use main content paragraphs as instructions
        if not result['instructions']:
            article = soup.find('article') or soup.find('main') or soup.find('div', class_=re.compile('content|post|entry', re.IGNORECASE))
            if article:
                paragraphs = article.find_all('p')
                text_parts = []
                for p in paragraphs:
                    t = p.get_text(strip=True)
                    if t and len(t) > 20:
                        text_parts.append(t)
                if text_parts:
                    result['instructions'] = '\n\n'.join(text_parts[:20])

        # Clean title - remove site name suffix
        if result['title'] and ' | ' in result['title']:
            result['title'] = result['title'].split(' | ')[0].strip()
        if result['title'] and ' - ' in result['title']:
            parts = result['title'].split(' - ')
            if len(parts) == 2 and len(parts[0]) > len(parts[1]):
                result['title'] = parts[0].strip()

    except Exception as e:
        logger.error(f"BeautifulSoup parsing error: {e}")

    return result


def _extract_recipe_fallback(html, url):
    """
    Fallback recipe extraction without BeautifulSoup using regex.

    Args:
        html: Raw HTML string
        url: Source URL

    Returns:
        dict with recipe data
    """
    result = {
        'title': '',
        'instructions': '',
        'ingredients': [],
        'authors': [],
        'genres': [],
        'image_url': '',
        'description': '',
    }

    try:
        # Extract title from <title> tag
        title_match = re.search(r'<title[^>]*>(.*?)</title>', html, re.IGNORECASE | re.DOTALL)
        if title_match:
            result['title'] = _clean_html_text(title_match.group(1))

        # Extract og:title
        og_match = re.search(r'<meta[^>]*property=["\']og:title["\'][^>]*content=["\'](.*?)["\']', html, re.IGNORECASE)
        if og_match:
            result['title'] = _clean_html_text(og_match.group(1))

        # Extract description
        desc_match = re.search(r'<meta[^>]*name=["\']description["\'][^>]*content=["\'](.*?)["\']', html, re.IGNORECASE)
        if desc_match:
            result['description'] = _clean_html_text(desc_match.group(1))

        # Extract og:image
        img_match = re.search(r'<meta[^>]*property=["\']og:image["\'][^>]*content=["\'](.*?)["\']', html, re.IGNORECASE)
        if img_match:
            result['image_url'] = img_match.group(1)

        # Clean title
        if result['title'] and ' | ' in result['title']:
            result['title'] = result['title'].split(' | ')[0].strip()

    except Exception as e:
        logger.error(f"Fallback HTML parsing error: {e}")

    return result


def _clean_html_text(text):
    """Remove HTML tags and decode entities from text."""
    if not text:
        return ''
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', text)
    # Decode common HTML entities
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    text = text.replace('&quot;', '"')
    text = text.replace('&#39;', "'")
    text = text.replace('&nbsp;', ' ')
    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _merge_recipe_data(existing_data, new_data):
    """
    Compare existing recipe data with new scraped data.
    Identifies fields that can be auto-filled (empty in existing)
    and fields that conflict (both have different values).

    Args:
        existing_data: dict with current recipe field values
        new_data: dict with scraped data

    Returns:
        tuple of (auto_updates: dict, conflicts: dict)
        auto_updates: fields that will be auto-filled (were empty)
        conflicts: fields where existing vs new data differs
    """
    auto_updates = {}
    conflicts = {}

    text_fields = ['title', 'instructions', 'description']
    for field in text_fields:
        existing_val = existing_data.get(field, '').strip()
        new_val = new_data.get(field, '').strip()
        if new_val:
            if not existing_val:
                auto_updates[field] = new_val
            elif existing_val != new_val:
                conflicts[field] = {
                    'existing': existing_val,
                    'new': new_val,
                }

    # List fields
    list_fields = ['ingredients', 'authors', 'genres']
    for field in list_fields:
        existing_list = existing_data.get(field, [])
        new_list = new_data.get(field, [])
        if new_list:
            if not existing_list:
                auto_updates[field] = new_list
            elif existing_list != new_list:
                conflicts[field] = {
                    'existing': existing_list,
                    'new': new_list,
                }

    # Image / source_url
    for field in ['image_url', 'source_url']:
        existing_val = existing_data.get(field, '').strip()
        new_val = new_data.get(field, '').strip()
        if new_val:
            if not existing_val:
                auto_updates[field] = new_val
            elif existing_val != new_val:
                conflicts[field] = {
                    'existing': existing_val,
                    'new': new_val,
                }

    return auto_updates, conflicts


def _get_existing_recipe_data(recipe):
    """
    Extract current data from a Recipe instance into a comparable dict.

    Args:
        recipe: Recipe model instance

    Returns:
        dict with recipe data
    """
    # Get ingredients as text list
    ingredients_list = []
    ris = RecipeIngredient.objects.filter(recipe=recipe).select_related('ingredient').order_by('order')
    for ri in ris:
        if ri.quantity:
            ingredients_list.append(f"{ri.quantity} - {ri.ingredient.name}")
        else:
            ingredients_list.append(ri.ingredient.name)

    # Get authors
    authors_list = [str(a) for a in recipe.authors.all()]

    # Get genres
    genres_list = [g.name for g in recipe.genres.all()]

    # Get primary URL
    primary_url = RecipeURL.objects.filter(recipe=recipe, is_primary=True).first()
    source_url = primary_url.url if primary_url else ''

    # Get image URL
    image_url = recipe.image.url if recipe.image else ''

    return {
        'title': recipe.title,
        'instructions': recipe.instructions,
        'description': '',  # Recipe model doesn't have description yet
        'ingredients': ingredients_list,
        'authors': authors_list,
        'genres': genres_list,
        'source_url': source_url,
        'image_url': image_url,
    }


def _find_existing_recipe_by_url(url):
    """
    Find an existing recipe that has the given URL.

    Args:
        url: URL string to search for

    Returns:
        Recipe instance or None
    """
    recipe_url = RecipeURL.objects.filter(url=url).first()
    if recipe_url:
        return recipe_url.recipe
    return None


def _find_existing_recipe_by_title(title):
    """
    Find an existing recipe by title (case-insensitive).

    Args:
        title: Recipe title to search for

    Returns:
        Recipe instance or None
    """
    if not title:
        return None
    return Recipe.objects.filter(title__iexact=title.strip()).first()


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
            # Provide primary source URL for prominent display
            primary_url_obj = RecipeURL.objects.filter(recipe=recipe, is_primary=True).first()
            context['primary_source_url'] = primary_url_obj.url if primary_url_obj else ''
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

    # Only accept valid web URLs (not local file paths or media paths)
    if not source_url.lower().startswith(('http://', 'https://')):
        logger.warning(f"Ignoring non-HTTP source URL: {source_url!r}")
        return
    
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
    """Upload images for OCR processing and/or scrape recipes from URLs."""
    if request.method == 'POST':
        form = OCRUploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                image_file = form.cleaned_data.get('image_file')
                recipe_url = form.cleaned_data.get('recipe_url', '').strip()
                auto_search_web = form.cleaned_data.get('auto_search_web', False)
                original_filename = image_file.name if image_file else None
                logger.debug(f"OCR upload: image={original_filename!r}, url={recipe_url!r}")

                ocr_data = None
                url_data = None
                detected_urls = []
                ocr_result = None

                # ---------- Step 1: OCR text extraction ----------
                if image_file:
                    ocr_result = process_ocr_image(image_file, request.user, auto_search_web=False)
                    logger.debug(f"OCR result: success={ocr_result.get('success')}")

                    # Extract URLs from OCR text even if OCR confidence is low
                    ocr_text = ocr_result.get('raw_text', '')
                    detected_urls = _extract_urls_from_text(ocr_text)
                    if detected_urls:
                        logger.info(f"URLs found in OCR text: {detected_urls}")

                # ---------- Step 2: URL-first approach ----------
                # Priority 1: Explicit URL from the form
                if recipe_url:
                    url_data = scrape_recipe_from_url(recipe_url)
                    if url_data['success']:
                        messages.info(request, "Successfully scraped recipe from URL.")
                    else:
                        messages.warning(request, f"URL scraping: {url_data['error']}")
                        url_data = None

                # Priority 2: If auto_search_web checked AND URLs detected in image, scrape them
                if not url_data and detected_urls and auto_search_web:
                    for detected_url in detected_urls[:3]:
                        url_data = scrape_recipe_from_url(detected_url)
                        if url_data and url_data['success']:
                            messages.info(request, f"Scraped recipe from URL found in image: {detected_url}")
                            break
                        else:
                            logger.debug(f"Failed to scrape detected URL: {detected_url}")
                            url_data = None

                # ---------- Step 3: Fall back to OCR text extraction ----------
                # Only parse OCR text if URL scraping didn't produce good data
                if image_file and ocr_result:
                    if url_data and url_data.get('success'):
                        # URL scraping worked — skip basic OCR text parse,
                        # but add detected URLs as source_url if not already set
                        if not url_data.get('source_url') and detected_urls:
                            url_data['source_url'] = detected_urls[0]
                        logger.info("Using URL-scraped data instead of OCR text extraction.")
                    elif ocr_result['success']:
                        ocr_data = ocr_result.get('recipe_data', {})
                        # Attach any detected URLs to OCR data as source_url
                        if detected_urls and not ocr_data.get('source_url'):
                            ocr_data['source_url'] = detected_urls[0]

                # Priority 3: If auto_search_web and we have a title but no URL data, search the web
                if auto_search_web and not url_data:
                    title = None
                    if ocr_data and ocr_data.get('title'):
                        title = ocr_data['title']
                    if title:
                        found_url = _search_web_for_recipe(title)
                        if found_url:
                            url_data = scrape_recipe_from_url(found_url)
                            if url_data and url_data['success']:
                                messages.info(request, "Found and scraped recipe from web search.")
                            else:
                                url_data = None

                        # If general web search failed, try site-specific search
                        if not url_data:
                            ocr_text = ocr_result.get('raw_text', '') if ocr_result else ''
                            site_name, search_template = _detect_recipe_site(ocr_text)
                            if search_template:
                                logger.info(f"Detected recipe site '{site_name}', searching on site...")
                                # Strategy A: search the site's search page
                                site_url = _search_recipe_on_site(title, search_template)
                                # Strategy B: try slug-based URL guessing
                                if not site_url:
                                    site_url = _guess_recipe_url_by_slug(
                                        title, search_template,
                                    )
                                if site_url:
                                    url_data = scrape_recipe_from_url(site_url)
                                    if url_data and url_data['success']:
                                        messages.info(
                                            request,
                                            f"Found recipe on {site_name}!"
                                        )
                                    else:
                                        url_data = None

                # ---------- Step 4: Combine data and decide action ----------
                combined_data = _combine_ocr_and_url_data(ocr_data, url_data)

                if not combined_data or not combined_data.get('title'):
                    if image_file and not (ocr_data or url_data):
                        if ocr_result and ocr_result.get('error'):
                            messages.error(request, f"OCR failed: {ocr_result['error']}")
                        else:
                            messages.error(request, "Could not extract recipe data.")
                    elif not url_data:
                        messages.error(request, "No recipe data could be extracted.")
                    # Clean up file handles before returning
                    if image_file:
                        image_file.close()
                        gc.collect()
                        if ocr_result:
                            _handle_images_folder_file(original_filename, False, request)
                    return render(request, 'RecipeDB/ocr_upload.html', {'form': form})

                # Check for existing recipe (by URL first, then by title)
                existing_recipe = None
                source_url = combined_data.get('source_url', recipe_url or '')
                if source_url:
                    existing_recipe = _find_existing_recipe_by_url(source_url)
                if not existing_recipe and recipe_url:
                    existing_recipe = _find_existing_recipe_by_url(recipe_url)
                if not existing_recipe and combined_data.get('title'):
                    existing_recipe = _find_existing_recipe_by_title(combined_data['title'])

                if existing_recipe:
                    # Recipe exists - check for conflicts
                    existing_data = _get_existing_recipe_data(existing_recipe)
                    auto_updates, conflicts = _merge_recipe_data(existing_data, combined_data)

                    # Auto-apply non-conflicting updates
                    if auto_updates:
                        _apply_auto_updates(existing_recipe, auto_updates, request.user)
                        messages.success(
                            request,
                            f"Auto-filled {len(auto_updates)} empty field(s) in '{existing_recipe.title}'."
                        )

                    # Save uploaded image to existing recipe if it doesn't have one
                    if image_file and not existing_recipe.image:
                        try:
                            image_file.seek(0)
                            existing_recipe.image.save(image_file.name, image_file, save=True)
                        except Exception as e:
                            logger.warning(f"Could not save image to existing recipe: {e}")

                    if conflicts:
                        # Store combined data and conflicts in session for merge confirmation
                        request.session['merge_recipe_id'] = existing_recipe.pk
                        request.session['merge_conflicts'] = _serialize_conflicts(conflicts)
                        request.session['merge_new_data'] = _serialize_new_data(combined_data)
                        # Clean up file handles
                        if image_file:
                            image_file.close()
                            gc.collect()
                            _handle_images_folder_file(original_filename, True, request)
                        return redirect('recipe_merge_confirm')
                    else:
                        # Clean up file handles
                        if image_file:
                            image_file.close()
                            gc.collect()
                            _handle_images_folder_file(original_filename, True, request)
                        return redirect('recipe_detail', pk=existing_recipe.pk)
                else:
                    # No existing recipe - create new one
                    recipe = _create_recipe_from_data(combined_data, request.user, image_file)
                    messages.success(request, f"Recipe '{recipe.title}' created successfully!")
                    # Clean up file handles AFTER saving to recipe
                    if image_file:
                        image_file.close()
                        gc.collect()
                        _handle_images_folder_file(original_filename, True, request)
                    return redirect('recipe_detail', pk=recipe.pk)

            except Exception as e:
                logger.error(f"Error during OCR upload: {e}", exc_info=True)
                messages.error(request, f'Error processing: {e}')
                # Ensure file handles are cleaned up on error
                if 'image_file' in locals() and image_file and hasattr(image_file, 'close'):
                    try:
                        image_file.close()
                    except Exception:
                        pass
    else:
        form = OCRUploadForm()

    return render(request, 'RecipeDB/ocr_upload.html', {'form': form})


def _handle_images_folder_file(original_filename, success, request):
    """Handle file management in the IMAGES folder after OCR processing."""
    if not original_filename:
        return

    images_folder = Path(getattr(settings, 'OCR_IMAGES_FOLDER', ''))
    logger.debug(f"IMAGES folder: {images_folder}, exists={images_folder.exists()}")
    if not images_folder.exists():
        return

    source_path = images_folder / original_filename
    logger.debug(f"Trying exact match: {source_path}, exists={source_path.exists()}")

    # Django sanitizes filenames (spaces → underscores), try original name
    if not source_path.exists():
        alt_name = original_filename.replace('_', ' ')
        alt_path = images_folder / alt_name
        if alt_path.exists():
            source_path = alt_path
            logger.info(f"Matched with spaces restored: {source_path}")

    # Fuzzy stem match
    if not source_path.exists():
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
        if success:
            _background_delete_file(source_path)
            messages.info(request, "Source image will be deleted from IMAGES folder.")
        else:
            err_name = f"ERR_{source_path.name}"
            err_path = images_folder / err_name
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
                _background_delete_file(source_path)
            except Exception as e:
                logger.warning(f"Could not copy source image: {e}")
                messages.warning(request, f"Could not rename source image: {e}")
    else:
        logger.warning(f"Source image not found in IMAGES folder: {original_filename}")


def _combine_ocr_and_url_data(ocr_data, url_data):
    """
    Combine OCR data and URL-scraped data, preferring URL data for structured fields.

    Args:
        ocr_data: dict from OCR processing (or None)
        url_data: dict from URL scraping (or None)

    Returns:
        dict with combined recipe data
    """
    if not ocr_data and not url_data:
        return None
    if not ocr_data:
        return url_data
    if not url_data or not url_data.get('success'):
        return ocr_data

    # URL data is generally more structured, prefer it for most fields
    combined = {}
    combined['title'] = url_data.get('title') or ocr_data.get('title', '')
    combined['instructions'] = url_data.get('instructions') or ocr_data.get('instructions', '')
    combined['ingredients'] = url_data.get('ingredients') or ocr_data.get('ingredients', [])
    combined['authors'] = url_data.get('authors') or ocr_data.get('authors', [])
    combined['genres'] = url_data.get('genres') or ocr_data.get('genres', [])
    combined['image_url'] = url_data.get('image_url') or ocr_data.get('image_url', '')
    combined['source_url'] = url_data.get('source_url') or ocr_data.get('source_url', '')
    combined['description'] = url_data.get('description') or ocr_data.get('description', '')
    combined['confidence'] = ocr_data.get('confidence', 0.0)

    return combined


def _apply_auto_updates(recipe, auto_updates, user):
    """
    Apply non-conflicting updates to an existing recipe.
    Only fills in fields that were previously empty.

    Args:
        recipe: Recipe instance
        auto_updates: dict of field_name -> new_value
        user: User performing the update
    """
    from .models import MAX_TITLE_LENGTH, MAX_NAME_LENGTH

    save_needed = False

    if 'title' in auto_updates and not recipe.title.strip():
        recipe.title = auto_updates['title'][:MAX_TITLE_LENGTH]
        save_needed = True

    if 'instructions' in auto_updates and not recipe.instructions.strip():
        recipe.instructions = auto_updates['instructions']
        save_needed = True

    if save_needed:
        recipe.save()

    if 'ingredients' in auto_updates:
        _save_ingredients_list(recipe, auto_updates['ingredients'])

    if 'authors' in auto_updates:
        for author_name in auto_updates['authors']:
            _add_author_by_name(recipe, author_name)

    if 'genres' in auto_updates:
        for genre_name in auto_updates['genres']:
            genre, _ = Genre.objects.get_or_create(
                name__iexact=genre_name, defaults={'name': genre_name}
            )
            recipe.genres.add(genre)

    if 'source_url' in auto_updates:
        _save_source_url(recipe, auto_updates['source_url'])


def _save_ingredients_list(recipe, ingredients):
    """
    Save a list of ingredient dicts to a recipe.

    Args:
        recipe: Recipe instance
        ingredients: list of dicts with name, quantity, order keys
            OR list of strings like "quantity - name"
    """
    from .models import MAX_NAME_LENGTH

    if isinstance(ingredients, list) and ingredients:
        if isinstance(ingredients[0], dict):
            for ing_data in ingredients:
                name = ing_data.get('name', '').strip().lower()[:MAX_NAME_LENGTH]
                if not name:
                    continue
                ingredient, _ = Ingredient.objects.get_or_create(name=name)
                RecipeIngredient.objects.get_or_create(
                    recipe=recipe,
                    ingredient=ingredient,
                    defaults={
                        'quantity': ing_data.get('quantity', '')[:100],
                        'order': ing_data.get('order', 0),
                    }
                )
        elif isinstance(ingredients[0], str):
            # Parse text format
            text = '\n'.join(ingredients)
            _save_ingredients_from_text(recipe, text)


def _add_author_by_name(recipe, name):
    """Add an author to a recipe by name string."""
    from .models import MAX_NAME_LENGTH

    name = name.strip()[:MAX_NAME_LENGTH]
    if not name:
        return

    author = Author.objects.filter(
        Q(publisher_name__iexact=name) |
        Q(first_name__iexact=name) |
        Q(last_name__iexact=name)
    ).first()

    if not author:
        parts = name.split(None, 1)
        if len(parts) == 2:
            author, _ = Author.objects.get_or_create(
                first_name=parts[0][:MAX_NAME_LENGTH],
                last_name=parts[1][:MAX_NAME_LENGTH],
                defaults={'publisher_name': ''}
            )
        else:
            author, _ = Author.objects.get_or_create(publisher_name=name)

    recipe.authors.add(author)


def _create_recipe_from_data(data, user, image_file=None):
    """
    Create a new Recipe from combined data dict.

    Args:
        data: dict with recipe data
        user: User creating the recipe
        image_file: Optional uploaded image file

    Returns:
        Recipe instance
    """
    from .models import MAX_TITLE_LENGTH, MAX_NAME_LENGTH

    title = data.get('title', 'Untitled Recipe')[:MAX_TITLE_LENGTH]
    instructions = data.get('instructions', '')
    if not instructions and data.get('description'):
        instructions = data['description']

    recipe = Recipe.objects.create(
        title=title,
        instructions=instructions or 'No instructions available.',
        created_by=user,
        ocr_confidence=data.get('confidence'),
        source_file=data.get('source_file', ''),
    )

    # Save image from upload
    if image_file:
        try:
            image_file.seek(0)
            recipe.image.save(image_file.name, image_file, save=True)
        except Exception as e:
            logger.warning(f"Could not save uploaded image: {e}")
    elif data.get('image_url'):
        # Try to download image from URL
        try:
            img_url = data['image_url']
            req = urllib.request.Request(
                img_url,
                headers={'User-Agent': SCRAPE_USER_AGENT}
            )
            with urllib.request.urlopen(req, timeout=SCRAPE_TIMEOUT) as resp:
                img_data = resp.read()
            # Determine filename from URL
            url_path = urllib.parse.urlparse(img_url).path
            img_name = os.path.basename(url_path) or 'recipe_image.jpg'
            from django.core.files.base import ContentFile
            recipe.image.save(img_name, ContentFile(img_data), save=True)
            logger.info(f"Downloaded recipe image from: {img_url}")
        except Exception as e:
            logger.warning(f"Could not download image from URL: {e}")

    # Add ingredients
    if data.get('ingredients'):
        _save_ingredients_list(recipe, data['ingredients'])

    # Add authors
    for author_name in data.get('authors', []):
        _add_author_by_name(recipe, author_name)

    # Add genres
    for genre_name in data.get('genres', []):
        genre_name = genre_name.strip()[:MAX_NAME_LENGTH]
        if genre_name:
            genre, _ = Genre.objects.get_or_create(
                name__iexact=genre_name, defaults={'name': genre_name}
            )
            recipe.genres.add(genre)

    # Add source URL (must be a valid web URL, not a local file path)
    source_url = data.get('source_url', '').strip()
    if source_url and source_url.lower().startswith(('http://', 'https://')):
        try:
            RecipeURL.objects.create(
                recipe=recipe,
                url=source_url,
                description='Source',
                is_primary=True,
            )
        except Exception as e:
            logger.warning(f"Could not save source URL '{source_url}': {e}")
    elif source_url:
        logger.warning(f"Ignoring non-HTTP source URL: {source_url!r}")

    return recipe


def _serialize_conflicts(conflicts):
    """Serialize conflicts dict for session storage.
    
    Lists of ingredient dicts are formatted as human-readable text for display,
    while the actual data is preserved in merge_new_data for the merge operation.
    """
    serialized = {}
    for field, data in conflicts.items():
        serialized[field] = {
            'existing': _format_conflict_value(data['existing']),
            'new': _format_conflict_value(data['new']),
        }
    return serialized


def _format_conflict_value(value):
    """Format a conflict value for human-readable display."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, dict):
                # Ingredient dict: show "quantity - name" or just "name"
                name = item.get('name', '')
                qty = item.get('quantity', '')
                if qty:
                    parts.append(f"{qty} - {name}")
                else:
                    parts.append(name)
            else:
                parts.append(str(item))
        return '\n'.join(parts)
    return str(value)


def _serialize_new_data(data):
    """Serialize scraped data for session storage."""
    serialized = {}
    for key, value in data.items():
        if isinstance(value, (str, int, float, bool, type(None))):
            serialized[key] = value
        elif isinstance(value, list):
            serialized[key] = []
            for item in value:
                if isinstance(item, dict):
                    serialized[key].append(item)
                else:
                    serialized[key].append(str(item))
        else:
            serialized[key] = str(value)
    return serialized


@login_required
def recipe_merge_confirm(request):
    """
    Show merge confirmation page when scraped data conflicts with existing recipe.
    User can choose which fields to keep (existing) or replace (new).
    """
    recipe_id = request.session.get('merge_recipe_id')
    conflicts = request.session.get('merge_conflicts', {})
    new_data = request.session.get('merge_new_data', {})

    if not recipe_id or not conflicts:
        messages.error(request, 'No merge data available.')
        return redirect('ocr_upload')

    recipe = get_object_or_404(Recipe, pk=recipe_id)

    if request.method == 'POST':
        from .models import MAX_TITLE_LENGTH, MAX_NAME_LENGTH

        # Process user's choices for each conflicting field
        updates_applied = 0
        for field in conflicts:
            choice = request.POST.get(f'choice_{field}', 'keep')
            if choice == 'replace':
                new_val = new_data.get(field, '')
                if field == 'title' and new_val:
                    recipe.title = str(new_val)[:MAX_TITLE_LENGTH]
                    recipe.save()
                    updates_applied += 1
                elif field == 'instructions' and new_val:
                    recipe.instructions = str(new_val)
                    recipe.save()
                    updates_applied += 1
                elif field == 'ingredients' and new_val:
                    if isinstance(new_val, list):
                        if new_val and isinstance(new_val[0], dict):
                            # List of ingredient dicts from URL scraping
                            RecipeIngredient.objects.filter(recipe=recipe).delete()
                            _save_ingredients_list(recipe, new_val)
                        else:
                            # List of strings
                            _save_ingredients_from_text(
                                recipe,
                                '\n'.join(str(item) for item in new_val)
                            )
                    else:
                        _save_ingredients_from_text(recipe, str(new_val))
                    updates_applied += 1
                elif field == 'authors' and new_val:
                    recipe.authors.clear()
                    if isinstance(new_val, list):
                        for name in new_val:
                            _add_author_by_name(recipe, str(name))
                    updates_applied += 1
                elif field == 'genres' and new_val:
                    recipe.genres.clear()
                    if isinstance(new_val, list):
                        for name in new_val:
                            genre, _ = Genre.objects.get_or_create(
                                name__iexact=str(name), defaults={'name': str(name)}
                            )
                            recipe.genres.add(genre)
                    updates_applied += 1
                elif field == 'source_url' and new_val:
                    _save_source_url(recipe, str(new_val))
                    updates_applied += 1

        # Clean up session
        for key in ['merge_recipe_id', 'merge_conflicts', 'merge_new_data']:
            request.session.pop(key, None)

        if updates_applied:
            messages.success(request, f"Updated {updates_applied} field(s) in '{recipe.title}'.")
        else:
            messages.info(request, "No changes were made.")

        return redirect('recipe_detail', pk=recipe.pk)

    # GET: show the merge confirmation form
    conflict_display = []
    for field, data in conflicts.items():
        conflict_display.append({
            'field': field,
            'field_label': field.replace('_', ' ').title(),
            'existing': data.get('existing', ''),
            'new': data.get('new', ''),
        })

    return render(request, 'RecipeDB/recipe_merge_confirm.html', {
        'recipe': recipe,
        'conflicts': conflict_display,
    })


def process_ocr_image(image_file, user, auto_search_web=False):
    """
    Process an image file using OCR to extract recipe information.
    Also detects URLs in the OCR text.

    Args:
        image_file: Uploaded image file
        user: User who uploaded the file
        auto_search_web: Whether to search web for additional info

    Returns:
        dict with 'success', 'recipe_data', 'raw_text', 'confidence', and 'error' keys
    """
    try:
        # Reset file pointer to the beginning
        image_file.seek(0)

        # Open and process the image
        image = Image.open(image_file)

        try:
            # Convert image to RGB if necessary
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
            return {
                'success': False,
                'error': f'OCR confidence too low: {avg_confidence:.1%}',
                'confidence': avg_confidence,
                'raw_text': text,
                'recipe_data': {},
            }

        # Extract recipe information from text
        recipe_data = extract_recipe_from_text(text)
        recipe_data['confidence'] = avg_confidence
        recipe_data['source_file'] = image_file.name

        return {
            'success': True,
            'confidence': avg_confidence,
            'raw_text': text,
            'recipe_data': recipe_data,
        }

    except Exception as e:
        logger.error(f"Error processing OCR image: {e}")
        return {
            'success': False,
            'error': str(e),
            'confidence': 0.0,
            'raw_text': '',
            'recipe_data': {},
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


def _search_recipe_on_site(title, search_url_template):
    """
    Search a specific recipe site for a recipe by title.

    Fetches the site's search results page and extracts the best
    matching recipe link from the HTML by ranking candidates on how
    many title words appear in the link text / URL.

    Args:
        title: Recipe title to search for
        search_url_template: URL template with {} placeholder for query

    Returns:
        str URL of the recipe page, or None
    """
    import urllib.request
    import urllib.parse

    # Minimum fraction of significant title words required to match
    MIN_MATCH_RATIO = 0.4
    # Absolute minimum matches regardless of title length
    MIN_ABSOLUTE_MATCHES = 2

    try:
        query = urllib.parse.quote(title)
        search_url = search_url_template.format(query)
        logger.info(f"Searching recipe site: {search_url}")

        req = urllib.request.Request(
            search_url,
            headers={
                'User-Agent': (
                    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                    'AppleWebKit/537.36 (KHTML, like Gecko) '
                    'Chrome/120.0.0.0 Safari/537.36'
                ),
                'Accept': 'text/html,application/xhtml+xml',
                'Accept-Language': 'en-US,en;q=0.9',
            },
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            html = response.read().decode('utf-8', errors='replace')

        # Parse the domain from the search URL template for link matching
        parsed = urllib.parse.urlparse(search_url_template)
        base_domain = parsed.netloc or parsed.path.split('/')[0]

        title_words = set(
            w.lower() for w in re.findall(r'\w+', title)
            if len(w) > 2
        )
        min_required = max(
            MIN_ABSOLUTE_MATCHES,
            int(len(title_words) * MIN_MATCH_RATIO),
        )

        # Navigation / non-recipe URL path segments to skip
        skip_patterns = (
            '/search', '/category', '/tag/', '/author/',
            '/page/', '/about', '/contact', '/privacy',
            '/terms', '/newsletter', '/subscribe',
            '?s=', '?q=', '?search=',
        )

        def _score_link(href, text_content):
            """Return (match_count, href) or None if link should be skipped."""
            # Make absolute URL
            if href.startswith('/'):
                href = f"{parsed.scheme}://{base_domain}{href}"
            if not href.startswith('http'):
                return None
            # Must be on the same site
            link_domain = urllib.parse.urlparse(href).netloc
            if base_domain not in link_domain:
                return None
            if any(pat in href.lower() for pat in skip_patterns):
                return None
            # Must have at least one path segment
            path = urllib.parse.urlparse(href).path
            segments = [s for s in path.split('/') if s]
            if not segments:
                return None
            combined = (text_content or '').lower() + ' ' + href.lower()
            # Use word-boundary matching (not substring) to avoid
            # false positives like "red" in "sun-dried"
            combined_words = set(re.findall(r'\w+', combined))
            matches = sum(1 for w in title_words if w in combined_words)
            return (matches, href)

        candidates = []  # list of (match_count, href)

        # Use BeautifulSoup if available, otherwise fall back to regex
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'html.parser')
            seen_hrefs = set()
            for link in soup.find_all('a', href=True):
                result = _score_link(link['href'], link.get_text())
                if result and result[1] not in seen_hrefs:
                    seen_hrefs.add(result[1])
                    candidates.append(result)
        except ImportError:
            # Fallback: use regex to find links
            link_pattern = re.compile(
                rf'href=["\']'
                rf'(https?://[^"\']*{re.escape(base_domain)}[^"\']*)'
                rf'["\']',
                re.IGNORECASE,
            )
            seen_hrefs = set()
            for match in link_pattern.finditer(html):
                href = match.group(1)
                result = _score_link(href, '')
                if result and result[1] not in seen_hrefs:
                    seen_hrefs.add(result[1])
                    candidates.append(result)

        if not candidates:
            logger.info(f"No candidate links found on site for '{title}'")
            return None

        # Sort by match count descending, pick the best
        candidates.sort(key=lambda x: x[0], reverse=True)
        best_matches, best_href = candidates[0]

        if best_matches >= min_required:
            logger.info(
                f"Found recipe on site: {best_href} "
                f"({best_matches}/{len(title_words)} title words matched)"
            )
            return best_href

        logger.info(
            f"Best candidate '{best_href}' only matched "
            f"{best_matches}/{len(title_words)} words "
            f"(need {min_required}); skipping"
        )
        return None

    except Exception as e:
        logger.warning(f"Site search for '{title}' failed: {e}")
        return None


def extract_recipe_from_text(text):
    """
    Extract structured recipe data from OCR text.

    Uses multi-pass heuristics to identify recipe sections:
    1. Filter out web-page noise (navigation, ads, breadcrumbs)
    2. Detect section headers (Ingredients, Instructions/Directions, Author, etc.)
    3. Identify ingredient lines by measurement keywords and patterns
    4. Identify the title from the first prominent non-noise line
    5. Remaining text becomes instructions

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
        'ingredients': [],
        'genres': [],
        'source_url': '',
        'description': '',
    }

    if not lines:
        return recipe_data

    try:
        # ---- Web-page noise patterns (to skip for title selection) ----
        # Breadcrumb navigation (e.g., "FOOD > RECIPES > SOUPS")
        BREADCRUMB_RE = re.compile(r'(?:>|›|»)\s*\w+.*(?:>|›|»)', re.IGNORECASE)
        # Common website navigation / header words
        NAV_KEYWORDS = {
            'advertisement', 'advertise', 'ad', 'menu', 'subscribe', 'sign in',
            'sign up', 'login', 'log in', 'newsletter', 'search', 'privacy',
            'cookie', 'cookies', 'terms', 'about us', 'contact', 'share',
            'copyright', 'all rights reserved', 'skip to content',
            'skip to main', 'close', 'trending', 'popular', 'latest',
        }
        # Navigation bar pattern: multiple short uppercase words separated by spaces
        NAV_BAR_RE = re.compile(
            r'^(?:[A-Z]{2,}\s+){2,}[A-Z]{2,}$'
        )
        # Rating/review noise (e.g., "1.5(2) 2 REVIEWS", "★★★")
        RATING_RE = re.compile(
            r'(?:★|☆|\breviews?\b|\bratings?\b|\bstars?\b|\d+\s*\(\d+\))',
            re.IGNORECASE,
        )
        # Very short lines that are likely OCR noise or site branding
        # (e.g., "FOOD< WINE", "F&W", "NYT")
        BRAND_RE = re.compile(
            r'^[A-Z\s<>&|/\\]{2,30}$'
        )

        def _is_noise_line(line):
            """Check if a line is likely web-page noise rather than recipe content."""
            lower = line.lower().strip()
            # Exact match of common noise
            if lower in NAV_KEYWORDS:
                return True
            # Breadcrumb navigation
            if BREADCRUMB_RE.search(line):
                return True
            # All-caps navigation bar
            if NAV_BAR_RE.match(line):
                return True
            # Short branding text in all caps with punctuation
            if len(line) < 30 and BRAND_RE.match(line):
                return True
            # Contains multiple nav keywords (whole-word matching to
            # avoid false positives like "cookies" in recipe titles)
            line_words = set(re.findall(r'\w+', lower))
            nav_hits = sum(
                1 for kw in NAV_KEYWORDS
                if set(kw.split()) <= line_words
            )
            if nav_hits >= 2:
                return True
            # Rating/review lines
            if RATING_RE.search(line) and len(line) < 60:
                return True
            return False

        # ---- Section header detection ----
        SECTION_PATTERNS = {
            'ingredients': re.compile(
                r'^\s*(?:ingredients|ingredienser|ainekset|zutaten|ingrédients)\s*:?\s*$',
                re.IGNORECASE,
            ),
            'instructions': re.compile(
                r'^\s*(?:instructions?|directions?|method|preparation|steps|valmistusohje|ohje|zubereitung)\s*:?\s*$',
                re.IGNORECASE,
            ),
            'author': re.compile(
                r'^\s*(?:by|author|chef|recipe\s+by|from|kirjoittanut)\s*:?\s*',
                re.IGNORECASE,
            ),
        }

        # Measurement / ingredient line patterns
        MEASUREMENT_RE = re.compile(
            r'(?:^|\s)'
            r'(?:\d+[\s/\-\.½¼¾⅓⅔⅛]*'
            r'(?:cups?|tablespoons?|tbsp|teaspoons?|tsp|grams?|g\b|kg\b|'
            r'ml\b|dl\b|l\b|oz\b|ounces?|lb|lbs|pounds?|pieces?|pcs|'
            r'pinch|cloves?|bunch|cans?|sticks?|slices?|large|medium|small|whole))',
            re.IGNORECASE,
        )
        # Bullet or numbered list item (common in ingredient lists)
        BULLET_RE = re.compile(r'^\s*(?:[\-\*•·]|\d+[\)\.]?)\s+')
        # Fraction at start
        FRACTION_RE = re.compile(
            r'^\s*(?:\d+\s*/\s*\d+|\d+\.\d+|[½¼¾⅓⅔⅛]|\d+\s*[½¼¾⅓⅔⅛])\s+',
        )

        # ---- Classify each line ----
        # States: 'unknown', 'title', 'ingredients', 'instructions', 'author'
        current_section = 'unknown'
        title_candidates = []
        ingredient_lines = []
        instruction_lines = []
        author_lines = []
        unknown_lines = []  # lines before any section header
        noise_lines = []    # web-page noise

        for line in lines:
            # Check for section headers
            matched_section = None
            for sec_name, sec_re in SECTION_PATTERNS.items():
                if sec_re.search(line):
                    matched_section = sec_name
                    break

            if matched_section == 'author':
                current_section = 'author'
                # The header line itself may contain the author name
                cleaned = SECTION_PATTERNS['author'].sub('', line).strip()
                if cleaned:
                    author_lines.append(cleaned)
                continue
            elif matched_section:
                current_section = matched_section
                continue

            # Dispatch to current section
            if current_section == 'ingredients':
                ingredient_lines.append(line)
            elif current_section == 'instructions':
                instruction_lines.append(line)
            elif current_section == 'author':
                author_lines.append(line)
            else:
                unknown_lines.append(line)

        # ---- If no section headers found, use heuristic classification ----
        if not ingredient_lines and not instruction_lines:
            for line in unknown_lines:
                if MEASUREMENT_RE.search(line) or FRACTION_RE.match(line):
                    ingredient_lines.append(line)
                elif BULLET_RE.match(line) and len(line) < 120:
                    # Short bulleted items are likely ingredients
                    ingredient_lines.append(BULLET_RE.sub('', line).strip())
                else:
                    title_candidates.append(line)
        else:
            title_candidates = unknown_lines

        # ---- Extract title ----
        # Strategy 1: Look for a line right after breadcrumbs/noise that
        #             looks like a recipe title (substantial, not noise).
        #             Multi-line titles are common in OCR ("Shorbet Ads (Egyptian Red\nLentil Soup)")
        found_breadcrumb = False
        post_breadcrumb_lines = []
        for candidate in title_candidates:
            stripped = candidate.strip()
            if not stripped:
                continue
            if _is_noise_line(stripped):
                if BREADCRUMB_RE.search(stripped):
                    found_breadcrumb = True
                noise_lines.append(stripped)
                continue
            if found_breadcrumb:
                post_breadcrumb_lines.append(stripped)

        # If we found lines after a breadcrumb, combine adjacent short lines
        # as a multi-line title (common in OCR of webpages)
        if post_breadcrumb_lines:
            # Combine consecutive short lines that form the title
            title_parts = []
            for pbl in post_breadcrumb_lines:
                if URL_REGEX.match(pbl) or pbl.lower().startswith('http'):
                    break
                if _is_noise_line(pbl):
                    break
                # Stop at a very long line (likely description, not title)
                if len(pbl) > 80 and title_parts:
                    break
                title_parts.append(pbl)
                combined = ' '.join(title_parts)
                # Check if title appears complete:
                # - Has at least MIN_TITLE_LENGTH chars
                # - No unmatched parentheses/brackets (continuation signal)
                MIN_TITLE_LENGTH = 10
                has_unmatched = (
                    combined.count('(') != combined.count(')') or
                    combined.count('[') != combined.count(']')
                )
                if len(combined) >= MIN_TITLE_LENGTH and not has_unmatched:
                    break
            if title_parts:
                recipe_data['title'] = ' '.join(title_parts)
                # Remove used lines from title_candidates
                for tp in title_parts:
                    if tp in title_candidates:
                        title_candidates.remove(tp)

        # Strategy 2: Fallback — first non-noise, non-URL, substantial line
        if not recipe_data['title']:
            for candidate in title_candidates:
                stripped = candidate.strip()
                if not stripped:
                    continue
                # Skip URLs
                if URL_REGEX.match(stripped) or stripped.lower().startswith('http'):
                    continue
                # Skip noise lines
                if _is_noise_line(stripped):
                    noise_lines.append(stripped)
                    continue
                # Skip very short lines (likely OCR noise)
                if len(stripped) < 3:
                    continue
                # A reasonable title is < ~120 chars
                if len(stripped) <= 120:
                    recipe_data['title'] = stripped
                    title_candidates.remove(candidate)
                    break

        # ---- Build instructions from remaining title_candidates + instruction_lines ----
        all_instructions = []
        # Lines before ingredients that weren't chosen as title (skip noise)
        for candidate in title_candidates:
            stripped = candidate.strip()
            if stripped and not MEASUREMENT_RE.search(stripped) and stripped not in noise_lines:
                all_instructions.append(stripped)
        all_instructions.extend(instruction_lines)
        recipe_data['instructions'] = '\n'.join(all_instructions).strip()

        # ---- Parse ingredient lines ----
        for idx, line in enumerate(ingredient_lines):
            # Remove bullet / numbering prefix
            clean = BULLET_RE.sub('', line).strip()
            if not clean:
                continue
            # Try to separate quantity from name
            qty_match = re.match(
                r'^(\d[\d\s/\.½¼¾⅓⅔⅛]*\s*'
                r'(?:cups?|tablespoons?|tbsp|teaspoons?|tsp|grams?|g\b|kg\b|'
                r'ml\b|dl\b|l\b|oz\b|ounces?|lb|lbs|pounds?|pieces?|pcs|'
                r'pinch|cloves?|bunch|cans?|sticks?|slices?|large|medium|small|whole)?)'
                r'\s+(.+)',
                clean,
                re.IGNORECASE,
            )
            if qty_match:
                recipe_data['ingredients'].append({
                    'name': qty_match.group(2).strip(),
                    'quantity': qty_match.group(1).strip(),
                    'order': idx,
                })
            else:
                # Try simple "number name" split
                parts = clean.split(None, 1)
                if len(parts) == 2 and any(c.isdigit() for c in parts[0]):
                    recipe_data['ingredients'].append({
                        'name': parts[1],
                        'quantity': parts[0],
                        'order': idx,
                    })
                else:
                    recipe_data['ingredients'].append({
                        'name': clean,
                        'quantity': '',
                        'order': idx,
                    })

        # ---- Authors ----
        for a in author_lines:
            a = a.strip()
            if a and len(a) > 1:
                recipe_data['authors'].append(a)

        # ---- Extract URLs from the text and set source_url ----
        all_urls = _extract_urls_from_text(text)
        if all_urls:
            recipe_data['source_url'] = all_urls[0]

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
