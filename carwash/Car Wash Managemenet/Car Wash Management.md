# Car Wash Management System (Odoo 19) – Developer & Client Guides

This document provides a comprehensive plan for building a **2026-ready Car Wash Management System** as an Odoo 19 app.  It includes both a **Developer Implementation Guide** (with architecture, module design, and integration details) and a **Client Feature Overview** (a customer-facing description of capabilities).  We emphasize practical, scalable design for all car wash types (from small manual shops to fully automated tunnels), and highlight advanced automation features like PLC control, IoT sensors, and license-plate recognition.  

> **Key integrations:** PLC-controlled wash tunnels, ultrasonic liquid-level sensors for automatic restocking, and LPR cameras for touchless entry.  
> **Odoo best practices:** Modular design with dedicated models, use of standard apps (CRM, Sales, Inventory, POS, etc.), and Odoo’s new JSON/REST API for external hardware.  

We will not cover unrelated topics like CI/CD or backup – the focus is on product **features, modules, and workflows**. 

---

## Developer Guide: Architecture & Implementation

### 1. Module Architecture & Data Model

We recommend a **modular Odoo addon** structure.  For example, create a main `carwash_base` module and specialized submodules (each with its own `__manifest__.py`) such as:

```
carwash_base/
   ├── models/
   │    ├── carwash_customer.py        # Extends res.partner for customers, tags, communication logs
   │    ├── carwash_vehicle.py         # Vehicle master (license plate, make/model, photos, history)
   │    ├── carwash_service.py         # Service packages (wash types, prices, durations, requirements)
   │    ├── carwash_appointment.py     # Appointments / bookings (customer, vehicle, services, status)
   │    ├── carwash_bay.py             # Washing Bay model (bay type, status, current vehicle)
   │    ├── carwash_queue.py           # Live Queue (token, waiting times, assigned bay)
   │    ├── carwash_jobcard.py         # Job card (assigned employee, start/end times, service tasks)
   │    ├── carwash_inspection.py      # Pre-/post-wash vehicle inspection (photos, damages)
   │    ├── carwash_quality.py         # Quality control (checklist, pass/fail, rework)
   │    ├── carwash_membership.py      # Membership plans and entitlements (wrapping Odoo Subscriptions)
   │    ├── carwash_loyalty.py         # Loyalty program (points, rewards, coupons)
   │    ├── carwash_commission.py      # Employee commission rules
   │    ├── carwash_multibranch.py    # Multi-location (branch) support, record rules per branch
   │    ├── carwash_portal.py         # Customer portal extensions (bookings, history)
   │    ├── carwash_iot.py            # IoT device handlers (API endpoints for sensors, cameras)
   │    └── ... (other components)
   ├── security/ir.model.access.csv  # Access controls
   ├── views/                        # XML views (form, list, calendar, Kanban, dashboards)
   ├── data/                         # Data imports (services, initial config, email templates)
   ├── reports/                      # QWeb receipt and membership statement templates
   ├── controllers/                  # HTTP controllers for external integrations (PLC, cameras)
   └── __manifest__.py
```

Use **Odoo’s standard models** and fields. For example, vehicle and appointment records might extend `fleet.vehicle` or use related one2many fields. Enforce rules and constraints with `@api.constrains` and SQL constraints (e.g. no overlapping bay slots). Follow best practices: typed fields, `@api.depends` for computed fields, and security via `ir.model.access.csv` and record rules (especially for multi-branch data scoping). For multi-branch, leverage the `res.company` model or a custom `branch_id` field with domain rules, as in specialized multi-site Odoo apps.

Dependencies should include relevant apps: at minimum `base`, `sale_management` (or `point_of_sale`), `calendar` (for scheduling), `stock` (inventory), `purchase` (RFQs), `fleet` (optional for vehicles) and `contacts` (for customers). Avoid duplicating functionality already in Odoo (e.g. use Odoo’s Inventory reordering rules and Purchase app rather than custom procurement logic).

### 2. Core Features (High Priority)

#### a. Customers & Vehicles
- **Customer Master** (`res.partner`): store name, contact, tags, communication history.
- **Vehicle Master** (`carwash.vehicle` or `fleet.vehicle`): store license plate, VIN, model/year, photos, associated customer(s), and service history.  
- Maintain one-to-many between customer and vehicles; support multiple vehicles per customer.

#### b. Services & Pricing
- **Service Packages**: Odoo products representing wash types (Basic Wash, Premium Wash, Waxing, Detailing, etc.), each with duration, base price, tax, and required materials.  
- Use Odoo’s pricing (pricelists) for special rates (e.g. by vehicle category, weekday, or membership discounts).  
- Add-on services modeled as optional lines (e.g. +Interior Clean, +Wax).

#### c. Appointments & Queue
- **Appointment Scheduling**: A model `carwash.appointment` linking customer, vehicle, date/time, selected service(s), employee, and bay.  
- **Status Workflow**: Implement a state machine (e.g. *Draft → Confirmed → Vehicle Arrived → Washing → QC → Ready → Delivered → Done*). Use Odoo `@api.model` or `@api.depends` methods to compute times, and transitions for reschedule/cancel.
- **Queue Management**: A live Kanban/board view (`carwash.queue`) showing waiting vehicles, bays, and statuses (Waiting, In Service, QC, Ready). Assign “token” numbers and estimate times. This can be a filtered view of upcoming/in-progress `carwash.appointment` records.
- **Bay Management**: Model `carwash.bay` with fields for bay name/number, type (hand wash vs. tunnel vs. detail bay), status, assigned employee. The Kanban/Calendar view shows bay occupancy by appointment slot, preventing double-booking.
- **Kiosk & Display**: Use Odoo’s web controllers or embedded screens for a “now serving” display and self-service check-in (driver scans QR code or enters plate via touch screen).

#### d. Point-of-Sale & Payment
- **POS Integration**: Extend Odoo POS to include wash packages and add-ons on the screen. When an appointment is invoiced or walked-in, the POS links the sale to the `carwash.appointment`. Validate memberships at POS (no wash beyond entitlement).  
- **Payment Methods**: Support cash, card, mobile wallets, split payments, advance payments, and return orders for refunds/discounts. Generate tax invoices/receipts via Odoo’s accounting integration.
- **Job Card**: Generate a job card (printout or digital) for each wash with details: customer, vehicle, service, assigned worker/bay, start/end times. Use Odoo reports (QWeb) or a printable PDF template.

#### e. Inventory & Consumables
- **Product Stock**: Use Odoo Inventory for shampoos, waxes, chemicals, cloths, etc. Each service consumes products.  
- **Automatic Replenishment**: Set reordering rules on each consumable. Optionally integrate IoT sensors (see below) to feed Odoo real-time inventory levels. When stock falls below minimum, Odoo (via scheduled actions) auto-generates RFQ/order.  
- **Batch/Lot Tracking**: If needed for chemical expiration control.

#### f. Employees & Shifts
- **Employee Roles**: Use Odoo `hr.employee` for washers, detailers, cashiers, supervisors. Assign employees to appointments and bays.  
- **Scheduling & Productivity**: Optionally track shifts and attendance. Generate commission/bonus rules (`carwash.commission`) based on number of services or revenue per employee.

#### g. History & CRM
- **Service History**: Link every completed wash to the vehicle record. Allow quick lookup: “last time this car came for a Premium wash and needed headlight polishing.” Build reports on customer or vehicle visit history.  
- **CRM & Marketing**: Tag customers (new, frequent, lapsed) and schedule reminders (via Marketing Automation) for follow-ups or membership renewals. Use Odoo Email or SMS templates for campaigns (e.g. “You’re due for a wash!”).

### 3. Advanced Automation & IoT Integrations

#### a. PLC Tunnel Automation  
For automated wash tunnels (large installations), integrate Odoo with the wash equipment’s PLC: when the cashier rings up a *Premium Wash* package in POS or confirms an appointment, Odoo sends a command to the PLC to configure the machinery.  For example:
- Odoo exposes an internal API or message queue endpoint.  
- **Custom Controller**: A Python controller (e.g. `/carwash/plc/command`) that receives requests (JSON-RPC or REST) from POS or appointment workflow.  
- **PLC Connector**: A Python module uses standard industrial protocols (Modbus TCP/IP, Profinet, or OPC-UA) to talk to the tunnel’s PLC. This channel is well-supported by libraries (e.g. python-snap7 for Siemens PLCs).  
- **Workflow**: On point-of-sale or order validation, code queries the selected service and calls the PLC connector. The PLC then activates specific valves, jets, and brushes for that package. Optionally log PLC status back into Odoo for audit.  
- This follows patterns in manufacturing PLC-ERP integration. A recent study demonstrated real-time PLC–Odoo integration (for a bottle-sorting plant) using Ethernet protocols. We can similarly implement for wash hardware.

#### b. Chemical IoT Sensors (Liquid-Level Monitoring)  
Install IoT-based level sensors in each chemical tank (shampoo, wax, water, etc.). These sensors can send data (via MQTT or HTTP) to Odoo (through IoT controllers or webhooks).  
- **Sensor Gateway**: Use an IoT gateway (could be Odoo’s IoT Box or another Raspberry Pi) to interface sensors and send events.  
- **Odoo Handlers**: Create a handler (in `carwash_iot`) that receives sensor updates (e.g. `/iot/sensor_level`). When a tank level falls below a threshold (e.g. 15%), trigger Odoo to auto-generate a Purchase RFQ: use Odoo’s Procurement/Inventory API to replenish that product.  
- Odoo’s built-in reordering rules can schedule purchases, but IoT allows real-time triggering. For example, when soap goes below 15%, the handler calls a server action to create a draft RFQ to the supplier. This is a form of sensor-driven replenishment.
- Use Odoo’s automated actions or server-side code to implement: an IoT event handler reads the sensor value, matches it to a `product.product`, and writes to the forecasted quantity or directly creates a `purchase.order` with supplier and quantity.  
- This follows Odoo’s IoT concept: “inventory sensor shows stock below minimum → Odoo automatically generates a buy order”.

#### c. License Plate Recognition (LPR) & Access Control  
Integrate LPR cameras at entrances/exits to identify vehicles instantly:
- **Data Flow**: LPR camera captures plate → image is processed locally (or via cloud LPR service) → the plate number is sent to Odoo (via an API endpoint) as a “check-in” event.  
- **Odoo Processing**: Upon receiving the plate number, Odoo searches `carwash.vehicle` (or a custom registry) for a matching vehicle record.  
   - If found, it checks for an active subscription/membership (`carwash_membership`) or prepaid wash.  
   - If valid, Odoo triggers the gate to open (via a connected controller) and optionally sends a welcome message (“Welcome, [Customer Name]!” on a display).  
   - Odoo creates or confirms an appointment/visit log in the system, ready to be billed.  
   - If the customer is not found or no active membership, Odoo can prompt for payment or registration (e.g. at kiosk or attendant).  
- **Integration**: Develop a REST/JSON-RPC API (e.g. `/carwash/lpr/entry`) that LPR hardware calls with payload `{ "plate": "...", "timestamp": "..." }`. Use Odoo’s access rules to authenticate requests (e.g. a secret token).  
- **Workflow Automation**: Similar to the Survision LPR use case, this automates entry and payment: “The POS system automatically logs the customer’s visit and links it to their account… verifying membership instantly.”  
- For boom barrier control, have a PLC or relay hardware connected; Odoo’s controller can send an “open” command if the plate is verified. This provides a smooth, driver-friendly experience.

#### d. Other Integrations  
- **Kiosk Terminal**: For walk-in customers, build a self-service UI (Odoo website or POS mode) where drivers select a wash, enter plate or scan QR, and pay. This system communicates with Odoo via the same APIs (using Odoo’s JSON-RPC).  
- **Notifications**: Use Odoo’s built-in mail/SMS to inform customers at each step (arrival, wash started, ready, invoice ready).

### 4. Odoo Workflow and APIs

- **API Use**: Leverage Odoo 19’s new JSON API for ease of integration. Controllers can use `@route(type='json')` to expose endpoints that authenticate via API keys or tokens. The Ecosire carwash module notes that “the whole system is reachable over Odoo’s XML-RPC/JSON-RPC API for kiosks, license-plate cameras, or a mobile check-in app”. We will similarly ensure key functions (create appointment, confirm entry, fetch service history) are accessible via API.
- **Automated Actions**: Use server-side scheduled actions (`cron`) and automated actions for things like membership billing, sending reminders, and moving workflow states for no-shows or completed tasks.
- **Dashboard/KPI**: Create Odoo dashboard views (using `action=` and `graph` definitions) for key metrics: active cars, queue lengths, daily revenue, inventory low alerts, etc. Utilize Odoo’s model methods to compute KPIs, then visualize in Kanban/Graph views for managers.

### 5. Implementation Phases (High-Level)

To manage scope, we can structure development in phases:
1. **Phase 1 (MVP):** Core models (Customers, Vehicles, Services), Appointment scheduling with Bay/Queue, POS integration, Inventory, and simple Service History.  
2. **Phase 2:** Add Employee tracking, Job Cards, Vehicle Inspection forms, Quality Control workflows, and Reports.  
3. **Phase 3:** Membership plans, Recurring Billing (Odoo Subscriptions), Loyalty program, Notifications (Email/SMS).  
4. **Phase 4:** Multi-branch support (companies, record rules), Customer portal, QR code scanning, Employee Commission rules.  
5. **Phase 5:** IoT integrations (sensors, PLC control), Computer Vision (optional), Advanced Dashboards.  

This ensures a working product early, with advanced automation added later.

---

## Client Overview: Features & Benefits

**Target Audience:** Car wash owners/managers (small local shops to large automated centers) looking for a unified system to handle bookings, operations, and customer management.  

### Core Benefits
- **One Dashboard for Operations:** Manage all bays, appointments, and staff from a single Odoo interface.  
- **Faster Turnaround:** Digital queue management and assignment ensure cars are washed quickly and efficiently.  
- **Customer Satisfaction:** Automated reminders, loyalty programs, and smooth entry processes improve the experience.  
- **Complete Record Keeping:** Every wash is logged in the vehicle’s history; generate reports on revenue, membership usage, and more.  

### Key Features

- **Flexible Appointment Booking:** Customers (or staff) can schedule a wash online or at the counter. The system assigns a service bay and updates a live queue. You can reschedule or cancel easily.  
- **Real-Time Queue Board:** A visual screen shows waiting cars, current washes, and ready-for-pickup vehicles, reducing confusion and wait times.
- **Automated Wash Tunnel Control:** For high-tech centers, the POS directly commands the wash tunnel machine. Ring up “Premium Wash” and the correct jets, wax sprayers, and brushes start automatically – no manual switch setting.
- **Instant Vehicle Recognition:** On entry, a camera reads the license plate. If the customer has a subscription or prepaid plan, the gate opens automatically and the system greets them by name. No tickets or staff needed.
- **Mobile/Kiosk Self-Service:** Walk-in drivers can use a tablet or kiosk to select their vehicle, pick a service, and pay on the spot. The system issues a queue token and adds them to the wash list.
- **Membership & Packages:** Offer monthly/annual wash packages (e.g. “10 Premium Washes for $300/month”). The system tracks remaining washes and renewals. At checkout, it verifies memberships so only valid members get free washes.
- **Loyalty & Rewards:** Customers earn points for every wash or dollar spent. Redeem points for discounts or free services. Send birthday coupons or referral bonuses via SMS/WhatsApp automatically.
- **Automatic Inventory Reordering:** Sensors monitor soap, wax, and water tanks. When levels are low, Odoo auto-generates a purchase request so you never run out of supplies. You save time and avoid downtime.  
- **Detailed Vehicle History:** For each car, track past services and notes. Know what add-ons were used last time (e.g. “last time we polished headlights after waxing this car”). This builds trust and upselling (offer the next recommended service).
- **Employee Management:** Assign washers and detailers to jobs. Track their productivity and even set up commission rules (e.g. “$2 bonus per Premium wash”).  
- **Multi-Location Support:** If you have multiple sites, run them from one Odoo instance. Each branch has its own bays, inventory, and staff, while reporting rolls up company-wide.
- **Accounting & Reporting:** Integrated billing and invoicing ensure all washes are accounted for. Get automatic daily/weekly/monthly financial reports, and dashboards showing revenue by service, branch, or customer segment.
- **Safety & Inspection:** Take photos of each vehicle on arrival to note existing scratches (prevent disputes). After the wash, a checklist ensures nothing is missed (exterior clean, interior vacuumed, etc.). Supervisors can sign off on quality.

### Smart Automations

1. **PLC Tunnel Control:** *Advanced centers only.* The POS and scheduling system link directly to your washing machines. Select a wash package and the system activates the exact sequence in the tunnel (no manual intervention).  
2. **IoT Stock Monitoring:** *Enterprise feature.* Ultrasonic/pressure sensors in chemical tanks feed real-time levels into Odoo. When a tank is 15% empty, Odoo automatically drafts a supplier RFQ, so you never fear running out mid-day.  
3. **LPR Gate Entry:** *Ultimate convenience.* License-Plate Recognition cameras at the gate check membership status instantly. Authorized cars glide through without stopping. This speeds up traffic and delights VIPs.  
4. **Customer Portal:** Clients can view their appointments, history, and membership status online. They can easily book or renew plans via a mobile-friendly portal.

### Why Odoo and This Module?

- **Fully Integrated:** We build on Odoo’s trusted framework (no cobbling together of disparate tools). CRM, POS, Accounting, HR, and Inventory all work seamlessly with the car wash features.  
- **Future-Ready:** Designed with next-gen IoT in mind, this system stays relevant. You can start simple (manual processes) and layer in automation (sensors, AI suggestions) as you grow.  
- **Flexible & Customizable:** It works for a single-owner detail shop or a multi-city chain. You choose your services, pricing, and rules – the software enforces them reliably.  
- **User-Friendly:** The front desk app is intuitive: pick the package, scan the vehicle or tag, and done. No spreadsheet manual scheduling needed.  
- **Proven Concepts:** We incorporate industry best practices (queue displays, job cards, membership logic). Similar systems use dedicated “bay” models and appointment states to keep operations smooth.  

In summary, this Odoo-based Car Wash system unifies every part of the business. It automates routine tasks (inventory, billing, entry), empowers staff with real-time data (queue status, past customer notes), and gives owners powerful control via dashboards and reports. By leveraging IoT and POS integrations, it turns a car wash into an intelligent, efficient operation – whether you run a small wash rack or a high-speed tunnel.  

**Citations:** Real-world examples show PLC–Odoo integration is feasible and accurate for industrial machines. Odoo’s IoT capability can trigger automatic reorders when inventory is low. And leading car wash solutions now use LPR at gates to speed up service and link vehicles to memberships. The above design incorporates these practices into the Odoo ecosystem.