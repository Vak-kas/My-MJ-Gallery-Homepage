from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User


class UserForm(UserCreationForm):
    email = forms.EmailField(label="이메일", required=True)

    class Meta:
        model = User
        fields = ("username", "password1", "password2", "email")

    def clean_email(self):
        email = self.cleaned_data.get("email")

        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("이미 사용 중인 이메일입니다.")

        return email

