"""CAPTCHA checks use synthetic records and a mocked provider, never network."""
import os
import httpx
from unittest.mock import patch, Mock

from app.security import hash_password
from tests.test_reviewer_download import ReviewerDownloadsTest
import app.routers.users as users


class CaptchaAuthenticationTests(ReviewerDownloadsTest):
    def setUp(self):
        super().setUp()
        self.env = patch.dict(os.environ, {'GSUB_CAPTCHA_MODE': 'hcaptcha', 'GSUB_CAPTCHA_SITE_KEY': 'synthetic-site',
            'GSUB_CAPTCHA_SECRET': 'synthetic-secret', 'GSUB_CAPTCHA_HOSTNAME': 'synthetic.example'}, clear=False)
        self.env.start(); self.addCleanup(self.env.stop)
        self.no_demo = patch.object(users, 'IS_DEMO', False); self.no_demo.start(); self.addCleanup(self.no_demo.stop)
        self.editor.password_hash = hash_password('Synthetic-password-123')
        self.db.commit()
        users._login_attempts.clear()

    def login(self, token=None):
        return self.client.post('/users/login', json={'email': self.editor.email, 'password': 'Synthetic-password-123', 'captcha_token': token})

    @staticmethod
    def response(body):
        response = Mock(); response.json.return_value = body; response.raise_for_status.return_value = None
        return response

    def test_missing_or_invalid_challenge_rejected(self):
        with patch('app.captcha.httpx.post') as provider:
            self.assertEqual(self.login().status_code, 400)
            provider.assert_not_called()
            self.assertEqual(self.login(True).status_code, 422)
            provider.assert_not_called()
            provider.return_value = self.response({'success': False, 'hostname': 'synthetic.example'})
            self.assertEqual(self.login('synthetic-response').status_code, 400)
            provider.return_value = self.response({'success': True, 'hostname': 'wrong.example'})
            self.assertEqual(self.login('synthetic-response').status_code, 400)

    def test_success_preserves_existing_role_and_password(self):
        with patch('app.captcha.httpx.post', return_value=self.response({'success': True, 'hostname': 'synthetic.example'})) as provider:
            result = self.login('synthetic-response')
            self.assertEqual(provider.call_args.kwargs['data']['sitekey'], 'synthetic-site')
        self.assertEqual(result.status_code, 200, result.text)
        self.db.expire_all(); self.assertEqual(self.db.get(type(self.editor), self.editor.user_id).role, 'editor')
        self.assertEqual(self.client.get('/users/auth-options').json()['captcha'], {'provider':'hcaptcha','site_key':'synthetic-site'})

    def test_registration_checks_captcha_before_creating_account(self):
        payload = {'name':'Synthetic author','email':'new-author@example.com','password':'Synthetic-password-123'}
        with patch('app.captcha.httpx.post') as provider:
            response = self.client.post('/users/register', json=payload)
            self.assertEqual(response.status_code,400)
            provider.assert_not_called()
        with patch('app.captcha.httpx.post', return_value=self.response({'success':True,'hostname':'synthetic.example'})), \
             patch.object(users,'prepare_registration_verification',return_value='synthetic-token'), \
             patch.object(users,'deliver_registration_verification'):
            response = self.client.post('/users/register', json={**payload,'captcha_token':'synthetic-response'})
        self.assertEqual(response.status_code,201,response.text)
        self.assertEqual(response.json()['role'],'author')

    def test_partial_configuration_fails_closed(self):
        with patch.dict(os.environ, {'GSUB_CAPTCHA_SECRET':''}):
            self.assertEqual(self.login('synthetic-response').status_code,503)
            self.assertEqual(self.client.get('/users/auth-options').status_code,503)

    def test_provider_failure_fails_closed(self):
        with patch('app.captcha.httpx.post', side_effect=httpx.ConnectError('synthetic failure')):
            self.assertEqual(self.login('synthetic-response').status_code,503)

    def test_disabled_preserves_password_login(self):
        with patch.dict(os.environ, {'GSUB_CAPTCHA_MODE':'off'}):
            self.assertEqual(self.login().status_code,200)
