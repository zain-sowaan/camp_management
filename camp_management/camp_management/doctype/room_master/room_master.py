# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _

class RoomMaster(Document):
    def validate(self):
        """
        Runs validations before saving the Room Master record.
        """
        self.fetch_camp_from_block()
        self.validate_unique_room_number()
        self.calculate_metrics()

    def on_update(self):
        """
        Triggered after a Room Master record is created or updated.
        Updates computed roll-up fields on the parent Block Master.
        """
        # If the block was changed, update metrics for the previous block as well
        before_save = self.get_doc_before_save()
        if before_save and before_save.block and before_save.block != self.block:
            self.update_block_metrics(before_save.block)
            
        self.update_block_metrics(self.block)

    def on_trash(self):
        """
        Triggered before a Room Master record is deleted.
        Recalculates the metrics for the parent block.
        """
        block_to_update = self.block
        # Defer execution until after deletion is committed
        frappe.db.after_commit.add(lambda: self.update_block_metrics(block_to_update))

    def fetch_camp_from_block(self):
        """
        Automatically fetch the Camp reference from the parent Block Master
        as a convenience field for filtering and reports.
        """
        if self.block:
            self.camp = frappe.db.get_value("Block Master", self.block, "camp")

    def validate_unique_room_number(self):
        """
        Ensures the Room Number is unique within the selected Block.
        (e.g., Block A cannot have two '101' rooms).
        """
        if not self.room_number or not self.block:
            return

        existing_room = frappe.db.exists(
            "Room Master",
            {
                "room_number": self.room_number,
                "block": self.block,
                "name": ("!=", self.name)
            }
        )
        
        if existing_room:
            frappe.throw(
                _("Room Number {0} already exists in {1}. Room numbers must be unique within a Block.").format(
                    frappe.bold(self.room_number), 
                    frappe.bold(self.block)
                ),
                frappe.UniqueValidationError
            )

    def calculate_metrics(self):
        """
        Calculates and syncs vacant beds and total beds.
        """
        # Count actual linked Bed Master records to enforce data integrity
        actual_bed_count = frappe.db.count("Bed Master", {"room": self.name})
        
        if actual_bed_count > 0:
            if self.total_beds != actual_bed_count:
                frappe.msgprint(_("Total Beds field has been auto-corrected to match the actual number of linked Bed Master records ({0}).").format(actual_bed_count))
                self.total_beds = actual_bed_count
                
            # Occupied beds metric is primarily driven by Bed Master/Room Allocation scripts,
            # but we perform a sanity check sync on room save.
            self.occupied_beds = frappe.db.count("Bed Master", {"room": self.name, "status": "Occupied"})
        else:
            # If no beds exist yet, ensure occupied is 0
            self.occupied_beds = 0

        # Compute vacant beds (Total Beds - Occupied Beds)
        self.vacant_beds = max(0, (self.total_beds or 0) - (self.occupied_beds or 0))

    def update_block_metrics(self, block_id):
        """
        Helper method to recalculate totals for the parent Block Master
        when a room's physical capacity or status changes.
        """
        if not block_id:
            return

        total_rooms = frappe.db.count("Room Master", {"block": block_id})
        
        # Sum up capacities and occupied metrics from all rooms in this block
        block_totals = frappe.db.get_value(
            "Room Master", 
            {"block": block_id}, 
            ["sum(total_beds)", "sum(occupied_beds)"], 
            as_dict=True
        )

        total_beds = int(block_totals.get("sum(total_beds)") or 0)
        occupied_beds = int(block_totals.get("sum(occupied_beds)") or 0)

        # Update the parent Block Master directly
        frappe.db.set_value("Block Master", block_id, {
            "total_rooms": total_rooms,
            "total_beds": total_beds,
            "occupied_beds": occupied_beds
        }, update_modified=False)

        # Cascade the update up to the Camp level to check thresholds (FR-CM-06)
        camp_id = frappe.db.get_value("Block Master", block_id, "camp")
        if camp_id:
            camp_doc = frappe.get_doc("Camp Master", camp_id)
            camp_doc.save()
