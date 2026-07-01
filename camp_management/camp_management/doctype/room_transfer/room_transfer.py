# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _
from frappe.utils import now_datetime, today

class RoomTransfer(Document):
    def validate(self):
        """
        Runs pre-submission validations on the transfer record.
        """
        self.fetch_source_details_from_allocation()
        self.validate_source_allocation()
        self.validate_destination_bed()

    def on_submit(self):
        """
        Executes the atomic room transfer transaction.
        Updates the source allocation, creates the new destination allocation,
        and transitions the bed states cleanly.
        """
        self.execute_atomic_transfer()

    def fetch_source_details_from_allocation(self):
        """
        Convenience fields: Fetch the source bed and source room automatically 
        from the linked source room allocation.
        """
        if self.source_allocation:
            allocation_details = frappe.db.get_value(
                "Room Allocation", 
                self.source_allocation, 
                ["bed", "room"], 
                as_dict=True
            )
            if allocation_details:
                self.source_bed = allocation_details.bed
                self.source_room = allocation_details.room

    def validate_source_allocation(self):
        """
        Validates that the selected source allocation is active and belongs to the chosen employee.
        """
        if not self.source_allocation:
            return

        status, allocated_employee = frappe.db.get_value(
            "Room Allocation", 
            self.source_allocation, 
            ["allocation_status", "employee"]
        )

        if status != "Active":
            frappe.throw(_("The Source Allocation {0} must be 'Active' to process a transfer.").format(frappe.bold(self.source_allocation)))
        
        if allocated_employee != self.employee:
            frappe.throw(_("The Source Allocation {0} does not belong to the selected Employee {1}.").format(
                frappe.bold(self.source_allocation), frappe.bold(self.employee)
            ))

    def validate_destination_bed(self):
        """
        Validates that the targeted destination bed is currently 'Available' for booking.
        """
        if not self.destination_bed:
            return

        bed_status = frappe.db.get_value("Bed Master", self.destination_bed, "status")
        if bed_status != "Available":
            frappe.throw(_("Destination Bed {0} is currently {1} and is not available for transfer.").format(
                frappe.bold(self.destination_bed), frappe.bold(bed_status)
            ))

    def execute_atomic_transfer(self):
        """
        Handles the actual transfer sequence safely within the submission transaction block.
        """
        # --- PHASE 1: Close Out the Source Allocation ---
        transfer_day = self.transfer_date or today()
        
        # FIX: Update the submitted Room Allocation directly via the database 
        # to bypass the framework's document save validation lock.
        frappe.db.set_value(
            "Room Allocation", 
            self.source_allocation, 
            {
                "actual_check_out_date": transfer_day,
                "allocation_status": "Checked-Out"
            },
            update_modified=True
        )
        
        # Release old bed using the target helper function defined in Room Allocation
        source_alloc_doc = frappe.get_doc("Room Allocation", self.source_allocation)
        source_alloc_doc.release_bed(
            status_on_release="Available", 
            description=f"Released via Room Transfer {self.name}. Reason: {self.reason}"
        )

        # --- PHASE 2: Create and Activate the Destination Allocation ---
        new_alloc_doc = frappe.get_doc({
            "doctype": "Room Allocation",
            "employee": self.employee,
            "camp": self.destination_camp,
            "block": self.destination_block,
            "room": self.destination_room,
            "bed": self.destination_bed,
            "check_in_date": transfer_day,
            "allocation_status": "Active" 
        })
        
        new_alloc_doc.insert(ignore_permissions=True)
        new_alloc_doc.submit() # Automatically triggers lock_bed() inside Room Allocation

        # --- PHASE 3: Complete Transfer Tracking Links ---
        # Update current document fields safely post-submit
        self.db_set("new_allocation", new_alloc_doc.name)
        self.db_set("transfer_status", "Completed")

        # Inject historical audit tracking links into the logs
        self.log_transfer_history(new_alloc_doc.name)

    def log_transfer_history(self, new_allocation_id):
        """
        Logs descriptive entries into the immutable Bed Status Log for tracking transparency.
        """
        # Log entry for Destination Bed acquisition
        log_dest = frappe.get_doc({
            "doctype": "Bed Status Log",
            "bed": self.destination_bed,
            "room": self.destination_room,
            "previous_status": "Available",
            "new_status": "Occupied",
            "changed_on": now_datetime(),
            "changed_by": frappe.session.user,
            "reference_doctype": self.doctype,
            "reference_name": self.name,
            "remarks": f"Transferred in from Bed {self.source_bed} via {self.name}. New Alloc: {new_allocation_id}"
        })
        log_dest.insert(ignore_permissions=True)