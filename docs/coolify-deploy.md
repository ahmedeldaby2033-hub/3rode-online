# النشر على Coolify — VPS أوراكل (الشريحة المجانية)

الموقع **ثابت (static)** — لا قاعدة بيانات ولا PHP. الطريقة الأسهل مع Coolify:
**المشروع في مستودع Git ← Coolify يبني صورة nginx وينشرها ← النطاق + SSL مجاناً تلقائياً**.
لا FTP ولا cPanel.

> هذه هي طريقة النشر الأساسية الآن. دليل الاستضافة المشتركة القديم في `DEPLOY.md`
> ما زال صالحاً كمرجع، لكن خطوات Coolify أدناه تحلّ محل أقسامه 1–3.

## 0 — قبل البدء: هل موارد الـ VPS كافية؟

- **الأفضل: مثيل ARM Ampere المجاني (4 OCPU / 24GB RAM)** — Coolify + Docker يعملان عليه بارتياح.
- **إن كان مثيل AMD المجاني (1GB RAM):** سيكون ضيقاً جداً على Coolify — أضف swap (4GB) أو انقل إلى ARM.
- تأكد أن Coolify مثبّت ويعمل، وأن لديك IP العام للـ VPS.

## 1 — ارفع المشروع إلى مستودع GitHub

من جهازك (أو من الـ VPS نفسه):

```bash
cd 3rode-online
git init
git add .
git commit -m "3rde.online — initial site (76 models, 169 offers)"
git branch -M main
git remote add origin https://github.com/<YOUR-USER>/3rode-online.git
git push -u origin main
```

- المستودع **عام أو خاص** — Coolify يدعم الاثنين (الخاص يحتاج ربط حساب GitHub في Coolify).
- ملف `.gitignore` يستثني `data/raw/` (يُعاد تصديره من الشيت) وملفات السجلات.
- مجلد `site/` **مرفوع مع المستودع** حتى يعمل أول نشر فوراً قبل أي مزامنة.

## 2 — أنشئ التطبيق في Coolify

1. Coolify ← **New Resource ← Application ← GitHub** (أو Public Repository) ← اختر مستودع `3rode-online`.
2. **Build Pack: Dockerfile** — ملف `Dockerfile` في جذر المشروع (موجود، يستخدم `nginx:alpine` ويقدّم `site/` + لوحة التحكم `admin/index.html`).
3. **Port: 80**.
4. **Domains:** أضف `3rde.online` (و `www.3rde.online` إن أردت — اختياري).
5. اضغط **Deploy**.
6. Coolify يصدر **شهادة SSL مجانية (Let's Encrypt)** تلقائياً للنطاق ويجدّدها بنفسه.

## 3 — وجّه النطاق إلى الـ VPS

من لوحة تحكم مسجّل النطاق:

| السجل | القيمة |
|---|---|
| A — `3rde.online` | IP العام للـ VPS |
| A — `www` (اختياري) | نفس IP الـ VPS |

- الانتشار قد يستغرق حتى 24 ساعة. تحقق بـ `ping 3rde.online`.
- لا تغيّر الـ Nameservers — سجل A يكفي مع Coolify.

## 4 — فعّل تصدير الشيت أولاً (مهم للمزامنة)

المزامنة على الـ VPS **لا تستطيع** قراءة الشيت مباشرة (أداة `hatch_gws_cli` موجودة عندي فقط).
هي تعتمد على **نقطة تصدير Apps Script** — لذلك:

1. انشر Apps Script من `admin/Code.gs` حسب `admin/SETUP.md` (نشر كـ Web App).
2. الصق رابط الـ Web App في `settings.json` ← `admin.apps_script_url`
   (أو من لوحة التحكم ← الإعدادات بعد أول نشر).
3. `git commit + push` — ليلتقط الـ VPS الرابط في المزامنة التالية.

بدون هذه الخطوة، المزامنة ستعيد بناء الموقع من آخر تصدير محفوظ (أسعار قديمة)
ولن تلتقط أي تعديل جديد في الشيت.

## 5 — المزامنة كل ساعة (cron على الـ VPS)

على الـ VPS نفسه:

```bash
# 1) استنساخ المشروع
sudo mkdir -p /opt && sudo chown $USER /opt
git clone https://github.com/<YOUR-USER>/3rode-online.git /opt/3rode-online

# 2) بايثون + Pillow (للعامة المائية)
python3 -m pip install pillow

# 3) هوية git للالتزامات التلقائية
git config --global user.name "3rde-sync"
git config --global user.email "da3m@3rde.online"

# 4) اجعل السكربت قابلاً للتنفيذ وجرّبه مرة يدوياً
chmod +x /opt/3rode-online/scripts/vps-sync.sh
/opt/3rode-online/scripts/vps-sync.sh

# 5) ثبّت المهمة كل ساعة
crontab -e
# أضف هذا السطر:
0 * * * *  /opt/3rode-online/scripts/vps-sync.sh
```

كيف يعمل `scripts/vps-sync.sh`:

- `git pull` ← يسحب آخر تعديلاتك (إعدادات، أكواد إعلانات...).
- `scripts/sync.py` ← يحدّث الأسعار من الشيت، يسجّل سجل الأسعار **فقط عند تغيّر السعر**،
  ينزّل صور المنتجات الجديدة ويضع العلامة المائية (النمط B)، ثم يعيد بناء الموقع.
- إن تغيّر شيء فعلياً فقط: `commit + push` ← وCoolify **يعيد النشر تلقائياً** عند الـ push.
- إن لم يتغيّر شيء: لا التزام ولا نشر — فلا إعادة بناء بلا داعٍ.
  (صفحات الموقع تحمل تاريخ آخر تحديث من الشيت نفسه، لا وقت البناء،
  فإعادة البناء بلا تغييرات تنتج ملفات مطابقة تماماً.)

## 6 — تحقّق بعد النشر

- افتح `https://3rde.online/` — الصفحة الرئيسية تعمل.
- افتح صفحة منتج (مثلاً `/mobiles/oppo-a6-128gb-4gb/`) — 3 أزرار شراء،
  زر جوميا يحمل `utm_source=JFORCE`، وزر أمازون يحمل الوسام `amazon0c2aca6-21`.
- لوحة التحكم: `https://3rde.online/admin/` (تحتاج إعداد Apps Script من `admin/SETUP.md`).
- أكمل أقسام 4–7 في `DEPLOY.md`: Search Console + Bing + Publisher Center + الأفلييت + AdSense.

## 7 — استكشاف الأخطاء

- **النطاق لا يفتح:** تأكد من سجل A ومن انتشار DNS، وأن Coolify أصدر الشهادة (صفحة Domains في التطبيق).
- **الأسعار لا تتحدث:** راجع `data/sync-cron.log` على الـ VPS، وتأكد أن `apps_script_url` مضبوط
  (القسم 4 أعلاه) وأن الـ Web App منشور للجميع (Anyone).
- **فشل البناء في Coolify:** افتح سجل البناء — غالباً سببه ملف مفقود في المستودع؛
  تأكد أن `site/` مرفوع بالكامل وأن `Dockerfile` و`nginx.conf` في جذر المستودع.
- **نفاد ذاكرة أثناء البناء:** راجع القسم 0 — مثيل 1GB غير كافٍ لـ Coolify.
- **روابط الأفلييت:** أي ترتيب لصفوف الشيت يجب أن يشمل **كل الأعمدة حتى AU**،
  وإلا ينحرف عمود الأفلييت عن منتجاته (حدث مرة 2026-11-19 وأُصلح).
  فحص `verify.py` الجديد (القسم 2b) يمنع نشر بناءٍ فيه انحراف كهذا.
