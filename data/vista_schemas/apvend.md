# apvend — AP Vendor Table

| Column      | Type         | Description                        |
|-------------|--------------|------------------------------------|
| Vendor      | varchar(10)  | Primary key — vendor code          |
| Name        | varchar(60)  | Vendor display name                |
| SortName    | varchar(60)  | Sort/search name                   |
| Address1    | varchar(60)  | Street address                     |
| Address2    | varchar(60)  | Suite / PO Box                     |
| City        | varchar(30)  | City                               |
| State       | varchar(4)   | State abbreviation                 |
| Zip         | varchar(10)  | ZIP code                           |
| Phone       | varchar(20)  | Primary phone                      |
| Email       | varchar(60)  | Primary email                      |
| Website     | varchar(100) | Website URL                        |
| Contact     | varchar(30)  | Primary contact name               |
| Active      | bit          | 1 = active, 0 = inactive           |
| Notes       | text         | Free-form notes                    |

## CSI Code Association
Vista links vendors to CSI codes via a separate vendor-category table.
FieldBridge outputs: vendor_name | Seq | DatabaseValue | DisplayValue
