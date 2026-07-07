# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

import frappe


def execute(filters=None):
	filters = filters or {}
	columns = get_columns()
	data = get_data(filters)
	return columns, data


def get_columns():
	return [
		{
			"fieldname": "camp",
			"label": "Camp",
			"fieldtype": "Link",
			"options": "Camp Master",
			"width": 150,
		},
		{
			"fieldname": "request_count",
			"label": "Request Count",
			"fieldtype": "Int",
			"width": 120,
		},
		{
			"fieldname": "total_cost",
			"label": "Total Cost",
			"fieldtype": "Currency",
			"width": 150,
		},
	]


def get_data(filters):
	conditions = ""
	if filters.get("camp"):
		conditions = "and mr.camp = %(camp)s"

	return frappe.db.sql(
		f"""
		select mr.camp, count(mr.name) as request_count, sum(mr.maintenance_cost) as total_cost
		from `tabMaintenance Request` mr
		where mr.docstatus < 2 {conditions}
		group by mr.camp
		order by total_cost desc
		""",
		filters,
	)
