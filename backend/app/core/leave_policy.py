"""Leave entitlement rules. Edit here (or move to a DB table later)."""

LEAVE_TYPES = ("Sick", "Casual", "Annual")
LEAVE_STATUSES = ("Pending", "Approved", "Rejected", "Cancelled")

# entitlement: days per calendar year, carry_forward_max: days carried into next year,
# half_day_allowed: a single-day application may be 0.5 day.
LEAVE_POLICY: dict[str, dict] = {
    "Sick": {"entitlement": 14.0, "carry_forward_max": 0.0, "half_day_allowed": True},
    "Casual": {"entitlement": 10.0, "carry_forward_max": 0.0, "half_day_allowed": True},
    "Annual": {"entitlement": 20.0, "carry_forward_max": 10.0, "half_day_allowed": False},
}

# Roster codes for a full-day approved leave.
LEAVE_ROSTER_CODE = {"Sick": "SL", "Casual": "CL", "Annual": "AL"}

# Continuous approved leave longer than this many calendar days triggers a new weekly-off /
# half-duty day, effective from the next roster week after the leave ends.
LONG_LEAVE_REPLAN_DAYS = 5
ROSTER_WEEK_START = 0  # Monday = 0 ... Sunday = 6 (first day of a roster week)
