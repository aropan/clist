import uuid

from django.contrib import admin
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from my_oauth.models import Credential, Form, Service, Token
from true_coders.models import Coder


class CredentialImportTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser(username="credential-import-admin")
        Coder.objects.create(user=cls.user)
        cls.service = Service.objects.create(name="credential-import-provider", user_id_field="id")
        cls.form = Form.objects.create(name="Import destination", service=cls.service, code="")
        cls.other_form = Form.objects.create(name="Other form", service=cls.service, code="")

    def setUp(self):
        self.model_admin = admin.site._registry[Credential]
        self.url = reverse("admin:my_oauth_credential_import")
        self.client.force_login(self.user)

    def request(self, content=None, extension="txt", **data):
        if content is None:
            return self.client.get(self.url)
        formats = self.model_admin.get_import_formats()
        data["format"] = next(i for i, fmt in enumerate(formats) if fmt().get_title() == extension)
        data["import_file"] = SimpleUploadedFile(f"credentials.{extension}", content.encode("utf-8"))
        return self.client.post(self.url, data)

    def credentials(self, form=None):
        return dict(Credential.objects.filter(form=form or self.form).values_list("login", "password"))

    def test_import_page_offers_form_selection_and_txt(self):
        response = self.request()

        self.assertContains(response, 'name="form"')
        self.assertContains(response, self.form.name)
        self.assertContains(response, self.other_form.name)
        self.assertContains(response, ">txt</option>")
        assert all(fmt().get_title() != "txt" for fmt in self.model_admin.get_export_formats())

    def test_txt_imports_every_line_into_selected_form(self):
        response = self.request(
            '\ufefffirst,first-password\r\n\r\n"логин,2","пароль,2"\r\nlast, spaced password \r\n',
            form=str(self.form.pk),
        )

        assert response.status_code == 302
        assert self.credentials() == {
            "first": "first-password",
            "логин,2": "пароль,2",
            "last": " spaced password ",
        }
        assert not Credential.objects.exclude(form=self.form).exists()
        assert set(Credential.objects.values_list("state", flat=True)) == {Credential.State.UNASSIGNED}

    def test_csv_without_form_column_uses_selected_form(self):
        response = self.request("login,password\naccount,test-password\n", extension="csv", form=str(self.form.pk))

        assert response.status_code == 302
        assert self.credentials() == {"account": "test-password"}

    def test_selected_form_overrides_file_column(self):
        response = self.request(
            f"form,login,password\n{self.other_form.pk},account,test-password\n",
            extension="csv",
            form=str(self.form.pk),
        )

        assert response.status_code == 302
        assert self.credentials() == {"account": "test-password"}
        assert not self.credentials(self.other_form)

    def test_existing_csv_import_with_form_column_still_works(self):
        response = self.request(
            f"form,login,password\n{self.form.pk},first,first-password\n{self.other_form.pk},second,second-password\n",
            extension="csv",
        )

        assert response.status_code == 302
        assert self.credentials() == {"first": "first-password"}
        assert self.credentials(self.other_form) == {"second": "second-password"}

    def test_reimport_updates_password_only_in_selected_form(self):
        token = Token.objects.create(service=self.service, user_id="assigned-user")
        existing = Credential.objects.create(
            form=self.form,
            login="account",
            password="old-password",
            token=token,
            state=Credential.State.ASSIGNED,
        )
        Credential.objects.create(form=self.other_form, login="account", password="other-password")

        response = self.request("account,new-password\n", form=str(self.form.pk))

        assert response.status_code == 302
        existing.refresh_from_db()
        assert existing.password == "new-password"
        assert existing.token == token
        assert existing.state == Credential.State.ASSIGNED
        assert self.credentials(self.other_form) == {"account": "other-password"}
        assert Credential.objects.count() == 2

    def test_txt_without_selected_form_reports_error(self):
        response = self.request("account,test-password\n")

        assert response.status_code == 200
        assert "form" in response.context_data["form"].errors
        assert not Credential.objects.exists()

    def test_invalid_form_is_rejected_before_import(self):
        for form in ("invalid-uuid", str(uuid.uuid4())):
            with self.subTest(form=form):
                response = self.request("account,test-password\n", form=form)

                assert response.status_code == 200
                assert "form" in response.context_data["form"].errors
                assert not Credential.objects.exists()

    def test_malformed_txt_rejects_entire_file(self):
        for row in ("missing-password", "too,many,columns", ",password", "login,", 'login,"unclosed'):
            with self.subTest(row=row):
                response = self.request(f"valid,test-password\n{row}\n", form=str(self.form.pk))

                assert response.status_code == 200
                assert "import_file" in response.context_data["form"].errors
                assert not Credential.objects.exists()

    def test_duplicate_logins_roll_back_entire_import(self):
        response = self.request("account,first-password\naccount,second-password\n", form=str(self.form.pk))

        assert response.status_code == 200
        assert "import_file" in response.context_data["form"].errors
        assert not Credential.objects.exists()
