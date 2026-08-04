from django.core.management.base import BaseCommand
from apps.smm.tasks import sync_all_smm_descriptions


class Command(BaseCommand):
    help = "Synchronizes detailed service descriptions from Ogaviral for all active SMM services."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Force re-fetching descriptions even if already populated.",
        )

    def handle(self, *args, **options):
        force = options["force"]
        self.stdout.write(self.style.MIGRATE_HEADING("Starting SMM Service Descriptions sync..."))
        count = sync_all_smm_descriptions(force_refresh=force)
        self.stdout.write(self.style.SUCCESS(f"Successfully updated {count} SMM service descriptions."))
