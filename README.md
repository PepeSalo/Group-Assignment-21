# RecipeDB - Recipe Database Management System

RecipeDB is a comprehensive web application built with Django 6.0.2 that allows users to manage, search, and rate recipes. It includes advanced features like Optical Character Recognition (OCR) for extracting recipe data from images, automatic web search for recipe sources, and intelligent file management for processed images.

## Features

### Core Functionality
- **User Authentication**: Sign up, login, and logout functionality
- **Recipe Management**: Create, read, update, and delete recipes
- **Permission-Based Access Control**:
  - Recipe creators can always edit/delete their own recipes
  - Other users need Django group/user permissions (`change_recipe`, `delete_recipe`)
  - Edit/Delete buttons hidden in UI when user lacks permission
- **Advanced Search**: Search recipes by title, author, genre, ingredients, and ratings
- **Rating System**: 
  - Published ratings (from cookbooks, websites, etc.)
  - Personal user ratings with notes
- **OCR Integration**: Upload images and automatically extract recipe data using Tesseract OCR
- **Multi-language Support**: Fully supports Unicode text including Chinese, Arabic, and other languages

### OCR & Image Processing
- **Tesseract OCR**: Extracts recipe text (title, ingredients, instructions) from uploaded images
- **Confidence Scoring**: Configurable threshold (default 40%) determines OCR success/failure
- **URL-First Approach**: When a URL is detected in an OCR image and "search web" is enabled, the system scrapes the URL first (using the superior URL-based extraction) before falling back to OCR text parsing
- **Improved Text Extraction**: Multi-pass heuristic parser that detects section headers (Ingredients, Instructions, Author), measurement patterns, bullet/numbered lists, and fraction notation for more accurate recipe extraction from OCR text
- **Web-Page Noise Filtering**: Automatically filters out website navigation bars, breadcrumbs (e.g., "FOOD > RECIPES > SOUPS"), brand text (e.g., "FOOD< WINE"), ratings/reviews, and ad keywords so that the actual recipe title is extracted instead of site branding
- **Multi-Line Title Detection**: Combines adjacent short lines with unmatched parentheses as a single title (e.g., "Shorbet Ads (Egyptian Red\nLentil Soup)" → "Shorbet Ads (Egyptian Red Lentil Soup)")
- **Known Recipe Site Detection**: Detects ~20 major recipe websites (Food & Wine, Allrecipes, Bon Appétit, Epicurious, Simply Recipes, etc.) from OCR-captured branding text
- **Site-Specific Recipe Search**: When a known recipe site is detected, searches the site's own search page and tries slug-based URL construction to find the original recipe page
- **URL Detection in Images**: OCR scans images for URLs and automatically repairs common OCR artifacts (missing `://`, extra spaces, spurious uppercase letters)
- **Automatic File Management**:
  - **On success**: Source image is deleted from the IMAGES folder (via background thread)
  - **On failure**: Source image is renamed with `ERR_` prefix, original is deleted in background
  - Background thread retries deletion up to 30 times (2-second intervals) to handle file locks from antivirus, Windows Explorer thumbnails, or similar processes
  - Uploaded images are saved to the recipe's `media/recipes/` folder
- **Image Download from URL**: When URL scraping finds a recipe image URL, it is automatically downloaded and saved to the recipe
- **Web Search Integration**: Optionally searches DuckDuckGo for recipe URLs on successful OCR
- **Smart Filename Matching**: Handles Django's filename sanitization (spaces → underscores) with multi-strategy matching (exact, spaces-restored, fuzzy stem matching)

### URL Scraping & Web Import
- **Recipe URL Scraping**: Paste a URL to automatically import recipe data from any web page
- **Multi-Strategy Extraction**:
  1. **JSON-LD** (schema.org Recipe): Structured data extraction – highest quality
  2. **BeautifulSoup HTML Parsing**: Parses common recipe CSS classes, Open Graph, and meta tags
  3. **Regex Fallback**: Extracts title, description, and image from meta tags without BeautifulSoup
- **Extracted Data**: Title, instructions, ingredients (with quantities), authors, genres/categories, image URL, source URL, description
- **Data Merge Protection**: When scraped data matches an existing recipe:
  - Empty fields are auto-filled without user intervention
  - Fields with conflicting data require user confirmation via a side-by-side comparison UI
  - Users choose "Keep Existing" or "Replace with New" for each conflicting field
- **OCR + URL Combination**: When an image contains a URL, both OCR text and URL-scraped data are combined, preferring structured URL data for ingredients and instructions

### Recipe Editing
- **Text-Based Ingredient Entry**: Enter ingredients as `quantity - name (notes)`, one per line
  ```
  2 cups - flour
  1 tsp - salt (fine)
  3 - eggs
  ```
- **Text-Based Authors**: Enter one author per line, auto-creates new authors
  ```
  Julia Child
  Jacques Pépin
  ```
- **Text-Based Genres**: Enter one genre per line, auto-creates new genres
- **Source URL**: Associate a primary URL with each recipe

### Database Models
- **Author**: Supports both individual authors (first/last name) and publishers
- **Genre**: Categorize recipes by cuisine type or category
- **Ingredient**: Track all ingredients used across recipes
- **Recipe**: Main recipe model with title, instructions, images, and OCR metadata
- **RecipeIngredient**: Junction table linking recipes to ingredients with quantities, notes, and ordering
- **PublishedRating**: Professional ratings with review text and source URLs
- **PersonalRating**: User-generated ratings with personal notes (one per user per recipe)
- **RecipeURL**: Multiple URLs can be associated with each recipe

### User Interface
- **Responsive Design**: Works seamlessly on desktop, tablet, and mobile devices
- **Dark/Light Mode**: Automatic theme switching based on system preferences with manual toggle
- **WCAG 2.1 AA Compliant**: High contrast colors for accessibility in both themes
- **Intuitive Navigation**: Clean and modern interface
- **No Inline CSS**: All styles use CSS classes defined in per-page `<style>` blocks via `{% block extra_css %}`, keeping templates clean and maintainable

### Admin Interface
- **Comprehensive Django Admin**: Full-featured admin panel for managing all models
- **Inline Editing**: Manage ingredients, ratings, and URLs directly from recipe pages
- **Advanced Filtering**: Filter recipes by author, genre, date, and OCR confidence
- **Search Functionality**: Quick search across all relevant fields
- **Visual Indicators**: Color-coded OCR confidence scores and rating displays
- **Safe HTML Formatting**: All admin display methods pre-format numeric values before passing to `format_html`, avoiding `SafeString` format code errors

## Installation

### Prerequisites
- Python 3.14+ (tested with 3.14.2)
- Tesseract OCR installed on your system
  - **Windows**: Download from [GitHub](https://github.com/UB-Mannheim/tesseract/wiki)
  - **Linux**: `sudo apt-get install tesseract-ocr`
  - **macOS**: `brew install tesseract`

### Setup Steps

1. **Clone or download the project**
   ```bash
   cd "Group Assignment 21"
   ```

2. **Create and activate virtual environment** (already configured)
   ```bash
   # Virtual environment is at .venv/
   ```

3. **Install dependencies** (already installed)
   - Django 6.0.2
   - Pillow 12.1.1
   - pytesseract
   - beautifulsoup4 (for HTML parsing of recipe URLs)

4. **Configure Tesseract path** (if needed)
   
   Edit `mysite/mysite/settings.py` and update the `TESSERACT_CMD` path:
   ```python
   TESSERACT_CMD = r'C:\Program Files\Tesseract-OCR\tesseract.exe'  # Windows
   # or
   TESSERACT_CMD = '/usr/bin/tesseract'  # Linux/Mac
   ```

5. **Configure OCR images folder** (if needed)

   Set the folder where recipe images are placed for OCR processing:
   ```python
   OCR_IMAGES_FOLDER = Path(r'C:\Temp\IMAGES')  # Default
   OCR_CONFIDENCE_THRESHOLD = 0.4  # 40% minimum confidence
   ```

6. **Run migrations**
   ```bash
   cd mysite
   python manage.py makemigrations
   python manage.py migrate
   ```

7. **Create superuser**
   ```bash
   python manage.py createsuperuser
   ```

8. **Run the development server**
   ```bash
   python manage.py runserver
   ```

9. **Access the application**
   - Main site: http://127.0.0.1:8000/
   - Admin panel: http://127.0.0.1:8000/admin/

## Usage Examples

### Creating a Recipe Manually

1. Sign up or log in to your account
2. Click "Add Recipe" in the navigation bar
3. Fill in the recipe details:
   - Title: "Chocolate Chip Cookies"
   - Instructions: "Mix all ingredients... Bake at 350°F for 12 minutes..."
   - Select authors and genres
   - Upload an image (optional)
4. Click "Create Recipe"
5. Add ingredients via the admin panel or API

### Using OCR to Add Recipes

1. Log in to your account
2. Click "OCR Upload" in the navigation bar
3. Choose one or both input methods:
   - **Image upload**: Select a JPG or PNG image containing a recipe
   - **Recipe URL**: Paste a URL to a recipe web page
4. Optionally enable "Search web for additional information"
5. Click "Upload and Process"
6. The system will:
   - Extract text using Tesseract OCR (if image provided)
   - Detect and repair URLs found in the OCR text
   - Scrape recipe data from the provided or detected URL
   - Combine OCR and URL data (structured URL data preferred)
   - Check for existing recipes by URL or title
   - **If no match**: Create a new recipe automatically
   - **If match found**: Auto-fill empty fields, then show merge confirmation for conflicting fields
   - On success: delete original image from IMAGES folder (background)
   - On failure: rename to `ERR_filename.png` and delete original (background)

### Importing Recipes from URLs

1. Log in and go to "OCR Upload"
2. Paste a recipe URL (e.g., `https://www.feastingathome.com/kung-pao-chicken/`)
3. Click "Upload and Process"
4. The system extracts recipe data (title, ingredients, instructions, author, etc.)
5. If the recipe already exists, you'll see a merge confirmation page
6. Choose which fields to keep or replace, then confirm

**Supported URL formats:**
- Pages with JSON-LD structured data (most recipe blogs) – best results
- Pages with standard HTML meta tags and Open Graph data
- Any web page with a `<title>` tag (minimal extraction)

### Editing a Recipe

1. Open any recipe you created
2. Click "Edit" (only visible for recipes you own)
3. Edit fields using text-based inputs:
   - **Ingredients**: Enter `quantity - name (notes)`, one per line
   - **Authors**: Enter one author per line (auto-creates new entries)
   - **Genres**: Enter one genre per line (auto-creates new entries)
   - **Source URL**: Paste a recipe URL
4. Click "Update Recipe"

### Searching for Recipes

1. Navigate to "Browse Recipes"
2. Use the search form:
   - **General Query**: Search across title, author, and ingredients
   - **Author**: Filter by specific author name
   - **Genre**: Select from dropdown menu
   - **Ingredient**: Search by ingredient name
   - **Minimum Rating**: Filter by rating threshold (1-5)
3. Click "Search" or "Clear" to reset

### Rating a Recipe

1. Open any recipe detail page
2. Scroll to the "Your Rating" section (login required)
3. Enter a score (1-5) and optional notes
4. Click "Submit Rating" or "Update Rating"
5. Your rating will be reflected in the community average

### Managing Recipes via Admin

1. Access the admin panel at `/admin/`
2. Log in with superuser credentials
3. Navigate to "Recipes"
4. Click on any recipe to edit
5. Use inline forms to add:
   - Ingredients with quantities and notes
   - URLs with descriptions
   - Published ratings with review text

## Database Schema

### Key Relationships
- Recipe ↔ Author (Many-to-Many)
- Recipe ↔ Genre (Many-to-Many)
- Recipe ↔ Ingredient (Many-to-Many through RecipeIngredient)
- Recipe → PersonalRating (One-to-Many)
- Recipe → PublishedRating (One-to-Many)
- Recipe → RecipeURL (One-to-Many)

### Indexes
Database indexes are strategically placed on:
- Author names (first_name, last_name, publisher_name)
- Genre and Ingredient names
- Recipe title and creation date
- Recipe-User combinations for ratings
- OCR confidence scores

## Testing

The project includes comprehensive test coverage:

```bash
cd mysite
python manage.py test RecipeDB
```

Test coverage includes:
- ✅ Chinese and Arabic text input/output (all models)
- ✅ Very large and very small positive/negative numbers
- ✅ Decimal number handling (OCR confidence values)
- ✅ Database constraints and validation
- ✅ User authentication flows (login, signup, logout)
- ✅ Recipe CRUD operations
- ✅ Permission-based edit/delete access control
- ✅ Text-based ingredient/author/genre parsing
- ✅ Source URL validation
- ✅ Search functionality (multi-language)
- ✅ Rating system (personal and published)
- ✅ OCR processing workflow
- ✅ Background file deletion (threaded)
- ✅ File management (ERR_ rename, delete on success)
- ✅ Error handling and edge cases
- ✅ URL extraction from OCR text (clean, garbled, www-only)
- ✅ OCR URL repair (missing ://, spaces, uppercase artifacts)
- ✅ JSON-LD recipe extraction (multiple formats, @graph, list types)
- ✅ HTML cleaning and entity decoding
- ✅ Recipe data merging (auto-updates vs conflicts)
- ✅ Combined OCR + URL data merging
- ✅ Recipe creation from scraped data
- ✅ Merge confirmation view (keep/replace per field)
- ✅ URL scraping with mocked HTTP responses
- ✅ OCR upload form validation (image or URL required)
- ✅ Serialization for session storage
- ✅ Web-page noise filtering (breadcrumbs, nav bars, brand text, ratings)
- ✅ Multi-line title combining with unmatched parenthesis detection
- ✅ Known recipe site detection from OCR branding text
- ✅ Slug-based URL generation and title-to-slug conversion

## Technology Stack

- **Framework**: Django 6.0.2
- **Database**: SQLite3
- **OCR**: Tesseract 5.4.0 with pytesseract
- **Image Processing**: Pillow 12.1.1
- **HTML Parsing**: BeautifulSoup 4 (beautifulsoup4)
- **Web Scraping**: JSON-LD (schema.org), Open Graph, meta tags, regex fallback
- **Web Search**: DuckDuckGo Instant Answer API (no API key required)
- **Frontend**: Responsive HTML5/CSS3 with vanilla JavaScript
- **Design**: Custom CSS with CSS variables for theming (light/dark mode), per-page `{% block extra_css %}` style blocks (no inline styles)

## Accessibility

- WCAG 2.1 AA compliant color contrast ratios
- Keyboard navigation support
- Screen reader friendly
- Responsive design for all device sizes
- Clear visual feedback for all interactions

## Security Considerations

- CSRF protection enabled
- Password validation with Django validators
- SQL injection prevention through Django ORM
- XSS protection through Django template escaping
- Secure file upload handling
- Permission-based recipe edit/delete (owner or Django permission required)
- Edit/Delete buttons hidden for unauthorized users

## Project Structure

```
mysite/
├── manage.py
├── mysite/
│   ├── settings.py      # Configuration
│   ├── urls.py          # Main URL routing
│   └── wsgi.py
└── RecipeDB/
    ├── models.py        # Database models
    ├── views.py         # View logic
    ├── forms.py         # Form definitions
    ├── admin.py         # Admin configuration
    ├── tests.py         # Test suite
    ├── urls.py          # App URL routing
    └── templates/       # HTML templates
        └── RecipeDB/
            ├── base.html              # Base template
            ├── home.html              # Homepage
            ├── login.html             # Login page
            ├── signup.html            # Registration
            ├── recipe_list.html       # Recipe browsing
            ├── recipe_detail.html     # Recipe details
            ├── recipe_form.html       # Create/edit recipe
            ├── recipe_confirm_delete.html
            ├── recipe_merge_confirm.html  # Data merge confirmation
            ├── ocr_upload.html        # OCR upload & URL scraping
            ├── author_list.html       # Authors
            ├── ingredient_list.html   # Ingredients
            └── genre_list.html        # Genres
```

## Future Enhancements

See [TODO.md](TODO.md) for planned features and improvements.

## License

This project is created as an educational assignment for HAMK University.

## Contributors

Group Assignment 21 - HAMK

## Support

For issues or questions, please refer to the project documentation or contact the development team.

---

**Note**: This is a development version. For production deployment, ensure you:
- Change the SECRET_KEY in settings.py
- Set DEBUG = False
- Configure allowed hosts
- Use a production database (PostgreSQL recommended)
- Set up proper static file serving
- Configure HTTPS
- Implement rate limiting for OCR uploads
