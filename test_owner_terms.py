import urllib.request
base='http://127.0.0.1:8877'
page=urllib.request.urlopen(base+'/').read().decode()
owner=urllib.request.urlopen(base+'/owner-control').read().decode()
print('SIGNUP_CHECKBOX', 'name="accept_terms"' in page)
print('OWNER_PAGE', 'Owner Control' in owner)
for route in ['/api/admin/summary','/api/admin/clients','/api/admin/settings','/api/admin/notifications','/api/admin/analytics']:
    try:
        r=urllib.request.urlopen(base+route,timeout=5)
        print(route,r.status)
    except Exception as e: print(route,'FAIL',e)
