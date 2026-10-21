import app
from pathlib import Path
s=Path('app.py').read_text(encoding='utf-8')
checks={
 'owner_shell_defined':'OWNER_APP_HTML = r"""' in s,
 'owner_home_default':'owner_app_html = OWNER_APP_HTML.encode()' in s,
 'customer_route':'if path=="/customer":' in s,
 'terms_route':'if path=="/terms":' in s,
 'login_terms_notice':'agreeTerms' in app.LOGIN_GATEWAY_HTML,
 'terms_route':'if path=="/terms":' in s,
 'login_terms_notice':'agreeTerms' in app.LOGIN_GATEWAY_HTML,
 'owner_route':'if path=="/owner-app":' in s,
 'owner_control_tab':'data-tab="control"' in app.OWNER_APP_HTML,
 'back_button':'Back to Owner App' in app.OWNER_APP_HTML,
 'customer_app_retained':'Create account' in app.HTML and 'loginTerms' in app.HTML,
 'owner_control_back':'Back to Owner App</button>' in app.OWNER_HTML,
 'paypal_sandbox_messaging':'PayPal Sandbox only.' in app.OWNER_APP_HTML,
}
for k,v in checks.items(): print(('PASS' if v else 'FAIL'),k)
if not all(checks.values()): raise SystemExit(1)
