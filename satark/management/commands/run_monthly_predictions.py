from django.core.management.base import BaseCommand
from ml_model.run_monthly_batch_prediction import run_monthly_batch_inference

class Command(BaseCommand):
    help = 'Executes monthly automated batch prediction for branch audit risk grades.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--as-on-date',
            type=str,
            help='Target snapshot month date in YYYY-MM-01 format (e.g. 2026-08-01).'
        )

    def handle(self, *args, **options):
        as_on_date = options.get('as_on_date')
        self.stdout.write(self.style.SUCCESS("Starting monthly batch inference command..."))
        
        try:
            result = run_monthly_batch_inference(as_on_date=as_on_date)
            self.stdout.write(
                self.style.SUCCESS(
                    f"Successfully completed batch predictions for {result['total_branches_scored']} branches. "
                    f"High Risk Count: {result['high_risk_branches']} ({result['high_risk_pct']}%)."
                )
            )
        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Error during monthly batch prediction: {e}"))
