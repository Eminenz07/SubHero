"""
Migration: add_airtime_cable_electricity_exam_models

Creates new VTU service tables:
  - AirtimeOrder
  - CablePlan
  - CableOrder
  - ElectricityOrder
  - ExamProduct
  - ExamPinOrder
"""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ("vtu", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # ─── AirtimeOrder ────────────────────────────────────────
        migrations.CreateModel(
            name="AirtimeOrder",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("network", models.CharField(max_length=20)),
                ("recipient", models.CharField(max_length=20)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=10)),
                ("reference", models.CharField(max_length=50, unique=True)),
                ("provider_ref", models.CharField(blank=True, default="", max_length=100)),
                ("status", models.CharField(
                    choices=[("PENDING","Pending"),("PROCESSING","Processing"),("SUCCESS","Success"),("FAILED","Failed")],
                    default="PENDING", max_length=15,
                )),
                ("delivered_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="airtime_orders",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={"db_table": "airtime_order", "ordering": ["-created_at"]},
        ),

        # ─── CablePlan ───────────────────────────────────────────
        migrations.CreateModel(
            name="CablePlan",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("plan_id", models.CharField(help_text="CheapDataHub cable plan ID", max_length=50, unique=True)),
                ("provider", models.CharField(help_text="dstv, gotv, startimes", max_length=20)),
                ("name", models.CharField(help_text="Package name e.g. DStv Compact", max_length=150)),
                ("amount", models.DecimalField(decimal_places=2, help_text="Subscription amount in NGN", max_digits=10)),
                ("subhero_price", models.DecimalField(decimal_places=2, help_text="Price charged to customer", max_digits=10)),
                ("is_active", models.BooleanField(default=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "cable_plan", "ordering": ["provider", "amount"]},
        ),

        # ─── CableOrder ──────────────────────────────────────────
        migrations.CreateModel(
            name="CableOrder",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("provider", models.CharField(max_length=20)),
                ("plan_id", models.CharField(max_length=50)),
                ("plan_name", models.CharField(max_length=150)),
                ("card_number", models.CharField(help_text="Smart card / IUC number", max_length=30)),
                ("phone", models.CharField(max_length=20)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=10)),
                ("reference", models.CharField(max_length=50, unique=True)),
                ("provider_ref", models.CharField(blank=True, default="", max_length=100)),
                ("status", models.CharField(
                    choices=[("PENDING","Pending"),("PROCESSING","Processing"),("SUCCESS","Success"),("FAILED","Failed")],
                    default="PENDING", max_length=15,
                )),
                ("delivered_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="cable_orders",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={"db_table": "cable_order", "ordering": ["-created_at"]},
        ),

        # ─── ElectricityOrder ────────────────────────────────────
        migrations.CreateModel(
            name="ElectricityOrder",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("disco_id", models.CharField(max_length=5)),
                ("disco_name", models.CharField(max_length=80)),
                ("meter_number", models.CharField(max_length=30)),
                ("meter_type", models.CharField(
                    choices=[("prepaid","Prepaid"),("postpaid","Postpaid")],
                    max_length=10,
                )),
                ("phone", models.CharField(max_length=20)),
                ("amount", models.DecimalField(decimal_places=2, max_digits=10)),
                ("reference", models.CharField(max_length=50, unique=True)),
                ("provider_ref", models.CharField(blank=True, default="", max_length=100)),
                ("token", models.CharField(blank=True, default="", help_text="Electricity token from provider", max_length=50)),
                ("units", models.CharField(blank=True, default="", help_text="kWh units credited", max_length=20)),
                ("status", models.CharField(
                    choices=[("PENDING","Pending"),("PROCESSING","Processing"),("SUCCESS","Success"),("FAILED","Failed")],
                    default="PENDING", max_length=15,
                )),
                ("delivered_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="electricity_orders",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={"db_table": "electricity_order", "ordering": ["-created_at"]},
        ),

        # ─── ExamProduct ─────────────────────────────────────────
        migrations.CreateModel(
            name="ExamProduct",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("product_id", models.CharField(max_length=20, unique=True)),
                ("exam_name", models.CharField(help_text="e.g. WAEC, NECO, NABTEB", max_length=50)),
                ("price_per_pin", models.DecimalField(decimal_places=2, max_digits=10)),
                ("subhero_price_per_pin", models.DecimalField(decimal_places=2, max_digits=10)),
                ("is_active", models.BooleanField(default=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"db_table": "exam_product", "ordering": ["exam_name"]},
        ),

        # ─── ExamPinOrder ────────────────────────────────────────
        migrations.CreateModel(
            name="ExamPinOrder",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("product_id", models.CharField(max_length=20)),
                ("exam_name", models.CharField(max_length=50)),
                ("quantity", models.PositiveSmallIntegerField(
                    choices=[(1,"1 PIN"),(2,"2 PINs"),(5,"5 PINs")],
                    default=1,
                )),
                ("amount", models.DecimalField(decimal_places=2, max_digits=10)),
                ("reference", models.CharField(max_length=50, unique=True)),
                ("provider_ref", models.CharField(blank=True, default="", max_length=100)),
                ("delivered_pins", models.TextField(blank=True, default="", help_text="Delivered PINs (newline separated)")),
                ("status", models.CharField(
                    choices=[("PENDING","Pending"),("PROCESSING","Processing"),("SUCCESS","Success"),("FAILED","Failed")],
                    default="PENDING", max_length=15,
                )),
                ("delivered_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="exam_pin_orders",
                    to=settings.AUTH_USER_MODEL,
                )),
            ],
            options={"db_table": "exam_pin_order", "ordering": ["-created_at"]},
        ),
    ]
