# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _
from frappe.utils import date_diff, now_datetime, today

class RoomAllocation(Document):
    def validate(self):
        """
        Runs calculations and validation logic before saving/submitting.
        """
        self.calculate_duration()
        self.fetch_department_fallback()
        self.validate_bed_availability()

    def on_submit(self):
        """
        Triggered when the Allocation is submitted (Approved/Activated).
        Locks the bed and updates its reference points.
        """
        if self.allocation_status == "Active":
            self.lock_bed()

    def on_cancel(self):
        """
        Triggered when an active or approved allocation is cancelled.
        Releases the bed.
        """
        self.release_bed(status_on_release="Available", description=f"Allocation cancelled via {self.name}")

    def calculate_duration(self):
        """
        Calculates the duration in days using: 
        Actual Check-Out Date (if available) or Expected Check-Out Date - Check-In Date.
        """
        start_date = self.check_in_date or today()
        end_date = self.actual_check_out_date or self.expected_check_out_date
        
        if end_date:
            if end_date < start_date:
                frappe.throw(_("Check-Out Date cannot be earlier than the Check-In Date."))
            self.duration_days = date_diff(end_date, start_date)
        else:
            self.duration_days = 0

    def fetch_department_fallback(self):
        """
        FR-AL-07: Automatically fetches the default Department from the linked Employee profile, 
        allowing manual override if already provided.
        """
        if self.employee and not self.department:
            self.department = frappe.db.get_value("Employee", self.employee, "department")

    def validate_bed_availability(self):
        """
        FR-AL-02: Validates that the targeted Bed is 'Available' prior to submission.
        Also blocks double-booking by confirming no other document currently retains a lock on it.
        """
        if not self.bed:
            return

        # Check the bed status in the Bed Master database
        bed_status, locked_by = frappe.db.get_value("Bed Master", self.bed, ["status", "current_allocation"])
        
        # We only strictly block it if it's not already locked by *this* ongoing allocation
        if bed_status != "Available" and locked_by != self.name:
            frappe.throw(
                _("Bed {0} is currently {1} and cannot be selected. It is locked by transaction {2}.").format(
                    frappe.bold(self.bed),
                    frappe.bold(bed_status),
                    frappe.bold(locked_by or _("Unknown"))
                )
            )

    def lock_bed(self):
        """
        Performs the transactional lock on the Bed Master record, 
        and flags an audit history record into the Bed Status Log.
        """
        previous_status = frappe.db.get_value("Bed Master", self.bed, "status")
        
        # Core Update: Flip status to Occupied, tie occupant and transaction links
        frappe.db.set_value("Bed Master", self.bed, {
            "status": "Occupied",
            "current_occupant": self.employee,
            "current_allocation": self.name
        })

        # Generate Immutable History Log Entry
        self.log_bed_status_change(
            prev_status=previous_status,
            new_status="Occupied",
            remarks=f"Employee checked in via {self.name}"
        )

        # Trigger hierarchy rollup totals recalculation
        self.update_hierarchy()

    def release_bed(self, status_on_release="Available", description=None):
        """
        FR-AL-04: Clears occupant details and releases the bed lock.
        """
        previous_status = frappe.db.get_value("Bed Master", self.bed, "status")

        frappe.db.set_value("Bed Master", self.bed, {
            "status": status_on_release,
            "current_occupant": None,
            "current_allocation": None
        })

        self.log_bed_status_change(
            prev_status=previous_status,
            new_status=status_on_release,
            remarks=description or f"Checked out via {self.name}"
        )

        self.update_hierarchy()

    def log_bed_status_change(self, prev_status, new_status, remarks):
        """
        System-generates a clean, read-only tracking footstep row inside DocType 8 (Bed Status Log).
        """
        log = frappe.get_doc({
            "doctype": "Bed Status Log",
            "bed": self.bed,
            "room": self.room,
            "previous_status": prev_status,
            "new_status": new_status,
            "changed_on": now_datetime(),
            "changed_by": frappe.session.user,
            "reference_doctype": self.doctype,
            "reference_name": self.name,
            "remarks": remarks
        })
        log.insert(ignore_permissions=True)

    def update_hierarchy(self):
        """
        Cascades total count changes upward through Rooms, Blocks, and Camps.
        """
        if self.room:
            # Dynamically import helper from bed master script file to prevent code replication
            from camp_management.camp_management.doctype.bed_master.bed_master import update_hierarchy_metrics
            update_hierarchy_metrics(self.room)