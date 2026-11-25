# عروض أونلاين — 3rde.online

موقع مقارنة أسعار موبايلات في مصر — جوميا مصر / أمازون مصر / نون مصر — مع تحديث
كل ساعة من Google Sheet، وروابط أفلييت، وكوبونات، وأدلة شراء، وقسم أخبار.

Price comparison website for smartphones in Egypt (Jumia Egypt / Amazon Egypt /
Noon Egypt), synced hourly from a Google Sheet, with affiliate links, coupons,
buying guides and a news section.

## النشر (Coolify)

راجع `docs/coolify-deploy.md` — مستودع Git ← تطبيق Dockerfile (nginx) ←
النطاق `3rde.online` مع SSL مجاني. المزامنة كل ساعة عبر `scripts/vps-sync.sh`
على الـ VPS (يسحب، يشغّل `scripts/sync.py`، ويرفع التغييرات فيعيد Coolify النشر).

## البنية

- `site/` — الموقع المبني (HTML ثابت، جاهز للنشر)
- `scripts/` — المولّد `build.py` + المزامنة `sync.py` + أدوات مساعدة
- `admin/` — لوحة التحكم (Google Apps Script `Code.gs` + `index.html`)
- `templates/` — قوالب أزرار الشراء وغيرها
- `docs/` — خطة SEO، دليل الأفلييت، دليل النشر، التدقيق، الصفحات القانونية
- `settings.json` — إعدادات الموقع (الوسوم، الإعلانات، الإشعارات)
- `data/` — سجل الأسعار وحالة الصور وسجل المزامنة (يُعاد تصدير `data/raw/` من الشيت)

## التحقق

```bash
python3 scripts/verify.py   # 722 فحصاً — يجب أن تكون كلها ناجحة
```

## المحتوى الحالي

76 موديلاً، 169 عرضاً، 10 علامات تجارية — جميع الصور محلية ومختومة
بالعلامة المائية (النمط B: شريط "3rde.online" السفلي).
