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

## البنية (MVC / OOP)
| الطبقة | الملفات |
|---|---|
| Model | `accounts/models.py` (User + Role)، `reports/models.py` (ActionRequest, RequestLink) |
| View (القوالب) | `templates/`، `reports/templates/reports/` |
| Controller | `reports/views.py` (Class-Based Views)، `reports/forms.py` |
| Services | `reports/services/`: `LinkAnalyzer`، `VideoDownloader`، `ProfileScreenshotter`، `EvidenceCollector`، `EvidenceDispatcher` |

## التشغيل
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

> ملاحظة: بعض المنصات (إنستغرام، فيسبوك، X) تحجب الزائر غير المسجّل، فقد تظهر صورة الصفحة على شكل صفحة تسجيل دخول أو يفشل تحميل الفيديو. استخدم `YTDLP_COOKIES_FILE` لحساب رسمي، وسيظهر سبب أي فشل في "سجل المعالجة" مع زر إعادة المحاولة.
