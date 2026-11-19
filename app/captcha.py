"""Optional server-side hCaptcha verification; disabled unless explicitly configured."""
import os

import httpx
from fastapi import HTTPException


def configuration():
    mode = os.environ.get('GSUB_CAPTCHA_MODE', 'off').strip().lower()
    if mode == 'off':
        return None
    if mode != 'hcaptcha':
        raise HTTPException(503, 'CAPTCHA configuration unavailable')
    sitekey = os.environ.get('GSUB_CAPTCHA_SITE_KEY', '').strip()
    secret = os.environ.get('GSUB_CAPTCHA_SECRET', '').strip()
    hostname = os.environ.get('GSUB_CAPTCHA_HOSTNAME', '').strip().lower()
    if not sitekey or not secret or not hostname or any(c in hostname for c in '/:?# '):
        raise HTTPException(503, 'CAPTCHA configuration unavailable')
    return sitekey, secret, hostname


def public_options():
    config = configuration()
    return {'provider': 'hcaptcha', 'site_key': config[0]} if config else {'provider': 'disabled'}


def verify(token):
    config = configuration()
    if config is None:
        return
    if not isinstance(token, str) or not token.strip() or len(token) > 4096:
        raise HTTPException(400, 'Complete the CAPTCHA challenge and try again')
    try:
        response = httpx.post('https://hcaptcha.com/siteverify', data={'secret': config[1], 'sitekey': config[0], 'response': token}, timeout=5.0, follow_redirects=False)
        response.raise_for_status()
        result = response.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(503, 'CAPTCHA verification is unavailable; please try again later') from None
    if not isinstance(result, dict) or result.get('success') is not True or not isinstance(result.get('hostname'), str) or result['hostname'].lower() != config[2]:
        raise HTTPException(400, 'CAPTCHA verification failed; please try again')
