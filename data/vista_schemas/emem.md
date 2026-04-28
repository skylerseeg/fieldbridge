# emem — Equipment Master Table

| Column       | Type         | Description                        |
|--------------|--------------|------------------------------------|
| Equipment    | varchar(20)  | Primary key — equipment code       |
| Description  | varchar(60)  | Equipment description              |
| Category     | varchar(10)  | Equipment category                 |
| Status       | varchar(10)  | A=Active, I=Inactive               |
| HourMeter    | decimal      | Current hour meter reading         |
| LastPMDate   | datetime     | Last preventive maintenance date   |
| LastPMHours  | decimal      | Hour meter at last PM              |
| NextPMHours  | decimal      | Hour meter for next PM due         |
| Location     | varchar(30)  | Current job/location               |
| CostCenter   | varchar(10)  | Cost center assignment             |
