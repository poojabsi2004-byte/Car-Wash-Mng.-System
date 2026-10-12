# Car Wash Consumable Management (`carwash_consumable`)

Branch-wise management of the materials a car wash uses up (shampoo, wax, tyre shine,
microfibre cloths...), built on Odoo **Inventory**.

## Workflow

```
 Set up consumable ──► Minimum stock per branch ──► Link to services (materials)
                                                          │
          ┌───────────────────────────────────────────────┘
          ▼
 Booking completed ──► recipe quantities consumed automatically (usage: Service)

 Extra / wastage / return ──► Consumable Request
     Draft ──Submit──► Submitted ──Approve──► Approved ──Issue Stock──► Issued
                           │                      │
                           └───────Reject─────────┘──► Rejected (reason)

 Daily check ──► below minimum? ──► To-Do for branch managers + dashboard "Low stock"
 Restock ──► Configuration > Consumables > Receive Stock (Inventory receipt) ──► back in stock
 Review ──► Reporting > Consumables > Consumption Analysis (product × usage × branch × month)
```

| Request type | Stock move | Use it when |
|---|---|---|
| Floor Issue | branch stock → consumption | a bay / the floor needs extra material |
| Wastage / Damage | branch stock → inventory loss | spilled, expired, broken (reason required) |
| Return to Store | consumption → branch stock | unused material brought back |

Rules: staff (washer / QC) see and edit only their own **draft** requests; Front Desk sees the
branch's requests; only **Car Wash Managers** approve, reject and issue. Issuing never takes more
than the branch has (Floor Issue / Wastage). Requests are isolated per branch.

## Where

| Menu | What |
|---|---|
| Configuration > Consumables > Requests (managers) / Operations > Consumable Requests (floor staff) | kanban by status, list, form with Submit / Approve / Reject / Issue Stock |
| Configuration > Consumables > Stock | consumables with **On Hand** at the current branch, editable **Minimum Stock**, status In / Low / Out (filters *Low Stock*, *Needs Restock*) |
| Configuration > Consumables > Receive Stock | Inventory receipts (restock) |
| Reporting > Consumables > Consumption Analysis | pivot / graph / list of all consumption |
| Configuration > Consumables > Consumable Products | create / edit consumable products |
| Booking form | **Consumables** smart button (what the booking used) |
| Dashboard | **Consumables** card: low-stock items with fill bars, requests to approve / issue |
| Settings | Car Wash > Configuration > Settings > Operations > **Consumable Management** switch |

Minimum stock is an Odoo reordering rule of the branch warehouse with a *manual* trigger (no
automatic purchase is attempted; the Purchase app isn't required).

On install: every branch with bays gets a warehouse if it had none (a branch without one used to
consume nothing), and products already used in service materials are flagged as consumables.

## Install / tests

```bash
python3 odoo-bin -c <your.conf> -d <database> -i carwash_consumable
python3 odoo-bin -c <your.conf> -d <test-database> --test-tags /carwash_consumable --stop-after-init
```

## Manual test steps

Use a copy of production, as a Car Wash Manager (plus a Washer user for steps 6-7).

1. **Settings** - Car Wash > Configuration > Settings > Operations: *Consumable Management* ticked.
2. **Create a consumable** - Configuration > Consumables > Consumable Products > New: *Car Shampoo*, unit
   *L*, Car Wash tab: *Car Wash Consumable* ticked. Save.
3. **Stock it** - Configuration > Consumables > Receive Stock > New: receive **20 L** of Car Shampoo into the
   branch warehouse, Validate.
4. **Minimum stock** - Configuration > Consumables > Stock: Car Shampoo shows On Hand 20. Set *Minimum Stock* =
   **15** → status *In Stock*. Set it to **25** → *Low Stock* (orange). Put it back to 15.
5. **Service recipe** - Configuration > Services & Booking > Services > *Basic Exterior Wash* >
   Car Wash tab > materials: add Car Shampoo, **0.5** per service.
6. **Booking consumption** - create and complete a booking with Basic Exterior Wash. On the
   booking, the **Consumables** button shows 0.5 L of Car Shampoo; Stock shows **19.5**.
7. **Floor issue (as Washer)** - Operations > Consumable Requests > New: Floor Issue, Car Shampoo **2**,
   reason "Bay 2 rush" > **Submit**. The washer can't Approve and can't edit it any more.
8. **Approve & issue (as Manager)** - the manager has a To-Do "Approve consumable request"; open
   it > **Approve** > **Issue Stock** > OK. Status *Issued*; Stock shows **17.5**.
9. **Not enough stock** - request **100** L, submit, approve, Issue Stock → error *Not enough
   stock* listing the shortage; the request stays *Approved*.
10. **Wastage** - New request, Wastage / Damage, 1 L, no reason → Submit refuses; add a reason →
    submit, approve, issue → Stock **16.5**.
11. **Return** - Return to Store, 1 L → after issue Stock **17.5**.
12. **Reject** - submit another request, manager clicks **Reject**, enters a reason → *Rejected*
    with the reason shown in red; *Reset to Draft* re-opens it.
13. **Low-stock alert** - set Minimum Stock to 30. Dashboard > **Consumables** card lists Car
    Shampoo as *Low stock*. Run Settings > Technical > Scheduled Actions > *Car Wash: Low-stock
    consumable alerts* > Run Manually → the manager gets a To-Do on the product (not duplicated
    on a second run).
14. **Analysis** - Reporting > Consumables > Consumption Analysis: rows per consumable, columns Service /
    Floor Issue / Wastage / Return; group by Branch and Month.
15. **Branch isolation** - switch to another branch (top right): Stock, Requests and the
    dashboard card show that branch only.
16. **Switch off** - Settings: untick *Consumable Management* → Consumables menu and dashboard
    card disappear; tick again → back (no data lost).
