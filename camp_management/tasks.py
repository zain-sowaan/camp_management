import frappe
from frappe.utils import now_datetime


def flag_overdue_maintenance_requests():
	"""
	FR-MM-07: Mark Maintenance Requests as overdue once Now > sla_due_datetime
	and the ticket has not yet reached Resolved/Closed.
	"""
	overdue_requests = frappe.get_all(
		"Maintenance Request",
		filters={
			"sla_due_datetime": ["<", now_datetime()],
			"status": ["not in", ["Resolved", "Closed"]],
			"is_overdue": 0,
		},
		pluck="name",
	)

	for name in overdue_requests:
		frappe.db.set_value("Maintenance Request", name, "is_overdue", 1, update_modified=False)

	if overdue_requests:
		frappe.db.commit()
