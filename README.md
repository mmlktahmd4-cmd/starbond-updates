# starbond-updates

تحديثات Starbond الموقّعة. راوترات Starbond بتفحص هالمستودع مرة باليوم وبتركّب النسخة الجديدة لحالها.

| الملف | شو هو |
|---|---|
| `stable/manifest.json` | آخر نسخة مستقرة (موقّعة: `manifest.json.sig`) |
| `beta/manifest.json` | آخر نسخة تجريبية (إذا في) |
| `releases/<النسخة>/Starbond-<النسخة>.tar.gz` | حزمة التحديث — بتنرفع كمان يدوي من اللوحة: النظام ← تحديث Starbond |
| `releases/<النسخة>/Starbond-<النسخة>-setup.tar.gz` | حزمة أول تفليش (RB5009: `sysupgrade -f` أو LuCI ← Restore backup) |

لا تعدّل الملفات يدوي: النشر بيصير من أداة `starbond-release.py` (بتبني وبتوقّع بالمفتاح السري).
