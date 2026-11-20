from app.modules.prescriptions.extraction_service import extract_prescription_medicines


def extract(text):
    return extract_prescription_medicines("rx-test", {"full_text": text})


def test_extracts_english_medicine_and_preserves_instructions():
    result = extract("Napa 500mg tablet\n1+0+1 after food\nfor 5 days")
    assert len(result.medicines) == 1
    medicine = result.medicines[0]
    assert medicine.medicine_name == "Napa"
    assert medicine.strength == "500mg"
    assert medicine.frequency.startswith("1+0+1")
    assert medicine.duration == "5 days"
    assert medicine.food_instruction == "After food / খাবারের পরে"
    assert medicine.verification_status == "needs_review"


def test_extracts_bangla_medicine_line_and_bangla_instructions():
    result = extract("Napa 500 মিগ্রা ট্যাবলেট\nদিনে দুইবার খাবারের পরে\n৫ দিন")
    assert len(result.medicines) == 1
    medicine = result.medicines[0]
    assert medicine.medicine_name == "Napa"
    assert medicine.dosage_form == "ট্যাবলেট"
    assert medicine.frequency == "Twice daily / দিনে দুইবার"
    assert medicine.food_instruction == "After food / খাবারের পরে"
    assert medicine.duration == "৫ দিন"


def test_does_not_guess_from_unstructured_notes():
    result = extract("Patient has fever and headache\nTake rest and drink water")
    assert result.extraction_status == "no_medicines_detected"
    assert result.medicines == []


def test_unclear_fields_stay_empty_and_need_review():
    result = extract("Azithro 500mg capsule")
    medicine = result.medicines[0]
    assert medicine.dose is None
    assert medicine.frequency is None
    assert medicine.duration is None
    assert medicine.verification_status == "needs_review"


def test_extracts_tablet_form_from_tab_prefix():
    medicine = extract("Tab. Napa 500 mg").medicines[0]
    assert medicine.medicine_name == "Napa"
    assert medicine.strength == "500mg"
    assert medicine.dosage_form == "tablet"


def test_extracts_capsule_form_from_cap_prefix():
    medicine = extract("Cap. Omeprazole 20 mg").medicines[0]
    assert medicine.medicine_name == "Omeprazole"
    assert medicine.strength == "20mg"
    assert medicine.dosage_form == "capsule"


def test_does_not_guess_missing_dosage_form():
    medicine = extract("Napa 500 mg").medicines[0]
    assert medicine.medicine_name == "Napa"
    assert medicine.dosage_form is None
