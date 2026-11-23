# نظام طلبات الإجراء — فريق الرصد والمتابعة الإلكترونية

نسخة إلكترونية (Django) من **نموذج طلب إجراء (حجب - قفل - حظر - توثيق) للصفحات والقنوات الرسمية**.

## المزايا
- تسجيل الدخول بـ **الكود** (الكود = اسم المستخدم).
- النموذج بأقسامه الستة: المنصات، نوع الإجراء، الروابط، شرح الحالة، المخولون بالعمليات (بالكود)، التوقيع والاعتماد.
- لكل رابط يقوم النظام تلقائياً بما يلي:
  - إذا كان **فيديو**: يحمّله (عن طريق yt-dlp) ويخزّنه في `media/evidence/...` مع بصمة SHA-256.
  - يحدد **الصفحة الشخصية** لصاحب الرابط ويأخذ لها **صورة** (Chromium عبر Playwright) مع بصمة SHA-256.
  - إذا كان الرابط صفحة شخصية أصلاً، يصوّرها مباشرة.
- الاعتماد والرفض من قبل المسؤول المعتمد (مكتب الأدلة الرقمية)، ويُسجَّل التوقيع والتاريخ تلقائياً.
- صفحة الطلب قابلة للطباعة بنفس ترتيب النموذج الورقي.
- مخطط سير العمل بصيغة BPMN 2.0 في الملف `docs/workflow.bpmn`.

## الصلاحيات
| الصفحة | من يراها |
|---|---|
| الطلبات، طلب جديد، التقارير | كل المستخدمين المسجّلين |
| اعتماد/رفض الطلب | المسؤول المعتمد أو مدير النظام |
| إدارة المستخدمين، سجل التدقيق، لوحة Django | **مدير النظام (Superadmin) فقط** |

- **سجل التدقيق** (django-auditlog): يسجّل كل إنشاء/تعديل/حذف على المستخدمين والطلبات والروابط مع المنفّذ وعنوان IP والقيم قبل/بعد (كلمات المرور لا تُسجَّل).
- **التقارير**: حسب الفترة والمنصة ونوع الإجراء والحالة، مع مؤشرات ورسوم أعمدة وتصدير **PDF** (A4، خط عربي مضمَّن، ترقيم صفحات) و**CSV** (يفتح في Excel) وطباعة.
- **شعار المؤسسة في تقرير PDF**: ضع الملف في مجلد `branding/` واضبط `REPORT_LOGO_PATH=branding/logo.png` (و`REPORT_LOGO_HEIGHT` اختيارياً) في `.env`.
- الخطوط: Noto Sans Arabic / Noto Sans (رخصة SIL OFL — `reports/static/reports/fonts/OFL.txt`).

## البنية (MVC / OOP)
| الطبقة | الملفات |
|---|---|
| Model | `accounts/models.py` (User + Role)، `reports/models.py` (ActionRequest, RequestLink) |
| View (القوالب) | `templates/`، `reports/templates/reports/` |
| Controller | `reports/views.py` (Class-Based Views)، `reports/forms.py` |
| Reporting | `reports/reporting.py`: `ReportFilter`، `ReportBuilder`، `ReportCsvExporter` |
| Users / Audit | `accounts/views.py` (`SuperuserRequiredMixin`)، django-auditlog |
| Services | `reports/services/`: `LinkAnalyzer`، `VideoDownloader`، `ProfileScreenshotter`، `EvidenceCollector`، `EvidenceDispatcher` |

## التشغيل عبر Docker (موصى به)
```bash
cp .env.example .env        # عدّل كلمة السر و DJANGO_SECRET_KEY
docker compose up -d --build
```
ثم افتح http://localhost:8000 وادخل بالكود `DJANGO_SUPERUSER_USERNAME` الموجود في `.env`.
- قاعدة البيانات والفيديوهات والصور تُحفظ في مجلد **`data/`** بجانب المشروع (مربوط بـ `/app/data` داخل الحاوية):
  `data/db.sqlite3` و `data/media/evidence/request_<رقم>/link_<رقم>/`.
  - النسخ الاحتياطي: `docker compose stop` ثم انسخ مجلد `data/` كاملاً.
  - عند الترقية من نسخة سابقة كانت تستخدم volume باسم `app_data`، تُنقل البيانات تلقائياً إلى `data/` عند أول تشغيل (مرة واحدة، والـ volume القديم يبقى نسخة احتياطية).
- الصورة مبنية على صورة Playwright الرسمية (فيها Chromium) ومعها ffmpeg.
- للمنصات التي تطلب تسجيل دخول أو تُظهر تحقق CAPTCHA: ضع ملف cookies المُصدَّر (`.txt` أو `.json`) داخل مجلد `cookies/` — يُلتقط تلقائياً (لتحميل الفيديو **ولتصوير الصفحة الشخصية**)، ثم تحقق بـ `docker compose exec web python manage.py check_cookies`.
- التشخيص: `docker compose exec web python manage.py debug_profile <رابط الصفحة>`
- السجلات: `docker compose logs -f web`

## التشغيل بدون Docker
```bash
pip install -r requirements.txt
python -m playwright install chromium    # مرة واحدة
python manage.py migrate
python manage.py createsuperuser         # اسم المستخدم = الكود
python manage.py runserver
```
أضف المستخدمين من `/admin/` واختر لكل منهم **الصفة** (مسؤول رصد، مسؤول تحميل، نقطة اتصال، مسؤول معتمد).

## الإعدادات (متغيرات البيئة)
| المتغير | الوصف |
|---|---|
| `EVIDENCE_ASYNC` | `1` (افتراضي) تُجمع الأدلة في الخلفية بعد الإرسال مباشرة. `0` عبر الأمر فقط. |
| `YTDLP_COOKIES_FILE` | ملف cookies (بصيغة Netscape) للمحتوى الذي يتطلب تسجيل دخول (إنستغرام، فيسبوك...). |
| `CHROMIUM_EXECUTABLE` | مسار متصفح Chromium إن لم يكن الافتراضي. |
| `EVIDENCE_MAX_VIDEO_MB` | الحد الأقصى لحجم الفيديو (افتراضي 500). |
| `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS` | إعدادات الإنتاج. |

إعادة معالجة الروابط المعلّقة أو الفاشلة (يمكن جدولته بـ cron):
```bash
python manage.py collect_evidence --retry
```

## الاختبارات
```bash
python manage.py test
```

### تحميل الفيديو (سلسلة محاولات)
1. **yt-dlp** مع انتحال بصمة متصفح Chrome (`curl_cffi`) — يحل أغلب حالات حجب تيك توك.
2. **المتصفح (Chromium)** كخطة بديلة: يفتح المنشور، يستخرج رابط الفيديو الحقيقي من بيانات الصفحة أو حركة الشبكة، وينزله بنفس الجلسة.
3. يتم تحديث yt-dlp تلقائياً عند تشغيل الحاوية (`YTDLP_AUTO_UPDATE=1`).

> ملاحظة: بعض المنصات (إنستغرام، فيسبوك، X) تحجب الزائر غير المسجّل، فقد تظهر صورة الصفحة على شكل صفحة تسجيل دخول أو يفشل تحميل الفيديو. استخدم `YTDLP_COOKIES_FILE` لحساب رسمي، وسيظهر سبب أي فشل في "سجل المعالجة" مع زر إعادة المحاولة.
