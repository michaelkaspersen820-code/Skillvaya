import urllib.request,json
base='http://127.0.0.1:8877'
def get(path):
    with urllib.request.urlopen(base+path,timeout=5) as r:return r.status,r.read().decode()
def post(path,data):
    with urllib.request.urlopen(urllib.request.Request(base+path,data=json.dumps(data).encode(),headers={'Content-Type':'application/json'},method='POST'),timeout=5) as r:return r.status,r.read().decode()
page=get('/')[1]
print('PAGE_OK',len(page)>10000)
print('TERMS_TAB', 'Terms, rules & safety' in page)
print('TERMS_CONTENT', 'Privacy and communications' in page)
print('ADMIN_METRICS_TAB', 'Downloads & usage' in page)
print('CATEGORIES',get('/api/categories')[0])
print('MANIFEST',get('/manifest.json')[0])
print('ANALYTICS_WRITE',post('/api/analytics',{'event':'visit','detail':'desktop'})[0])
for route in ['/api/admin/analytics','/api/admin/clients','/api/admin/settings','/api/admin/notifications']:
 try: print(route,get(route)[0])
 except Exception as e: print(route,'PROTECTED',getattr(e,'code','error'))
