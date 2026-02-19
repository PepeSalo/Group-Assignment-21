# TODO List - RecipeDB

## High Priority

### OCR Enhancements
- [x] ~~Implement web search functionality to find updated recipe images and information~~ (DuckDuckGo API)
- [x] ~~Add automatic file renaming with ERR_ prefix for failed OCR and deletion for successful OCR~~
- [x] ~~Configure OCR confidence threshold (set to 40%)~~
- [x] ~~Handle file locks from antivirus/Explorer with background thread deletion~~
- [x] ~~URL detection in OCR images with automatic repair of OCR artifacts~~
- [x] ~~URL scraping: import recipe data from pasted URLs (JSON-LD, BeautifulSoup, regex fallback)~~
- [x] ~~Merge confirmation UI: keep/replace per field when scraped data conflicts with existing recipe~~
- [x] ~~Auto-fill empty recipe fields from scraped data without user confirmation~~
- [x] ~~Combined OCR + URL data merging (URL data preferred for structured fields)~~
- [x] ~~URL-first OCR approach: when URL found in image + web search enabled, use URL scraping before OCR text extraction~~
- [x] ~~Improved OCR text extraction: multi-pass heuristic parser with section headers, measurement patterns, bullets, fractions~~
- [x] ~~Fix merge TypeError when ingredients are dicts (from URL scraping) instead of strings~~
- [x] ~~Fix image file management: save uploaded image to recipe before closing file handle~~
- [x] ~~Add image URL download: save scraped image_url to recipe image field~~
- [x] ~~Proper conflict display: format ingredient dicts as human-readable "quantity - name" text~~
- [x] ~~URL validation: reject non-HTTP paths (media files, local paths) from being stored as RecipeURLs~~
- [x] ~~Prominent source URL display: show source URL in recipe info card and link image to source~~
- [x] ~~Web-page noise filtering: skip breadcrumbs, nav bars, brand text, ratings for title extraction~~
- [x] ~~Multi-line title combining with unmatched parenthesis detection~~
- [x] ~~Known recipe site detection from OCR branding text (Food & Wine, Allrecipes, Bon Appétit, etc.)~~
- [x] ~~Site-specific recipe search: search on detected site and slug-based URL guessing~~
- [ ] Add support for handwritten recipe recognition
- [ ] Implement batch OCR processing for multiple images
- [ ] Add OCR language selection (currently English only)
- [ ] Improve URL scraping for non-recipe pages (news articles, blogs)

### Search & Filtering
- [ ] Add autocomplete for search fields
- [ ] Implement tag-based searching
- [ ] Add "Recently Viewed" recipes
- [ ] Create "Favorite Recipes" functionality
- [ ] Add ability to save custom searches
- [ ] Implement full-text search with ranking

### User Features
- [ ] Add user profiles with profile pictures
- [ ] Implement recipe collections/cookbooks
- [ ] Add recipe sharing via email/social media
- [ ] Create shopping list generation from recipe ingredients
- [ ] Add nutrition information tracking
- [ ] Implement meal planning calendar
- [ ] Add cooking timer integration

### Recipe Management
- [x] ~~Add text-based ingredient editing (quantity - name (notes) format)~~
- [x] ~~Add text-based author editing (auto-create new authors)~~
- [x] ~~Add text-based genre editing (auto-create new genres)~~
- [x] ~~Add source URL field to recipe form~~
- [ ] Add recipe versioning/history
- [ ] Implement recipe forks/variations
- [ ] Add step-by-step photo gallery for instructions
- [ ] Create video upload support
- [ ] Add cooking difficulty level field
- [ ] Implement preparation and cooking time fields
- [ ] Add serving size calculator

## Medium Priority

### Admin & Management
- [ ] Add bulk import/export for recipes (CSV, JSON)
- [ ] Implement recipe moderation queue
- [ ] Add activity logs for admin actions
- [ ] Create backup/restore functionality
- [ ] Add statistics dashboard for admins

### API Development
- [ ] Create RESTful API for mobile app integration
- [ ] Add API authentication with tokens
- [ ] Implement GraphQL endpoint
- [ ] Create API documentation with Swagger/OpenAPI

### Performance
- [ ] Implement Redis caching for frequently accessed recipes
- [ ] Add database query optimization
- [ ] Implement lazy loading for images
- [ ] Add CDN support for static files
- [ ] Optimize database indexes further

### Testing
- [x] ~~Increase test coverage with URL scraping, merge, and OCR URL detection tests (235 tests)~~
- [x] ~~Added noise filtering tests, site detection tests, slug generation tests (284 tests)~~
- [ ] Increase test coverage to >90%
- [ ] Add integration tests for OCR workflow
- [ ] Implement end-to-end testing with Selenium
- [ ] Add performance testing suite
- [ ] Create load testing scenarios

## Low Priority

### Internationalization
- [ ] Add multi-language support (i18n)
- [ ] Create translation system for recipes
- [ ] Add RTL (Right-to-Left) layout support
- [ ] Implement locale-specific date/time formatting
- [ ] Add currency conversion for ingredient costs

### Social Features
- [ ] Implement commenting system on recipes
- [ ] Add user following/followers
- [ ] Create recipe recommendation engine
- [ ] Add "Recipe of the Day" feature
- [ ] Implement user achievements/badges
- [ ] Create cooking challenges/competitions

### Mobile
- [ ] Create progressive web app (PWA)
- [ ] Develop native mobile apps (iOS/Android)
- [ ] Add offline mode support
- [ ] Implement push notifications

### Advanced Features
- [ ] AI-powered recipe suggestions based on available ingredients
- [ ] Add dietary restrictions and allergen filtering
- [ ] Implement cost calculation for recipes
- [ ] Create seasonal ingredient recommendations
- [ ] Add equipment/utensil tracking
- [ ] Implement recipe difficulty assessment

### UI/UX Improvements
- [ ] Add recipe print-friendly view
- [ ] Implement voice-controlled recipe reading
- [ ] Create interactive cooking mode
- [ ] Add recipe card generator for sharing
- [ ] Implement advanced filtering with sliders and ranges
- [ ] Add image gallery/carousel for recipes

### Integration
- [ ] Connect with grocery delivery APIs
- [ ] Integrate with smart kitchen devices
- [ ] Add calendar app integration
- [ ] Implement import from popular recipe websites
- [ ] Create browser extension for recipe clipping

## Bug Fixes

- [x] ~~Handle edge cases in OCR text extraction~~ (truncation, confidence threshold)
- [x] ~~Fix rating save error (get_or_create without default score)~~
- [x] ~~Fix file lock errors during OCR rename/delete (background thread)~~
- [x] ~~Fix Django filename sanitization (spaces → underscores) in OCR file matching~~
- [x] ~~Fix recipe delete/edit permissions (any logged-in user could delete)~~ — now requires ownership or Django permission
- [x] ~~Fix recipe form field order (instructions was above ingredients)~~
- [x] ~~Fix trailing punctuation not stripped from OCR-detected URLs~~
- [ ] Fix potential race conditions in rating updates
- [ ] Improve error messages for failed file uploads
- [ ] Add validation for image file sizes
- [ ] Fix pagination issues with filtered searches

## Documentation

- [ ] Create user guide with screenshots
- [ ] Add video tutorials for key features
- [ ] Create API documentation
- [ ] Write deployment guide for production
- [ ] Add contributing guidelines
- [ ] Create architecture documentation

## Security

- [x] ~~Add permission checks for recipe edit/delete (owner or Django permission)~~
- [ ] Implement rate limiting for API endpoints
- [ ] Add two-factor authentication (2FA)
- [ ] Implement account recovery via email
- [ ] Add CAPTCHA for registration
- [ ] Create audit log system
- [ ] Implement data export for GDPR compliance
- [ ] Add content security policy headers

## Performance Monitoring

- [ ] Add application monitoring (e.g., Sentry)
- [ ] Implement analytics tracking
- [ ] Create performance metrics dashboard
- [ ] Add error tracking and reporting
- [ ] Implement uptime monitoring

## Known Issues

1. OCR accuracy varies significantly with image quality
2. ~~Web search feature not yet implemented~~ ✅ Done (DuckDuckGo API)
3. ~~File renaming with I/U prefix not yet implemented~~ ✅ Done (ERR_ prefix for failures, delete for successes)
4. Large image uploads may timeout
5. Search results could be slow with large databases
6. Background file deletion may take up to 60 seconds if file is locked by external process
7. OCR URL repair may not fix all OCR artifacts (e.g., character substitutions in domain names)
8. URL scraping depends on page structure; non-standard recipe pages may yield minimal data

## Recently Completed ✅

- ✅ Django project and app setup
- ✅ Database models with proper relationships
- ✅ User authentication (login, logout, signup)
- ✅ Recipe CRUD operations
- ✅ Advanced search functionality
- ✅ Rating system (published and personal)
- ✅ OCR upload basic functionality
- ✅ Comprehensive admin interface
- ✅ Responsive design with dark/light mode
- ✅ WCAG 2.1 AA compliant styling
- ✅ Comprehensive test suite
- ✅ Database indexing for common queries
- ✅ Multi-language text support (Chinese, Arabic, etc.)
- ✅ Text-based ingredient/author/genre editing in recipe form
- ✅ Source URL field for recipes
- ✅ DuckDuckGo web search for recipe URLs on OCR upload
- ✅ OCR file management: delete on success, ERR_ rename on failure
- ✅ Background thread file deletion to handle Windows file locks
- ✅ Smart filename matching (exact, spaces-restored, fuzzy stem)
- ✅ Configurable OCR confidence threshold (40%)
- ✅ PIL image handle cleanup to prevent file locking
- ✅ Tesseract OCR 5.4.0 integration on Windows
- ✅ Permission-based recipe edit/delete (owner or group permission)
- ✅ Recipe form field order: Title → Authors → Genres → Ingredients → Instructions → URL → Image
- ✅ URL scraping: import recipes from web pages (JSON-LD, BS4, regex fallback)
- ✅ OCR URL detection with automatic repair of OCR artifacts
- ✅ Merge confirmation UI for conflicting data (side-by-side keep/replace)
- ✅ Auto-fill empty recipe fields from scraped data
- ✅ Combined OCR + URL data merging with URL data preferred
- ✅ beautifulsoup4 dependency added for HTML parsing
- ✅ OCRUploadForm: supports URL-only, image-only, or both
- ✅ recipe_merge_confirm view with session-based conflict storage
- ✅ 235 comprehensive tests (up from 115)

## Notes

- Priority levels may change based on user feedback
- Security fixes will always take highest priority
- Performance optimizations should be benchmarked
- All new features should include tests
- Documentation should be updated with each release

---

Last Updated: February 19, 2026
