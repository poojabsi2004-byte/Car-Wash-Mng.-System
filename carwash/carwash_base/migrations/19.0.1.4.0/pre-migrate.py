def migrate(cr, version):
    """Time slots can now be set per branch: the same time may exist once for all branches and
    once for a specific branch, so the old "one slot per time" database constraint goes."""
    cr.execute("ALTER TABLE carwash_time_slot DROP CONSTRAINT IF EXISTS carwash_time_slot_hour_uniq")
