import os,sqlite3,tempfile
import app

def main():
    os.environ.pop('DATABASE_URL',None)
    os.environ.pop('SKILLVAYA_OWNER_EMAIL',None)
    os.environ.pop('SKILLVAYA_OWNER_PASSWORD',None)
    app.DB=os.path.join(tempfile.gettempdir(),'skillvaya_owner_promotion_legacy_migration.sqlite3')
    try: os.remove(app.DB)
    except OSError: pass
    app.SESSIONS.clear(); app.init()
    with app.conn() as c:
        owner_id=c.execute("INSERT INTO users(name,email,password_hash,role,created_at,phone,accepted_terms_version,accepted_terms_at) VALUES(?,?,?,?,?,?,?,?) RETURNING id",('Migration Owner','migration-owner@example.test',app.hashpw('MigrationOwnerPass123'),'admin',app.now(),'','owner',app.now())).fetchone()['id']
        business_id=c.execute("INSERT INTO businesses(user_id,name,category,area,phone,whatsapp,email,website,description,photos,plan,billing,status,payment_status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,'local','monthly','active','verified',?) RETURNING id",(owner_id,'Legacy Owner Plumbing','Plumbers','Pretoria','+27120000000','+27820000000','legacy-owner@example.test','','Legacy description','',app.now())).fetchone()['id']
        promo_id=c.execute("INSERT INTO owner_promotions(kind,business_name,title,category,description,target_url,image_url,status,owner_free,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?) RETURNING id",('business','Legacy Owner Plumbing','Legacy Owner Plumbing','Plumbers','Legacy description','','','paused',1,app.now(),app.now())).fetchone()['id']
    with sqlite3.connect(app.DB) as c: c.execute('ALTER TABLE owner_promotions DROP COLUMN directory_business_id')
    app.init()
    with app.conn() as c:
        cols=app.table_columns(c,'owner_promotions')
        promo=c.execute('SELECT directory_business_id,status FROM owner_promotions WHERE id=?',(promo_id,)).fetchone()
        business=c.execute('SELECT status,area,phone,whatsapp,email FROM businesses WHERE id=?',(business_id,)).fetchone()
    assert 'directory_business_id' in cols,cols
    assert promo['directory_business_id']==business_id,(promo,business_id)
    assert business['status']=='suspended',dict(business)
    assert business['area']=='Pretoria' and business['phone']=='+27120000000',dict(business)
    print('PASS legacy migration adds owner directory link, backfills the matching listing, and preserves pause state/contact data')
if __name__=='__main__': main()
