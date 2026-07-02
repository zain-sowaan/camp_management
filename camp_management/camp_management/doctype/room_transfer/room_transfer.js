// Copyright (c) 2026, Sowaan and contributors
// For license information, please see license.txt

frappe.ui.form.on("Room Transfer", {
	setup: function (frm) {
		// Filter Destination Block based on selected Destination Camp
		frm.set_query("destination_block", function () {
			return {
				filters: { camp: frm.doc.destination_camp },
			};
		});
		// Filter Destination Room based on selected Destination Block
		frm.set_query("destination_room", function () {
			return {
				filters: { block: frm.doc.destination_block },
			};
		});
		// Filter Destination Bed based on selected Destination Room and only show Available beds
		frm.set_query("destination_bed", function () {
			return {
				filters: {
					room: frm.doc.destination_room,
					status: "Available",
				},
			};
		});
		// Filter Source Allocation to only the active allocation(s) of the selected employee
		frm.set_query("source_allocation", function () {
			return {
				filters: {
					employee: frm.doc.employee,
					allocation_status: "Active",
					docstatus: 1,
				},
			};
		});
	},
	employee: function (frm) {
		if (frm.doc.employee) {
			// Auto-fetch department on the UI when employee is picked
			frappe.db.get_value("Employee", frm.doc.employee, "department").then((r) => {
				if (r.message && r.message.department) {
					frm.set_value("department", r.message.department);
				}
			});
		}
	},
});
