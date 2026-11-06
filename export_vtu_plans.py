import os
import sys
import csv
import django
from pathlib import Path

# Bootstrap Django settings
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")
django.setup()

from apps.vtu.models import VTUPlan, CablePlan
from apps.vtu.tasks import sync_vtu_plans, sync_cable_plans

print("Syncing VTU catalogue from the active provider...")
sync_vtu_plans()
print("Syncing cable catalogue from the active provider...")
sync_cable_plans()

csv_path = Path(__file__).resolve().parent / "vtu_full_catalog.csv"
print(f"Exporting VTU catalogue to {csv_path}...")

try:
    plans = VTUPlan.objects.all().order_by("network", "subhero_price")
    with open(csv_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Plan ID",
            "Provider Product",
            "Network",
            "Plan Name",
            "Validity",
            "Provider Price (N)",
            "SubHero Retail Price (N)",
        ])
        for p in plans:
            writer.writerow([
                p.plan_id,
                p.provider_product,
                p.network.upper(),
                p.name,
                p.validity,
                f"N{p.provider_price:.2f}",
                f"N{p.subhero_price:.2f}",
            ])
    print(f"SUCCESS: Exported {plans.count()} data plans to {csv_path}")
except Exception as e:
    print(f"ERROR: {str(e)}")

cable_csv_path = Path(__file__).resolve().parent / "vtu_cable_catalog.csv"
print(f"Exporting cable catalogue to {cable_csv_path}...")
try:
    cable_plans = CablePlan.objects.all().order_by("provider", "subhero_price")
    with open(cable_csv_path, mode="w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "Plan ID",
            "Provider Product",
            "Provider",
            "Plan Name",
            "Provider Price (N)",
            "SubHero Retail Price (N)",
        ])
        for p in cable_plans:
            writer.writerow([
                p.plan_id,
                p.provider_product,
                p.provider.upper(),
                p.name,
                f"N{p.provider_price:.2f}",
                f"N{p.subhero_price:.2f}",
            ])
    print(f"SUCCESS: Exported {cable_plans.count()} cable plans to {cable_csv_path}")
except Exception as e:
    print(f"ERROR: {str(e)}")
