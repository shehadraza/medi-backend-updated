MEDI AI COMPANION — CONSOLIDATED PATCH

This patch consolidates the previously supplied Phase 1 check-in context patch and
Weekly Health Insights patch into one compatible set of files.

Included files:
- app/modules/ai/context_service.py
- app/modules/ai/service.py
- app/modules/ai/routes.py
- app/modules/ai/schemas.py
- app/modules/ai/weekly_health_insights.py (new)

What it includes:
1. Consent-gated recent daily health check-in context in AI chat.
2. Bounded, provenance-labeled self-reported check-in fields.
3. A descriptive weekly health trends endpoint:
   GET /ai/insights/weekly-health?timezone_name=Asia/Dhaka
4. Keeps the existing weekly medication endpoint:
   GET /ai/insights/weekly-medication?timezone_name=Asia/Dhaka
5. Counts symptom days uniquely per local date (not duplicate symptom mentions).
6. Uses date type for local calendar-day schema fields.

Safety and data handling:
- Personal health context is accessed only after existing purpose + consent checks.
- Only the authenticated user's check-ins are read through the existing service.
- No OCR-unconfirmed prescription data is promoted into verified instructions.
- Weekly summaries are descriptive, self-reported observations, not diagnosis.
- No database schema changes, migration, seed, or writes are included.
- Do not modify MEDI_TEST_DATABASE_URL or database settings for applying this patch.
- Do not run migrations for this patch.

Apply:
1. Stop the backend server.
2. Back up the five destination files if they exist.
3. Extract this ZIP into the backend project root and allow overwrite.
4. Restart the backend.
5. Run the existing test suite only with the project's guarded medi_test setup.

Validation performed on the supplied source snapshot:
- Python compileall completed successfully for app/ after merging these files.

Important validation limitation:
The uploaded medi-ai-source.zip did not contain tests/, conftest.py, pytest.ini,
alembic.ini, or the full test harness. Therefore this patch was syntax-checked,
but a fresh full pytest run could not be performed from the supplied archive.
The previously reported 245-passed run remains the last full-suite result supplied
by the project owner; it is not represented here as a new run.
