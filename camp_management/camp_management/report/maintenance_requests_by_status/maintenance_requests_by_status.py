# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

import frappe


def execute(filters=None):
	columns = get_columns()
	data = get_data()
	return columns, data


def get_columns():
	return [
		{
			"fieldname": "status",
			"label": "Status",
			"fieldtype": "Data",
			"width": 150,
		},
		{
			"fieldname": "total",
			"label": "Total",
			"fieldtype": "Int",
			"width": 120,
		},
	]


def get_data():
	return frappe.db.sql(
		"""
		select status, count(*) as total
		from `tabMaintenance Request`
		group by status
		"""
	)
