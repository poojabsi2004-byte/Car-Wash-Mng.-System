# Car Wash Staff Attendance (`carwash_attendance`)

Branch-wise staff attendance for the Car Wash app, built on Odoo's standard
**Attendances** app (`hr_attendance`: check-in / check-out, kiosk, overtime).

## What it adds

| Where | What |
|---|---|
| Attendance records | **Branch** of every attendance = the staff member's branch when they checked in (kept if they move branch later). Filter *Today*, *Car Wash Staff*, group by *Branch*. |
| Employee form | **Attendance** tab (after *Staff Role*): status, **Check In / Check Out** button, last check-in/out, hours worked today, attendance history with branch. |
| Menus | **Staff → Attendances** (today, grouped by branch). **Configuration → Staff → Attendances**. Attendance settings (kiosk, overtime): link in *Car Wash → Configuration → Settings → Staff*. |
| Dashboard | **Staff Attendance** section at the end (managers / owner): checked in, checked out, not in today, hours worked today, and a card per person checked in. Five cards are shown; with more than five, use the ‹ › arrows to slide. Follows the branch selected in the company switcher. |
| Settings | **Car Wash → Configuration → Settings → Staff → Staff Attendance** switch (on by default). Off = tab, menus and dashboard section hidden, Check In/Out disabled. |
| Access | Car Wash **Managers** get *Attendances: Officer – Manage all attendances*. Other staff check in through the kiosk / Attendances app as usual. |

The Configuration menu is organised in sections: **Settings**, **Services & Booking**,
**Operations**, **Staff**, **Customers**.

## Install / upgrade

```bash
python3 odoo-bin -c <your.conf> -d <database> -i carwash_attendance -u carwash_base
```

`-i carwash_attendance` also installs Odoo **Attendances** (`hr_attendance`) if needed.
`-u carwash_base` refreshes the reorganised Configuration menu of the other car wash modules.

## Automated tests

```bash
python3 odoo-bin -c <your.conf> -d <test-database> --test-tags /carwash_attendance --stop-after-init
```

Covers: manager attendance rights, branch recorded and kept, Check In / Check Out from the
employee, dashboard counts and branch scoping (6 people in = more than one slide), switch off.

## Manual test steps

Use a **copy** of the production database, logged in as a Car Wash Manager (and Settings admin
for step 1).

1. **Settings** – *Car Wash → Configuration → Settings*: under **Staff**, *Staff Attendance* is
   ticked. The links *Attendances* and *Attendance Settings (kiosk, overtime)* open.
2. **Configuration menu** – *Car Wash → Configuration* shows *Settings* then the headers
   *Services & Booking*, *Operations*, *Consumables*, *Staff* (Staff Roles, Attendances),
   *Customers*.
3. **Give staff a role** – *Staff → Staff*, open an employee, *Staff Role* tab → *Add a line* →
   *Washer*. Check the employee's company is the right **branch** (*Work* tab → Company).
4. **Check in from the employee** – open the *Attendance* tab → **Check In**. Expected: badge
   *Checked in*, button turns into **Check Out**, a new line in the history with the branch.
5. **Check out** – click **Check Out**. Expected: *Checked out*, check-out time and worked hours
   on the line, *Worked Today* updated.
6. **Branch-wise list** – *Staff → Attendances*: today's attendances grouped by **Branch**.
   Try the *At Work* filter and *Group By → Branch*.
7. **Dashboard** – check in 6 or more staff of the same branch (steps 3–4, or the Attendances
   kiosk). Open *Car Wash → Dashboard* and scroll to the end:
   - *Staff Attendance* shows the counts (Checked in / Checked out / Not in today / Worked today),
   - 5 cards are visible; the **›** arrow slides to the next ones, **‹** back,
   - clicking a card opens the employee; *All attendances* opens the list,
   - switch branch in the company switcher (top right): the section shows that branch only.
8. **Branch is kept** – move a checked-out employee to another branch (*Work* tab → Company):
   their past attendances keep the old branch.
9. **Switch off** – Settings → untick *Staff Attendance* → Save. Expected: no *Attendance* tab on
   employees, no *Attendances* menus, no dashboard section. Tick it again → everything is back
   (attendance data is never deleted).
10. **Access** – log in as a Front Desk / Washer user: no Configuration menu; they can still use
    the Attendances kiosk / app to check themselves in.
