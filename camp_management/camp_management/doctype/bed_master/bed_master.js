// Copyright (c) 2026, Sowaan and contributors
// For license information, please see license.txt

frappe.ui.form.on("Bed Master", {
	setup: function (frm) {
		// Filter Block based on selected Camp
		frm.set_query("block", function () {
			return {
				filters: { camp: frm.doc.camp },
			};
		});
		// Filter Room based on selected Block
		frm.set_query("room", function () {
			return {
				filters: { block: frm.doc.block },
			};
		});
	},
});
