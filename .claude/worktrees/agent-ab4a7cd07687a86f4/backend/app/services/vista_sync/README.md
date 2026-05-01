# vista_sync
Read/write bridge to Trimble Viewpoint Vista.

## Key Tables
| Table   | Purpose                     |
|---------|-----------------------------|
| apvend  | AP Vendors                  |
| emem    | Equipment master            |
| jcjm    | Job cost master             |
| jcci    | Job cost items              |
| preh    | Payroll employee hours      |
| emwo    | Equipment work orders       |

## Files
- `vendor_import.py`   — AP vendor CSV → Vista (v1)
- `equipment_read.py`  — Pull fleet status from emem
- `workorder_sync.py`  — Push work orders to emwo (v2)
- `job_cost_read.py`   — Pull jcjm/jcci for dashboards
