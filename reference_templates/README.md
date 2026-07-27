# Reference Templates

Official template CSV files used as the source of truth for header validation.

## Structure

```
reference_templates/
├── data_import_tool/    # Data Import Tool column headers
└── workbench/           # Workbench (Salesforce API) column headers
```

Each folder contains identically named files. The app resolves the path from:

**upload method + template name → `{folder}/{slug}.csv`**

Example:
- Data Import Tool + Customers → `data_import_tool/customers.csv`
- Workbench + Customers → `workbench/customers.csv`

## How to add templates

1. Save the official template as CSV (not xlsx).
2. Place it in the correct folder.
3. Use the slug filename for that template (see table below).
4. Keep the original header row exactly as provided by the tool.

## Filename mapping

| Template (app dropdown) | Filename |
|-------------------------|----------|
| Account Relationship | `account_relationship.csv` |
| Assortment | `assortment.csv` |
| Assortment Assignment | `assortment_assignment.csv` |
| Assortment Product | `assortment_product.csv` |
| Contact | `contact.csv` |
| Contract | `contract.csv` |
| Customer to Route | `customer_to_route.csv` |
| Customers | `customers.csv` |
| Employee to Route | `employee_to_route.csv` |
| Order | `order.csv` |
| Order Item | `order_item.csv` |
| Payers | `payers.csv` |
| Pricelist Master | `pricelist_master.csv` |
| Products | `products.csv` |
| Prospects | `prospects.csv` |
| Retail Promotion | `retail_promotion.csv` |
| Retail Sales Geo | `retail_sales_geo.csv` |
| Routing Import | `routing_import.csv` |
| Store Assortment | `store_assortment.csv` |
| Store Product | `store_product.csv` |
| Units of Measure | `units_of_measure.csv` |
| Wholesalers | `wholesalers.csv` |

## Notes

- Header comparison is separate from business rules, required-field rules, and dependencies.
- Those will live in `rules/` and be added later.
- Do not hardcode column names in Python — update the CSV files here instead.
