# TODO List - RecipeDB

## High Priority

### OCR Enhancements
- [x] ~~Implement web search functionality to find updated recipe images and information~~ (DuckDuckGo API)
- [x] ~~Add automatic file renaming with ERR_ prefix for failed OCR and deletion for successful OCR~~
- [x] ~~Configure OCR confidence threshold (set to 40%)~~
- [x] ~~Handle file locks from antivirus/Explorer with background thread deletion~~
- [ ] Improve OCR text extraction with NLP for better ingredient and instruction parsing
- [ ] Add support for handwritten recipe recognition
- [ ] Implement batch OCR processing for multiple images
- [ ] Add OCR language selection (currently English only)

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

## Notes

- Priority levels may change based on user feedback
- Security fixes will always take highest priority
- Performance optimizations should be benchmarked
- All new features should include tests
- Documentation should be updated with each release

---

Last Updated: February 18, 2026
