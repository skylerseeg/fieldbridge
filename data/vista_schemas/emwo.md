# emwo — Equipment Work Order Table

| Column       | Type         | Description                        |
|--------------|--------------|------------------------------------|
| WorkOrder    | varchar(20)  | Primary key — WO number            |
| Equipment    | varchar(20)  | FK → emem.Equipment                |
| Description  | varchar(60)  | Work description                   |
| Status       | varchar(10)  | O=Open, C=Closed, H=Hold           |
| Priority     | varchar(10)  | 1=Critical, 2=High, 3=Normal       |
| RequestedBy  | varchar(30)  | Foreman / requestor                |
| OpenDate     | datetime     | Date opened                        |
| ClosedDate   | datetime     | Date closed                        |
| Mechanic     | varchar(20)  | Assigned mechanic (FK → preh)      |
| LaborHours   | decimal      | Actual labor hours                 |
| PartsCost    | decimal      | Parts cost                         |
| TotalCost    | decimal      | Total work order cost              |
| JobNumber    | varchar(20)  | FK → jcjm — charged job            |
