from django import forms
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from .models import (
    Recipe, Author, Genre, Ingredient, RecipeIngredient,
    PersonalRating, PublishedRating, RecipeURL
)


class CustomUserCreationForm(UserCreationForm):
    """Enhanced user registration form with email."""
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'form-control',
            'placeholder': 'Email address'
        })
    )
    
    class Meta:
        model = User
        fields = ('username', 'email', 'password1', 'password2')
        widgets = {
            'username': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Username'
            })
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['password1'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Password'
        })
        self.fields['password2'].widget.attrs.update({
            'class': 'form-control',
            'placeholder': 'Confirm password'
        })

    def clean_email(self):
        """Ensure email is unique."""
        email = self.cleaned_data.get('email')
        if email and User.objects.filter(email=email).exists():
            raise ValidationError('This email address is already in use.')
        return email

    def save(self, commit=True):
        """Save user with email."""
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        if commit:
            user.save()
        return user


class CustomAuthenticationForm(AuthenticationForm):
    """Custom login form with styled inputs."""
    username = forms.CharField(
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Username'
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            'class': 'form-control',
            'placeholder': 'Password'
        })
    )


class RecipeSearchForm(forms.Form):
    """Advanced recipe search form with multiple filters."""
    query = forms.CharField(
        required=False,
        max_length=200,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Search by title, author, or ingredients...'
        })
    )
    
    author = forms.CharField(
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Author name'
        })
    )
    
    genre = forms.ModelChoiceField(
        queryset=Genre.objects.all(),
        required=False,
        empty_label='All genres',
        widget=forms.Select(attrs={'class': 'form-control'})
    )
    
    ingredient = forms.CharField(
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ingredient name'
        })
    )
    
    min_rating = forms.IntegerField(
        required=False,
        min_value=1,
        max_value=5,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'placeholder': 'Min rating (1-5)'
        })
    )


class PersonalRatingForm(forms.ModelForm):
    """Form for users to rate recipes."""
    class Meta:
        model = PersonalRating
        fields = ['score', 'notes']
        widgets = {
            'score': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 1,
                'max': 5,
                'placeholder': 'Rating (1-5)'
            }),
            'notes': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 4,
                'placeholder': 'Your notes about this recipe (optional)'
            })
        }
        labels = {
            'score': 'Your Rating',
            'notes': 'Personal Notes'
        }


class RecipeForm(forms.ModelForm):
    """Form for creating and editing recipes."""
    
    ingredients_text = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 8,
            'placeholder': 'One ingredient per line, format:\nquantity - ingredient name\n\nExamples:\n2 cups - flour\n500g - chicken breast\n1 tablespoon - olive oil'
        }),
        label='Ingredients',
        help_text='One ingredient per line. Use "quantity - name" format (e.g., "2 cups - flour").'
    )
    
    authors_text = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'One author per line.\nExamples:\nJohn Smith\nBBC Good Food'
        }),
        label='Authors',
        help_text='One author per line. New authors are created automatically.'
    )
    
    genres_text = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'rows': 3,
            'placeholder': 'One genre per line.\nExamples:\nDessert\nItalian\nMain Course'
        }),
        label='Genres',
        help_text='One genre per line. New genres are created automatically.'
    )
    
    source_url = forms.URLField(
        required=False,
        widget=forms.URLInput(attrs={
            'class': 'form-control',
            'placeholder': 'https://example.com/recipe'
        }),
        label='Source URL',
        help_text='URL of the original recipe source (e.g., website where recipe was found).'
    )
    
    class Meta:
        model = Recipe
        fields = ['title', 'instructions', 'image']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Recipe title'
            }),
            'instructions': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 10,
                'placeholder': 'Step-by-step cooking instructions'
            }),
            'image': forms.FileInput(attrs={
                'class': 'form-control'
            })
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Pre-populate text fields from existing recipe data
        if self.instance and self.instance.pk:
            from .models import RecipeIngredient
            # Pre-populate ingredients
            ingredients = RecipeIngredient.objects.filter(
                recipe=self.instance
            ).select_related('ingredient').order_by('order')
            lines = []
            for ri in ingredients:
                if ri.quantity:
                    line = f"{ri.quantity} - {ri.ingredient.name}"
                else:
                    line = ri.ingredient.name
                if ri.notes:
                    line += f" ({ri.notes})"
                lines.append(line)
            self.fields['ingredients_text'].initial = '\n'.join(lines)
            
            # Pre-populate authors
            authors = self.instance.authors.all()
            self.fields['authors_text'].initial = '\n'.join(
                str(a) for a in authors
            )
            
            # Pre-populate genres
            genres = self.instance.genres.all()
            self.fields['genres_text'].initial = '\n'.join(
                g.name for g in genres
            )
            
            # Pre-populate source URL (use primary URL if available)
            from .models import RecipeURL
            primary_url = RecipeURL.objects.filter(
                recipe=self.instance, is_primary=True
            ).first()
            if not primary_url:
                primary_url = RecipeURL.objects.filter(
                    recipe=self.instance
                ).first()
            if primary_url:
                self.fields['source_url'].initial = primary_url.url


class RecipeIngredientForm(forms.ModelForm):
    """Form for adding ingredients to recipes."""
    class Meta:
        model = RecipeIngredient
        fields = ['ingredient', 'quantity', 'notes', 'order']
        widgets = {
            'ingredient': forms.Select(attrs={
                'class': 'form-control'
            }),
            'quantity': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., 2 cups, 500g'
            }),
            'notes': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'e.g., chopped, diced'
            }),
            'order': forms.NumberInput(attrs={
                'class': 'form-control',
                'min': 0
            })
        }


class RecipeURLForm(forms.ModelForm):
    """Form for adding URLs to recipes."""
    class Meta:
        model = RecipeURL
        fields = ['url', 'description', 'is_primary']
        widgets = {
            'url': forms.URLInput(attrs={
                'class': 'form-control',
                'placeholder': 'https://example.com/recipe'
            }),
            'description': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Description of URL'
            }),
            'is_primary': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            })
        }


class AuthorForm(forms.ModelForm):
    """Form for creating and editing authors."""
    class Meta:
        model = Author
        fields = ['first_name', 'last_name', 'publisher_name']
        widgets = {
            'first_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'First name'
            }),
            'last_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Last name'
            }),
            'publisher_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Publisher name'
            })
        }
        help_texts = {
            'first_name': 'For individual authors',
            'last_name': 'For individual authors',
            'publisher_name': 'For publisher/organization authors'
        }


class IngredientForm(forms.ModelForm):
    """Form for creating and editing ingredients."""
    class Meta:
        model = Ingredient
        fields = ['name', 'description']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ingredient name'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Optional description'
            })
        }


class GenreForm(forms.ModelForm):
    """Form for creating and editing genres."""
    class Meta:
        model = Genre
        fields = ['name', 'description']
        widgets = {
            'name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Genre name'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Optional description'
            })
        }


class OCRUploadForm(forms.Form):
    """Form for uploading images for OCR processing."""
    image_file = forms.ImageField(
        required=False,
        widget=forms.FileInput(attrs={
            'class': 'form-control',
            'accept': 'image/jpeg,image/png'
        }),
        help_text='Upload a JPG or PNG image containing a recipe'
    )

    recipe_url = forms.URLField(
        required=False,
        widget=forms.URLInput(attrs={
            'class': 'form-control',
            'placeholder': 'https://example.com/recipe'
        }),
        label='Recipe URL',
        help_text='Paste a recipe URL to scrape recipe data from the web page'
    )

    auto_search_web = forms.BooleanField(
        required=False,
        initial=False,
        widget=forms.CheckboxInput(attrs={
            'class': 'form-check-input'
        }),
        label='Search web for additional information',
        help_text='Search the web for the same recipe to find additional images and data'
    )

    def clean(self):
        """Ensure at least one of image_file or recipe_url is provided."""
        cleaned = super().clean()
        image_file = cleaned.get('image_file')
        recipe_url = cleaned.get('recipe_url')
        if not image_file and not recipe_url:
            raise ValidationError(
                'Please provide either an image file or a recipe URL (or both).'
            )
        return cleaned
