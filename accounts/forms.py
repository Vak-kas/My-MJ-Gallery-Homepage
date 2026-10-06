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

        # 대소문자만 다른 같은 주소로 여러 계정을 만들지 못하게 함
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("이미 사용 중인 이메일입니다.")

        return email

