// Copyright (c) 2026, Sowaan and contributors
// For license information, please see license.txt

frappe.ui.form.on('Room Transfer', {
    setup: function(frm) {
        // Filter Block based on selected Camp
        frm.set_query('block', function() {
            return {
                filters: { 'camp': frm.doc.camp }
            };
        });
        // Filter Room based on selected Block
        frm.set_query('room', function() {
            return {
                filters: { 'block': frm.doc.block }
            };
        });
        // Filter Bed based on selected Room and only show Available beds
        frm.set_query('bed', function() {
            return {
                filters: { 
                    'room': frm.doc.room,
                    'status': 'Available'
                }
            };
        });
    },
    employee: function(frm) {
        if (frm.doc.employee) {
            // Auto-fetch department on the UI when employee is picked
            frappe.db.get_value('Employee', frm.doc.employee, 'department')
                .then(r => {
                    if (r.message && r.message.department) {
                        frm.set_value('department', r.message.department);
                    }
                });
        }
    }
});
