# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _
from frappe.utils import add_to_date, now_datetime

class MaintenanceRequest(Document):
    def validate(self):
        """
        Validates data before saving and calculates the SLA timelines.
        """
        self.calculate_sla_due_date()
        self.handle_high_priority_maintenance_lock()

    def on_update(self):
        """
        Triggered after saving changes. Handles releasing maintenance statuses 
        when work finishes.
        """
        self.handle_resolution_and_release()

    def calculate_sla_due_date(self):
        """
        FR-MM-07: Automatically calculates the 'sla_due_datetime' based on 
        the priority matrix from the ticket reported date.
        """
        if not self.reported_date:
            self.reported_date = now_datetime()

        # Define priority SLA windows in hours
        sla_hours_map = {
            "High": 4,       # e.g., Critical HVAC or structural issue
            "Medium": 24,    # e.g., Minor plumbing or electrical issue
            "Low": 72        # e.g., Furniture repair
        }

        hours_to_add = sla_hours_map.get(self.priority, 24)
        self.sla_due_datetime = add_to_date(self.reported_date, hours=hours_to_add)

    def handle_high_priority_maintenance_lock(self):
        """
        FR-MM-03: Sets the linked Room Status to 'Maintenance' automatically 
        when a High-priority Maintenance Request is raised.
        """
        if self.priority == "High" and self.room and self.status not in ["Resolved", "Closed"]:
            current_room_status = frappe.db.get_value("Room Master", self.room, "room_status")
            
            if current_room_status != "Maintenance":
                frappe.db.set_value("Room Master", self.room, "room_status", "Maintenance")
                frappe.msgprint(
                    _("Room {0} status has been automatically set to {1} due to a High priority maintenance issue.")
                    .format(frappe.bold(self.room), frappe.bold("Maintenance"))
                )

            # Optional: If a specific bed is specified, take it offline
            if self.bed:
                current_bed_status = frappe.db.get_value("Bed Master", self.bed, "status")
                if current_bed_status != "Out of Service":
                    # Bypass standard role constraint because this is an automated system event, not a user action
                    frappe.db.set_value("Bed Master", self.bed, "status", "Out of Service")
                    
                    # Log the system change via the log module helper if configured
                    create_bed_status_log(
                        bed=self.bed,
                        room=self.room,
                        prev_status=current_bed_status,
                        new_status="Out of Service",
                        ref_doc="Maintenance Request",
                        ref_name=self.name,
                        remarks=f"Placed out of service due to High Priority Maintenance request {self.name}"
                    )

    def handle_resolution_and_release(self):
        """
        FR-MM-04: Automatically clears the room/bed maintenance blocks once the 
        ticket status transitions to Resolved or Closed.
        """
        if self.status in ["Resolved", "Closed"]:
            # Automatically set resolution date if not populated
            if not self.resolution_date:
                self.resolution_date = now_datetime().date()
                frappe.db.set_value(self.doctype, self.name, "resolution_date", self.resolution_date, update_modified=False)

            # Check if there are any *other* unresolved High priority requests for this room
            other_active_high_requests = frappe.db.exists(
                "Maintenance Request",
                {
                    "room": self.room,
                    "priority": "High",
                    "status": ["not in", ["Resolved", "Closed"]],
                    "name": ["!=", self.name]
                }
            )

            # If no other critical tasks exist, restore room and bed statuses to available safely
            if not other_active_high_requests and self.room:
                current_room_status = frappe.db.get_value("Room Master", self.room, "room_status")
                if current_room_status == "Maintenance":
                    frappe.db.set_value("Room Master", self.room, "room_status", "Available")
                    
            if self.bed:
                current_bed_status = frappe.db.get_value("Bed Master", self.bed, "status")
                if current_bed_status == "Out of Service":
                    frappe.db.set_value("Bed Master", self.bed, "status", "Available")
                    
                    create_bed_status_log(
                        bed=self.bed,
                        room=self.room,
                        prev_status="Out of Service",
                        new_status="Available",
                        ref_doc="Maintenance Request",
                        ref_name=self.name,
                        remarks=f"Restored to Available after resolution of ticket {self.name}"
                    )


def create_bed_status_log(bed, room, prev_status, new_status, ref_doc, ref_name, remarks):
    """
    Helper function to dynamically push an immutable entry into 'Bed Status Log' (DocType 8).
    This handles the audit trail specifications seamlessly.
    """
    log = frappe.get_doc({
        "doctype": "Bed Status Log",
        "bed": bed,
        "room": room,
        "previous_status": prev_status,
        "new_status": new_status,
        "changed_on": now_datetime(),
        "changed_by": frappe.session.user,
        "reference_doctype": ref_doc,
        "reference_name": ref_name,
        "remarks": remarks
    })
    log.insert(ignore_permissions=True)