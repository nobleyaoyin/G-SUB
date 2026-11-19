import { afterEach, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import CaptchaWidget from './CaptchaWidget';

afterEach(() => { cleanup(); delete window.hcaptcha; document.getElementById('gsub-hcaptcha-script')?.remove(); });

it('provides only provider-issued challenge responses and clears expired responses', () => {
  const onToken = vi.fn(); let options;
  window.hcaptcha = { render: vi.fn((_element, settings) => { options = settings; return 7; }), remove: vi.fn() };
  const view = render(<CaptchaWidget siteKey="synthetic-site" onToken={onToken} />);
  expect(screen.getByLabelText('CAPTCHA challenge')).toBeTruthy();
  expect(options.sitekey).toBe('synthetic-site');
  options.callback('synthetic-challenge'); expect(onToken).toHaveBeenLastCalledWith('synthetic-challenge');
  options['expired-callback'](); expect(onToken).toHaveBeenLastCalledWith(null);
  view.unmount(); expect(window.hcaptcha.remove).toHaveBeenCalledWith(7);
});
