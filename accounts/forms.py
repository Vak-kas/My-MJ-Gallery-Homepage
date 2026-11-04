from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User


class UserForm(UserCreationForm):
    email = forms.EmailField(label="이메일", required=True)
    real_name = forms.CharField(label="이름", required=True, max_length=30)
    message = forms.CharField(label="가입 인사", required=False, max_length=300)
    privacy_agree = forms.BooleanField(
        label="개인정보 수집·이용 동의", required=True,
        error_messages={"required": "개인정보 수집·이용에 동의해야 가입할 수 있습니다."},
    )

    class Meta:
        model = User
        fields = ("username", "password1", "password2", "email")

    def clean_email(self):
        email = self.cleaned_data.get("email")

        if User.objects.filter(email=email).exists():
            raise forms.ValidationError("이미 사용 중인 이메일입니다.")

        return email

    def clean_real_name(self):
        name = " ".join((self.cleaned_data.get("real_name") or "").split())
        if len(name) < 2:
            raise forms.ValidationError("이름을 정확히 입력해 주세요.")
        return name


class FindIdForm(forms.Form):
    real_name = forms.CharField(label="이름", max_length=30)
    email = forms.EmailField(label="가입할 때 쓴 이메일")


class DeleteAccountForm(forms.Form):
    password = forms.CharField(label="비밀번호", widget=forms.PasswordInput)
    agree = forms.BooleanField(label="작성한 글·댓글·저장한 자료가 모두 지워지는 것을 확인했어요", required=True)
