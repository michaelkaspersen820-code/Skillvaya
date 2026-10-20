import urllib.request
base='http://127.0.0.1:8877'
landing=urllib.request.urlopen(base+'/').read().decode()
page=urllib.request.urlopen(base+'/customer').read().decode()
owner=urllib.request.urlopen(base+'/owner-control').read().decode()
print('LANDING_PAGE', len(landing)>1000)
print('SIGNUP_CHECKBOX', 'name="accept_terms"' in page)
print('OWNER_PAGE', 'Owner Control' in owner)
for route in ['/api/admin/summary','/api/admin/clients','/api/admin/settings','/api/admin/notifications','/api/admin/analytics']:
    try:
        r=urllib.request.urlopen(base+route,timeout=5)
        print(route,r.status)
    except Exception as e: print(route,'FAIL',e)
