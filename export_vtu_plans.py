import os
import sys
import csv
import django
from decimal import Decimal

# Add project root to sys.path
sys.path.insert(0, r"c:\Users\Eminence\Documents\SubHero")

# Bootstrap Django settings
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
django.setup()

from apps.vtu.models import VTUPlan

# Live plans extracted from the CheapDataHub Reseller Panel
live_plans = [
    # Airtel
    {"plan_id": "70", "network": "airtel", "name": "1GB (Social Bundle) Gifting (3 Days)", "provider_price": Decimal("260.00"), "subhero_price": Decimal("295.00"), "validity": "3 Days"},
    {"plan_id": "13", "network": "airtel", "name": "500MB Gifting (7 days)", "provider_price": Decimal("440.00"), "subhero_price": Decimal("490.00"), "validity": "7 Days"},
    {"plan_id": "69", "network": "airtel", "name": "1.5GB Gifting (1 Day)", "provider_price": Decimal("450.00"), "subhero_price": Decimal("500.00"), "validity": "1 Day"},
    {"plan_id": "66", "network": "airtel", "name": "1.5GB Gifting (2 Days)", "provider_price": Decimal("540.00"), "subhero_price": Decimal("599.00"), "validity": "2 Days"},
    {"plan_id": "15", "network": "airtel", "name": "1GB Gifting (7 Days)", "provider_price": Decimal("700.00"), "subhero_price": Decimal("785.00"), "validity": "7 Days"},
    {"plan_id": "17", "network": "airtel", "name": "2GB Gifting (30 Days)", "provider_price": Decimal("1320.00"), "subhero_price": Decimal("1470.00"), "validity": "30 Days"},
    {"plan_id": "52", "network": "airtel", "name": "5GB Gifting (7 Days)", "provider_price": Decimal("1420.00"), "subhero_price": Decimal("1570.00"), "validity": "7 Days"},
    {"plan_id": "18", "network": "airtel", "name": "3GB Gifting (30 Days)", "provider_price": Decimal("1760.00"), "subhero_price": Decimal("1960.00"), "validity": "30 Days"},
    {"plan_id": "22", "network": "airtel", "name": "6GB SME (7 Days)", "provider_price": Decimal("2200.00"), "subhero_price": Decimal("2455.00"), "validity": "7 Days"},
    {"plan_id": "19", "network": "airtel", "name": "4GB Gifting (30 Days)", "provider_price": Decimal("2300.00"), "subhero_price": Decimal("2570.00"), "validity": "30 Days"},
    {"plan_id": "20", "network": "airtel", "name": "8GB Gifting (30 Days)", "provider_price": Decimal("2700.00"), "subhero_price": Decimal("2999.00"), "validity": "30 Days"},
    {"plan_id": "21", "network": "airtel", "name": "10GB Gifting (30 Days)", "provider_price": Decimal("3660.00"), "subhero_price": Decimal("4070.00"), "validity": "30 Days"},
    
    # Glo
    {"plan_id": "42", "network": "glo", "name": "200 MB corporate gifting (1 Day)", "provider_price": Decimal("80.00"), "subhero_price": Decimal("89.00"), "validity": "1 Day"},
    {"plan_id": "35", "network": "glo", "name": "500MB corporate gifting (30 Days)", "provider_price": Decimal("200.00"), "subhero_price": Decimal("225.00"), "validity": "30 Days"},
    {"plan_id": "68", "network": "glo", "name": "1GB corporate gifting (3 Days)", "provider_price": Decimal("250.00"), "subhero_price": Decimal("280.00"), "validity": "3 Days"},
    {"plan_id": "36", "network": "glo", "name": "1GB corporate gifting (30 Days)", "provider_price": Decimal("380.00"), "subhero_price": Decimal("425.00"), "validity": "30 Days"},
    {"plan_id": "41", "network": "glo", "name": "1GB Gifting (14 Days)", "provider_price": Decimal("440.00"), "subhero_price": Decimal("485.00"), "validity": "14 Days"},
    {"plan_id": "40", "network": "glo", "name": "2GB corporate gifting (30 Days)", "provider_price": Decimal("750.00"), "subhero_price": Decimal("840.00"), "validity": "30 Days"},
    {"plan_id": "37", "network": "glo", "name": "3GB corporate gifting (30 Days)", "provider_price": Decimal("1160.00"), "subhero_price": Decimal("1290.00"), "validity": "30 Days"},
    {"plan_id": "54", "network": "glo", "name": "5GB corporate gifting (7 Days)", "provider_price": Decimal("1520.00"), "subhero_price": Decimal("1690.00"), "validity": "7 Days"},
    {"plan_id": "38", "network": "glo", "name": "5GB corporate gifting (30 Days)", "provider_price": Decimal("1970.00"), "subhero_price": Decimal("2190.00"), "validity": "30 Days"},
    {"plan_id": "39", "network": "glo", "name": "10GB corporate gifting (30 Days)", "provider_price": Decimal("3950.00"), "subhero_price": Decimal("4390.00"), "validity": "30 Days"},
    {"plan_id": "59", "network": "glo", "name": "20.5GB Gifting (30 Days)", "provider_price": Decimal("4770.00"), "subhero_price": Decimal("5300.00"), "validity": "30 Days"},
    {"plan_id": "58", "network": "glo", "name": "107GB Gifting (30 Days)", "provider_price": Decimal("17370.00"), "subhero_price": Decimal("19300.00"), "validity": "30 Days"},
    
    # MTN
    {"plan_id": "43", "network": "mtn", "name": "110MB Gifting (1 Day)", "provider_price": Decimal("89.00"), "subhero_price": Decimal("99.00"), "validity": "1 Day"},
    {"plan_id": "74", "network": "mtn", "name": "230MB Gifting (1 Day)", "provider_price": Decimal("180.00"), "subhero_price": Decimal("200.00"), "validity": "1 Day"},
    {"plan_id": "76", "network": "mtn", "name": "500MB SME (2 Days)", "provider_price": Decimal("225.00"), "subhero_price": Decimal("250.00"), "validity": "2 Days"},
    {"plan_id": "78", "network": "mtn", "name": "1GB SME (1 Day)", "provider_price": Decimal("250.00"), "subhero_price": Decimal("280.00"), "validity": "1 Day"},
    {"plan_id": "44", "network": "mtn", "name": "500MB SME (30 Days)", "provider_price": Decimal("310.00"), "subhero_price": Decimal("350.00"), "validity": "30 Days"},
    {"plan_id": "77", "network": "mtn", "name": "1GB SME (2 Days)", "provider_price": Decimal("360.00"), "subhero_price": Decimal("399.00"), "validity": "2 Days"},
    {"plan_id": "45", "network": "mtn", "name": "1GB SME (7 Days)", "provider_price": Decimal("400.00"), "subhero_price": Decimal("450.00"), "validity": "7 Days"},
    {"plan_id": "46", "network": "mtn", "name": "1GB SME (30 Days)", "provider_price": Decimal("510.00"), "subhero_price": Decimal("570.00"), "validity": "30 Days"},
    {"plan_id": "79", "network": "mtn", "name": "2.5GB SME (1 Day)", "provider_price": Decimal("540.00"), "subhero_price": Decimal("600.00"), "validity": "1 Day"},
    {"plan_id": "71", "network": "mtn", "name": "2GB Gifting (7 Days)", "provider_price": Decimal("810.00"), "subhero_price": Decimal("900.00"), "validity": "7 Days"},
    {"plan_id": "27", "network": "mtn", "name": "2.5GB Gifting (2 Days)", "provider_price": Decimal("810.00"), "subhero_price": Decimal("900.00"), "validity": "2 Days"},
    {"plan_id": "47", "network": "mtn", "name": "2GB SME (7 Days)", "provider_price": Decimal("830.00"), "subhero_price": Decimal("930.00"), "validity": "7 Days"},
    {"plan_id": "60", "network": "mtn", "name": "3.5GB Gifting (1 Day)", "provider_price": Decimal("880.00"), "subhero_price": Decimal("980.00"), "validity": "1 Day"},
    {"plan_id": "48", "network": "mtn", "name": "2GB SME (30 Days)", "provider_price": Decimal("1030.00"), "subhero_price": Decimal("1150.00"), "validity": "30 Days"},
    {"plan_id": "61", "network": "mtn", "name": "4GB Gifting (2 Days)", "provider_price": Decimal("1050.00"), "subhero_price": Decimal("1175.00"), "validity": "2 Days"},
    {"plan_id": "49", "network": "mtn", "name": "3GB SME (30 Days)", "provider_price": Decimal("1230.00"), "subhero_price": Decimal("1370.00"), "validity": "30 Days"},
    {"plan_id": "50", "network": "mtn", "name": "5GB SME (30 Days)", "provider_price": Decimal("1840.00"), "subhero_price": Decimal("2050.00"), "validity": "30 Days"},
    {"plan_id": "53", "network": "mtn", "name": "6GB Gifting (7 Days)", "provider_price": Decimal("2240.00"), "subhero_price": Decimal("2495.00"), "validity": "7 Days"},
    {"plan_id": "55", "network": "mtn", "name": "11GB Gifting (7 Days)", "provider_price": Decimal("3080.00"), "subhero_price": Decimal("3430.00"), "validity": "7 Days"},
    {"plan_id": "33", "network": "mtn", "name": "7GB Gifting (30 Days)", "provider_price": Decimal("3140.00"), "subhero_price": Decimal("3499.00"), "validity": "30 Days"},
    {"plan_id": "67", "network": "mtn", "name": "10GB Gifting (30 Days)", "provider_price": Decimal("4020.00"), "subhero_price": Decimal("4470.00"), "validity": "30 Days"},
    {"plan_id": "57", "network": "mtn", "name": "36GB Gifting (30 Days)", "provider_price": Decimal("9720.00"), "subhero_price": Decimal("10800.00"), "validity": "30 Days"},
    {"plan_id": "51", "network": "mtn", "name": "75GB SME (30 Days)", "provider_price": Decimal("16190.00"), "subhero_price": Decimal("17990.00"), "validity": "30 Days"},
]

print("Seeding active CheapDataHub VTU plans to database...")
seeded_count = 0
for p in live_plans:
    VTUPlan.objects.update_or_create(
        plan_id=p["plan_id"],
        defaults={
            "network": p["network"],
            "name": p["name"],
            "provider_price": p["provider_price"],
            "subhero_price": p["subhero_price"],
            "validity": p["validity"],
            "is_active": True
        }
    )
    seeded_count += 1
print(f"Seeded {seeded_count} active VTU plans into the database.")

csv_path = r"c:\Users\Eminence\Documents\SubHero\vtu_full_catalog.csv"
print("Exporting VTU catalogue to CSV...")
try:
    plans = VTUPlan.objects.all().order_by('network', 'subhero_price')
    with open(csv_path, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow([
            "Plan ID",
            "Network",
            "Plan Name",
            "Validity",
            "Provider Price (N)",
            "SubHero Retail Price (N)"
        ])
        for p in plans:
            writer.writerow([
                p.plan_id,
                p.network.upper(),
                p.name,
                p.validity,
                f"N{p.provider_price:.2f}",
                f"N{p.subhero_price:.2f}"
            ])
    print(f"SUCCESS: Exported to {csv_path}")
except Exception as e:
    print(f"ERROR: {str(e)}")
