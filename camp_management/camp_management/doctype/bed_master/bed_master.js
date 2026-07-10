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
	refresh: function (frm) {
		if (frm.is_new()) {
			frm.add_custom_button(__("Generate Bed Sequence"), () =>
				show_generate_bed_sequence_dialog(frm)
			);
		}
	},
});

function show_generate_bed_sequence_dialog(frm) {
	const dialog = new frappe.ui.Dialog({
		title: __("Generate Bed Sequence"),
		fields: [
			{
				fieldname: "room",
				fieldtype: "Link",
				options: "Room Master",
				label: __("Room"),
				reqd: 1,
				default: frm.doc.room,
				get_query: () => (frm.doc.block ? { filters: { block: frm.doc.block } } : {}),
			},
			{
				fieldname: "bed_type",
				fieldtype: "Select",
				label: __("Bed Type"),
				options: "\nSingle\nBunk (Upper)\nBunk (Lower)",
				default: frm.doc.bed_type,
			},
			{ fieldname: "column_break_1", fieldtype: "Column Break" },
			{
				fieldname: "start_bed_number",
				fieldtype: "Data",
				label: __("Starting Bed Number"),
				description: __(
					"Leave blank to continue after the highest existing bed number in the room."
				),
			},
			{
				fieldname: "count",
				fieldtype: "Int",
				label: __("Number of Beds to Create"),
				reqd: 1,
				default: 1,
			},
		],
		primary_action_label: __("Generate"),
		primary_action: (values) => {
			frappe.call({
				method: "camp_management.camp_management.doctype.bed_master.bed_master.generate_bed_sequence",
				args: values,
				freeze: true,
				freeze_message: __("Generating beds..."),
				callback: (r) => {
					if (!r.message) return;
					dialog.hide();

					const { created, skipped_existing } = r.message;
					let message = __("Created {0} bed(s): {1}", [
						created.length,
						created.join(", "),
					]);
					if (skipped_existing.length) {
						message +=
							"<br>" +
							__("Skipped {0} number(s) already in use: {1}", [
								skipped_existing.length,
								skipped_existing.join(", "),
							]);
					}
					frappe.msgprint({
						title: __("Bed Sequence Generated"),
						message,
						indicator: "green",
					});

					frappe.set_route("List", "Bed Master", { room: values.room });
				},
			});
		},
	});

	dialog.show();
}
