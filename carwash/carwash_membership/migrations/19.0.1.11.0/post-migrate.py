"""Plans get a Monthly and a Yearly amount (the customer picks one when joining) instead of one billing period.

- plans: the amounts come from the billing product's price and the plan's old billing period
  (monthly 1000 -> 1000 a month / 12000 a year; yearly 9000 -> 750 a month / 9000 a year; quarterly 2700 -> 900 / 10800)
- memberships: billed yearly if their plan was yearly, else monthly; the end date covers everything paid;
  the free washes now restart every month (from the current period's start)
"""


def migrate(cr, version):
    cr.execute("""
        SELECT 1 FROM information_schema.columns
         WHERE table_name = 'carwash_membership_plan' AND column_name = 'billing_period'
    """)
    old_period = "p.billing_period" if cr.fetchone() else "'monthly'"
    cr.execute(f"""
        SELECT p.id, COALESCE(pt.list_price, 0), {old_period}
          FROM carwash_membership_plan p
          JOIN product_product pp ON pp.id = p.product_id
          JOIN product_template pt ON pt.id = pp.product_tmpl_id
         WHERE COALESCE(p.monthly_price, 0) = 0 AND COALESCE(p.yearly_price, 0) = 0
    """)
    yearly_plans = []
    for plan_id, price, period in cr.fetchall():
        if period == "yearly":
            monthly, yearly = round(price / 12, 2), price
            yearly_plans.append(plan_id)
        elif period == "quarterly":
            monthly, yearly = round(price / 3, 2), price * 4
        else:
            monthly, yearly = price, price * 12
        cr.execute(
            "UPDATE carwash_membership_plan SET monthly_price = %s, yearly_price = %s WHERE id = %s",
            (monthly, yearly, plan_id),
        )
    if yearly_plans:
        cr.execute(
            "UPDATE carwash_membership SET billing_period = 'yearly' WHERE plan_id = ANY(%s)", (yearly_plans,)
        )
    cr.execute("UPDATE carwash_membership SET billing_period = 'monthly' WHERE billing_period IS NULL")
    cr.execute("""
        UPDATE carwash_membership
           SET valid_until = GREATEST(valid_until, paid_until),
               paid_until = GREATEST(valid_until, paid_until)
         WHERE paid_until IS NOT NULL OR valid_until IS NOT NULL
    """)
    cr.execute("""
        UPDATE carwash_membership
           SET wash_period_start = COALESCE(period_start, start_date)
         WHERE wash_period_start IS NULL AND state = 'active'
    """)
