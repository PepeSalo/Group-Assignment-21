    ## Aim of the project
    RecipeDB web app using the latest version of Django web programming, Sqlite3 as database and Tesseract for Optical Character Recognition (OCR). The end result aims to be user-friendly, responsive and have WCAG 2.1 compliant contrast in both light and dark mode (including link and button and UI element colors should have high enough contrast).
    ## Programming practices
    Use best programming practices. Include comprehensive error checking by default. Use constants instead of magic values. Keep the code short and elegant. Use class-based generic views when applicable.
    Make sure all the templates inherit from base template, which is responsive and supports both light and dark mode.
    ## Test code
    Include comprehensive test code, which checks the following:
    - Chinese and Arabic text for input and output strings
    - very large and very small positive and negative numbers for numbers
    - decimal numbers for floating point numbers
    - database access, file loading and saving might fail for multiple reasons (incorrect path and file name, lack of privilege, corrupted content, out of disk space, internet connection errors)
    ## Documentation
    Update Readme.md automatically to explain the main features of the program, including some examples.
    update TODO.md to keep up a list of features still to implement or fix
