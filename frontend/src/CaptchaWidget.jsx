import { useEffect, useRef, useState } from 'react';

// The provider script is loaded only when the server explicitly enables CAPTCHA.
export default function CaptchaWidget({ siteKey, onToken }) {
  const container = useRef(null);
  const onTokenRef = useRef(onToken);
  const [error, setError] = useState('');
  useEffect(() => { onTokenRef.current = onToken; }, [onToken]);
  useEffect(() => {
    const controller = new AbortController();
    const instance = { widget: undefined };
    const render = () => {
      if (controller.signal.aborted || !container.current || !window.hcaptcha || instance.widget !== undefined) return;
      instance.widget = window.hcaptcha.render(container.current, {
        sitekey: siteKey,
        callback: token => onTokenRef.current(token),
        'expired-callback': () => onTokenRef.current(null),
        'error-callback': () => { onTokenRef.current(null); setError('CAPTCHA is unavailable. Please try again later.'); },
      });
    };
    let script = document.getElementById('gsub-hcaptcha-script');
    if (!script) {
      script = document.createElement('script');
      script.id = 'gsub-hcaptcha-script';
      script.src = 'https://js.hcaptcha.com/1/api.js?render=explicit';
      script.async = true;
      script.defer = true;
      document.head.appendChild(script);
    }
    script.addEventListener('load', render);
    const failed = () => setError('CAPTCHA is unavailable. Please try again later.');
    script.addEventListener('error', failed);
    render();
    return () => {
      controller.abort();
      script.removeEventListener('load', render);
      script.removeEventListener('error', failed);
      if (instance.widget !== undefined && window.hcaptcha) window.hcaptcha.remove(instance.widget);
    };
  }, [siteKey]);
  return <div className="form-group"><p>Complete the CAPTCHA challenge to continue.</p><div ref={container} aria-label="CAPTCHA challenge" />{error && <p role="alert">{error}</p>}</div>;
}
