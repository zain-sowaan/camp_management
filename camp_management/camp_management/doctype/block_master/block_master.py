# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt
import frappe
from frappe import _
from frappe.model.document import Document


class BlockMaster(Document):
	def validate(self):
		"""
		Runs validations before saving the Block Master record.
		"""
		self.validate_unique_block_per_camp()
		self.calculate_metrics()
		self.set_title()

	def on_update(self):
		"""
		Triggered after a Block record is created or updated.
		Handles status propagation constraints and cascades metrics to the parent camp.
		"""
		self.propagate_status_to_rooms()
		self.update_parent_camp_metrics()

	def validate_unique_block_per_camp(self):
		"""
		Enforces a unique constraint on (camp, block_name).
		Prevents duplicate block names within the same Camp.
		"""
		if not self.camp or not self.block_name:
			return

		duplicate_block = frappe.db.exists(
			"Block Master", {"camp": self.camp, "block_name": self.block_name, "name": ("!=", self.name)}
		)

		if duplicate_block:
			frappe.throw(
				_(
					"A block named {0} already exists in {1}. Block names must be unique within a Camp."
				).format(frappe.bold(self.block_name), frappe.bold(self.camp)),
				frappe.UniqueValidationError,
			)

	def set_title(self):
		"""
		Builds a camp-qualified display title, since block_name is only unique within a
		camp (the same block name can legally repeat across different camps), so the bare
		name alone is ambiguous in dropdowns/lists once there are multiple camps.
		"""
		camp_name = frappe.db.get_value("Camp Master", self.camp, "camp_name") if self.camp else None
		if camp_name and self.block_name:
			self.block_title = f"{camp_name} / {self.block_name}"
		else:
			self.block_title = self.block_name

	def calculate_metrics(self):
		"""
		Calculates and tracks real-time roll-up metrics for Rooms and Beds.
		"""
		# Count total rooms assigned to this block
		self.total_rooms = frappe.db.count("Room Master", {"block": self.name})

		# Bed Master carries its own block reference (fetched from its Room), so beds
		# can be counted directly instead of via a raw SQL CASE/SUM aggregate, which
		# frappe.db.get_value doesn't reliably alias back out.
		self.total_beds = frappe.db.count("Bed Master", {"block": self.name})
		self.occupied_beds = frappe.db.count("Bed Master", {"block": self.name, "status": "Occupied"})

	def propagate_status_to_rooms(self):
		"""
		FR-CM-04: If the Block status is changed to 'Closed' or 'Under Maintenance',
		this workflow setting propagates the restriction by updating child Rooms.
		"""
		if self.status in ["Closed", "Under Maintenance"]:
			# Map the Block status into the respective Room Master status values
			target_room_status = "Maintenance" if self.status == "Under Maintenance" else "Closed"

			# Check if 'Closed' exists in your Room Master select choices; if it doesn't,
			# we default it to 'Maintenance' to safely prevent active allocations.
			room_status_field = frappe.get_meta("Room Master").get_field("room_status")
			room_options = room_status_field.options.split("\n") if room_status_field else []

			if target_room_status not in room_options:
				target_room_status = "Maintenance"

			# Fetch all rooms under this block that are not already matched to the status
			rooms_to_update = frappe.get_all(
				"Room Master",
				filters={"block": self.name, "room_status": ("!=", target_room_status)},
				pluck="name",
			)

			if rooms_to_update:
				for room in rooms_to_update:
					frappe.db.set_value("Room Master", room, "room_status", target_room_status)

				frappe.msgprint(
					_("Block status set to {0}. Updated {1} child room(s) to status: {2}.").format(
						frappe.bold(self.status), len(rooms_to_update), frappe.bold(target_room_status)
					)
				)

	def update_parent_camp_metrics(self):
		"""
		Cascades changes up to the Camp Master layer, ensuring camp roll-up
		summaries remain dynamically accurate and evaluating compliance against alert rules.
		"""
		if self.camp:
			camp_doc = frappe.get_doc("Camp Master", self.camp)
			camp_doc.save()
