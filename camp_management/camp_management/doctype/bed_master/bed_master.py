# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class BedMaster(Document):
	def validate(self):
		"""
		Runs validations before saving the Bed Master record.
		"""
		self.fetch_block_from_room()
		self.validate_out_of_service_role()
		self.set_title()

	def on_update(self):
		"""
		Triggered after a Bed Master record is created or updated.
		Updates computed roll-up fields across the Room, Block, and Camp hierarchy.
		"""
		# If the room was changed, update metrics for the previous room as well
		before_save = self.get_doc_before_save()
		if before_save and before_save.room and before_save.room != self.room:
			update_hierarchy_metrics(before_save.room)

		update_hierarchy_metrics(self.room)

	def on_trash(self):
		"""
		Triggered before a Bed Master record is deleted.
		Recalculates the metrics for the hierarchy so deleted beds are accounted for.
		"""
		# Use frappe.get_doc instead of self because the record is being deleted
		room_to_update = self.room

		# Defer execution to on_trash finish or use an execution hook
		frappe.db.after_commit.add(lambda: update_hierarchy_metrics(room_to_update))

	def fetch_block_from_room(self):
		"""
		FR-BM-01: Automatically fetch the Block/Wing reference from the parent Room Master
		as a convenience field.
		"""
		if self.room:
			self.block = frappe.db.get_value("Room Master", self.room, "block")

	def set_title(self):
		"""
		Builds a room-qualified display title, since bed_number is only unique within a
		room (e.g. every room has a "Bed 1"), so the bare number alone is ambiguous in
		dropdowns/lists once there are many rooms.
		"""
		room_title = frappe.db.get_value("Room Master", self.room, "room_title") if self.room else None
		if room_title and self.bed_number:
			self.bed_title = f"{room_title} / Bed {self.bed_number}"
		else:
			self.bed_title = self.bed_number

	def validate_out_of_service_role(self):
		"""
		SRS 6.3: Restrict setting the status to 'Out of Service'
		exclusively to users with the 'Camp Administrator' role.
		"""
		if self.status == "Out of Service":
			# Check if it's a new document or if the status was recently changed to Out of Service
			is_new = self.is_new()
			previous_status = frappe.db.get_value("Bed Master", self.name, "status") if not is_new else None

			if is_new or previous_status != "Out of Service":
				if "Camp Administrator" not in frappe.get_roles():
					frappe.throw(
						_(
							"Only users with the 'Camp Administrator' role are allowed to set a bed status to 'Out of Service'."
						),
						frappe.PermissionError,
					)


def update_hierarchy_metrics(room_id):
	"""
	Global helper function to cleanly recalculate and update roll-up metrics
	throughout the Room -> Block -> Camp hierarchy when a bed's status changes.
	"""
	if not room_id:
		return

	# ---------------------------------------------------------
	# 1. Update Room Master Metrics
	# ---------------------------------------------------------
	total_beds = frappe.db.count("Bed Master", {"room": room_id})
	occupied_beds = frappe.db.count("Bed Master", {"room": room_id, "status": "Occupied"})
	vacant_beds = max(0, total_beds - occupied_beds)

	frappe.db.set_value(
		"Room Master",
		room_id,
		{"total_beds": total_beds, "occupied_beds": occupied_beds, "vacant_beds": vacant_beds},
		update_modified=False,
	)

	# Fetch parent Block and Camp references
	block_id, camp_id = frappe.db.get_value("Room Master", room_id, ["block", "camp"])

	# ---------------------------------------------------------
	# 2. Update Block Master Metrics
	# ---------------------------------------------------------
	if block_id:
		total_rooms = frappe.db.count("Room Master", {"block": block_id})

		# Accumulate totals across all rooms in this block
		block_total_beds = frappe.db.count("Bed Master", {"block": block_id})
		block_occupied_beds = frappe.db.count("Bed Master", {"block": block_id, "status": "Occupied"})

		frappe.db.set_value(
			"Block Master",
			block_id,
			{
				"total_rooms": total_rooms,
				"total_beds": block_total_beds,
				"occupied_beds": block_occupied_beds,
			},
			update_modified=False,
		)

	# ---------------------------------------------------------
	# 3. Update Camp Master Metrics & Trigger Alerts
	# ---------------------------------------------------------
	if camp_id:
		# Load the Camp Master document and utilize its internal logic
		# This triggers threshold evaluations and automated manager alerts safely
		camp_doc = frappe.get_doc("Camp Master", camp_id)
		camp_doc.save()
