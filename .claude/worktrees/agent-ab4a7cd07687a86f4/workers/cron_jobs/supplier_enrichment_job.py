"""
Scheduled job: run supplier enrichment pipeline daily at 6 AM.
Configure via cron or Azure Functions timer trigger.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../backend'))
from app.services.email_bridge import fieldbridge_supplier_enrichment as pipeline

if __name__ == "__main__":
    pipeline.run()
