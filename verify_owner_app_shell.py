import app
from pathlib import Path
s=Path('app.py').read_text(encoding='utf-8')
checks={
 'owner_shell_defined':'OWNER_APP_HTML = r"""' in s,
 'owner_home_default':'owner_app_html = OWNER_APP_HTML.encode()' in s,
 'customer_route':'if path in ("/customer","/customer-app"):' in s,
 'terms_route':'if path in ("/terms"' in s,
 'login_terms_notice':'agreeTerms' in app.LOGIN_GATEWAY_HTML,
 'owner_route':'if path=="/owner-app":' in s,
 'owner_promotions_navigation':'showArea(\'owner-promotions\')' in app.OWNER_APP_HTML and 'function renderPromotions' in app.OWNER_APP_HTML,
 'owner_navigation':'id="ownerNav"' in app.OWNER_APP_HTML and 'showArea(\'dashboard\')' in app.OWNER_APP_HTML and 'showArea(\'payments\')' in app.OWNER_APP_HTML,
 'customer_app_retained':'Create profile' in app.HTML and 'loginTerms' in app.HTML,
 'owner_control_back':'Back to Owner App</button>' in app.OWNER_HTML,
 'paypal_checkout_messaging':'showArea(\'payments\')' in app.OWNER_APP_HTML and 'PayPal payment requests & refunds' in app.OWNER_HTML and 'PayPal confirms' in app.OWNER_HTML,
 'professional_owner_ui':'Complete control. A stronger platform.' in app.OWNER_APP_HTML and 'Skillvaya 1.1 visual finishing layer' in app.HTML,
}
for k,v in checks.items(): print(('PASS' if v else 'FAIL'),k)
if not all(checks.values()): raise SystemExit(1)
