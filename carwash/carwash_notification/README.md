# Car Wash Notifications (`carwash_notification`)

Customer email notifications for the car wash, built on Odoo's **mail** module: mail templates,
the outgoing mail queue, and a note in the record's chatter for every email sent.

## Notifications

| Key | Email | Sent when | Record |
|---|---|---|---|
| booking_request | Booking request received | a car wash booking request (lead) is created – website or phone | Booking Request |
| booking_confirmed | Booking confirmed | booking confirmed – services, **package & saving**, membership saving, total, token | Booking |
| booking_updated | Booking updated | date/time or **package** changes on a confirmed booking | Booking |
| booking_reminder | Visit reminder | hourly job: confirmed visits within the next *N* hours (default 24); not for bookings made < 2 h ago; once per visit (again if it's moved) | Booking |
| booking_ready | Ready for pickup | end of service (amount to pay) | Booking |
| booking_cancelled | Booking cancelled | a confirmed/arrived booking is cancelled | Booking |
| membership_payment_request | Payment request | billing order sent (join / renewal) – Pay now link | Membership |
| membership_activated | Membership activated | **first** payment – welcome + benefits | Membership |
| membership_renewed | Membership renewed | later payments – new end date | Membership |
| membership_expiring | Ending soon – renew | daily job: *N* days (default **2**) before the paid period ends, once per period, not if the next period is already paid – **Renew now** link | Membership |
| membership_expired | Membership expired | the daily billing job lapses it | Membership |
| membership_cancelled | Membership cancelled | membership cancelled | Membership |

The vehicle-ready / booking-confirmed emails of `carwash_membership` and its membership emails are
routed through this module (one email, never two). The rating request email stays in
`carwash_jobcard` (Customer Ratings switch).

## Settings

*Car Wash > Configuration > Settings > Notifications*

- **Booking emails** / **Membership emails** – one switch per notification (all on by default).
- **Reminder timing** – *Reminder before the visit (hours)* (24), *Renewal reminder (days before
  the end)* (2).
- **Email Templates** – edit the wording of any email (templates are `noupdate`: your edits survive
  module upgrades).

Scheduled actions: *Car Wash: Visit reminders* (hourly), *Car Wash: Membership renewal reminders*
(daily). Emails go through the standard mail queue (*Mail: Email Queue Manager*).

**An outgoing mail server is required for emails to leave Odoo**: Settings > General Settings >
Discuss/Emails > *Use Custom Email Servers* (or Settings > Technical > Outgoing Mail Servers).

## Install / tests

```bash
python3 odoo-bin -c <your.conf> -d <database> -i carwash_notification -u carwash_membership
python3 odoo-bin -c <your.conf> -d <test-database> --test-tags /carwash_notification --stop-after-init
```

## Manual test steps

Use a copy of production. Give the test customer **your own email address**. Without a mail
server you can still check everything in *Settings > Technical > Emails* (activate developer mode)
– each email appears there – and in the record's chatter ("Email sent to …").

1. **Mail server** – configure an outgoing mail server and *Test Connection* (or skip and check
   *Technical > Emails* as above).
2. **Settings** – Car Wash > Configuration > Settings > Notifications: all switches on, 24 hours,
   2 days. *Email Templates* lists the 12 car wash emails.
3. **Booking request** – book on the website (or create a booking request by phone in Booking
   Requests) → email *We received your car wash booking request*.
4. **Confirmed** – Confirm Booking (or confirm a booking with a **package**) → email *Booking
   confirmed – CW/… on …* showing services, package saving, total; chatter shows *Email sent to*.
5. **Updated** – on the confirmed booking change the time slot (or the package) → *Your booking …
   was updated* with the new time. Editing notes sends nothing.
6. **Reminder** – make a confirmed booking for tomorrow, wait 2 hours (or set its creation earlier)
   and run *Scheduled Actions > Car Wash: Visit reminders > Run Manually* → *Reminder: your car
   wash …*. Run again → no second email.
7. **Ready** – start and end the service (End Service) → *Your vehicle … is ready for pickup*.
8. **Cancelled** – cancel another confirmed booking → *Your booking … was cancelled*.
9. **Membership payment / activated** – join a plan on the website (or Request Payment) →
   *Complete your … membership payment*; pay it → *Welcome! Your … membership is active*.
10. **Renewed** – pay the next period (My Membership > Pay next period now) → *… membership is
    renewed*.
11. **Renew reminder (2 days)** – set a membership's *Paid Until* to the day after tomorrow (or wait),
    run *Car Wash: Membership renewal reminders* → *Your … membership ends on … – renew now* with a
    **Renew now** button. Run again → nothing (one per period).
12. **Expired / cancelled** – let a membership lapse (Paid Until in the past + run the billing job)
    → *… has expired*; cancel one → *… was cancelled*.
13. **Switches** – untick *Booking confirmed* → confirming sends nothing; tick it again. Change
    *Renewal reminder* to 7 days → memberships ending within a week get the reminder.
14. **Edit a template** – Email Templates > *Car Wash: Booking Confirmed* > change a sentence →
    the next confirmation uses it.
