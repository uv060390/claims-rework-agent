"""Reference code tables for the synthetic behavioral-health claims generator.

Code sets (CPT/HCPCS, ICD-10-CM, POS, CARC) are drawn from public CMS/X12
documentation so generated claims look authentic to a healthcare-literate reader.
Fee-schedule amounts are illustrative, loosely based on public CMS Physician Fee
Schedule national payment amounts — they are NOT any payer's real contracted rates.
"""

from decimal import Decimal

# CPT/HCPCS code -> (description, fee-schedule allowed amount)
BH_SERVICES: dict[str, tuple[str, Decimal]] = {
    "90791": ("Psychiatric diagnostic evaluation", Decimal("145.44")),
    "90792": ("Psychiatric diagnostic evaluation with medical services", Decimal("163.77")),
    "90832": ("Psychotherapy, 30 minutes", Decimal("71.10")),
    "90834": ("Psychotherapy, 45 minutes", Decimal("94.55")),
    "90837": ("Psychotherapy, 60 minutes", Decimal("141.47")),
    "90839": ("Psychotherapy for crisis, first 60 minutes", Decimal("137.19")),
    "90846": ("Family psychotherapy without patient present", Decimal("92.61")),
    "90847": ("Family psychotherapy with patient present", Decimal("96.06")),
    "90853": ("Group psychotherapy", Decimal("26.51")),
    "96130": ("Psychological testing evaluation, first hour", Decimal("110.44")),
    "H0004": ("Behavioral health counseling and therapy, per 15 minutes", Decimal("24.00")),
    "H0031": ("Mental health assessment by non-physician", Decimal("55.00")),
    "H2019": ("Therapeutic behavioral services, per 15 minutes", Decimal("18.50")),
}

# ICD-10-CM behavioral-health diagnosis codes
ICD10_BH: dict[str, str] = {
    "F32.9": "Major depressive disorder, single episode, unspecified",
    "F33.1": "Major depressive disorder, recurrent, moderate",
    "F41.1": "Generalized anxiety disorder",
    "F41.9": "Anxiety disorder, unspecified",
    "F43.10": "Post-traumatic stress disorder, unspecified",
    "F43.23": "Adjustment disorder with mixed anxiety and depressed mood",
    "F60.3": "Borderline personality disorder",
    "F90.0": "ADHD, predominantly inattentive type",
    "F10.20": "Alcohol dependence, uncomplicated",
    "F11.20": "Opioid dependence, uncomplicated",
    "F20.9": "Schizophrenia, unspecified",
    "F31.9": "Bipolar disorder, unspecified",
    "F84.0": "Autistic disorder",
    "F42.2": "Mixed obsessional thoughts and acts",
}

# Place-of-service codes
POS_CODES: dict[str, str] = {
    "02": "Telehealth provided other than in patient's home",
    "10": "Telehealth provided in patient's home",
    "11": "Office",
    "12": "Home",
    "21": "Inpatient hospital",
    "22": "On-campus outpatient hospital",
    "53": "Community mental health center",
    "57": "Non-residential substance abuse treatment facility",
}

# Claim adjustment reason codes (CARC) used by the denial scenarios
CARC_CODES: dict[str, str] = {
    "16": "Claim/service lacks information or has submission/billing error(s)",
    "18": "Exact duplicate claim/service",
    "22": "This care may be covered by another payer per coordination of benefits",
    "29": "The time limit for filing has expired",
    "45": "Charge exceeds fee schedule/maximum allowable",
    "50": "Not deemed a medical necessity by the payer",
    "96": "Non-covered charge(s)",
    "97": "Payment is included in the allowance for another service (bundled)",
    "197": "Precertification/authorization absent",
}

MODIFIERS: dict[str, str] = {
    "95": "Synchronous telemedicine service",
    "GT": "Via interactive audio and video telecommunication systems",
    "HO": "Masters degree level",
    "HN": "Bachelors degree level",
    "25": "Significant, separately identifiable E/M service",
}

# Timely-filing limit used consistently by generator, rules engine, and docs
TIMELY_FILING_DAYS = 90

PROVIDER_NAMES: list[str] = [
    "Lakeside Behavioral Health LLC",
    "Summit Counseling Associates",
    "Riverbend Psychiatry Group",
    "Cedar Grove Mental Wellness",
    "Harborview Therapy Center",
    "Bluestem Psychological Services",
    "Northgate Family Counseling",
    "Willow Creek Behavioral Care",
    "Beacon Point Psychiatric Associates",
    "Stonebridge Recovery Services",
    "Maple Leaf Counseling PLLC",
    "Foxglove Community Mental Health",
    "Crestline Psychotherapy Group",
    "Silver Birch Wellness Clinic",
    "Oakfield Behavioral Medicine",
    "Pinehurst Counseling Collective",
    "Meadowlark Mental Health Center",
    "Ironwood Psychiatry PLLC",
    "Clearwater Family Therapy",
    "Aspen Ridge Behavioral Group",
]
