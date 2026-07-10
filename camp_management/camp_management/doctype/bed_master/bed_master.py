# Copyright (c) 2026, Sowaan and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document

BED_NUMBER_SUFFIX_RE = re.compile(r"^(.*?)(\d+)$")


class BedMaster(Document):
	def validate(self):
		"""
		Runs validations before saving the Bed Master record.
		"""
		self.fetch_block_from_room()
		self.validate_unique_bed_number()
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

	def validate_unique_bed_number(self):
		"""
		Ensures the Bed Number is unique within the selected Room (mirrors Room Master's
		own number-uniqueness-within-parent pattern), since two beds sharing a room and
		bed_number would collide on the same bed_title and be indistinguishable in
		dropdowns and allocations.
		"""
		if not self.bed_number or not self.room:
			return

		existing_bed = frappe.db.exists(
			"Bed Master", {"bed_number": self.bed_number, "room": self.room, "name": ("!=", self.name)}
		)

		if existing_bed:
			frappe.throw(
				_("Bed Number {0} already exists in {1}. Bed numbers must be unique within a Room.").format(
					frappe.bold(self.bed_number), frappe.bold(self.room)
				),
				frappe.UniqueValidationError,
			)

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


@frappe.whitelist()
def generate_bed_sequence(room, count, start_bed_number=None, bed_type=None):
	"""
	Bulk-creates a numbered sequence of Bed Master records for a Room, so setting up
	a room with many beds (e.g. 50) doesn't require clicking through the "New Bed
	Master" form one bed at a time. Candidate numbers are checked against beds that
	already exist in the room and skipped on a clash, so the sequence can be re-run
	to top up a room instead of failing on the first duplicate.
	"""
	frappe.has_permission("Bed Master", "create", throw=True)

	count = frappe.utils.cint(count)
	if count < 1:
		frappe.throw(_("Number of beds to generate must be at least 1."))
	if count > 200:
		frappe.throw(_("Cannot generate more than 200 beds in a single batch."))

	room_doc = frappe.db.get_value("Room Master", room, ["name", "block", "camp"], as_dict=True)
	if not room_doc:
		frappe.throw(_("Room {0} does not exist.").format(room))

	existing_numbers = set(frappe.get_all("Bed Master", filters={"room": room}, pluck="bed_number"))

	prefix, number, width = _parse_bed_number_seed(start_bed_number, existing_numbers)

	created = []
	skipped = []
	while len(created) < count:
		candidate = f"{prefix}{str(number).zfill(width)}"
		if candidate in existing_numbers:
			skipped.append(candidate)
			number += 1
			continue

		bed = frappe.get_doc(
			{
				"doctype": "Bed Master",
				"bed_number": candidate,
				"room": room_doc.name,
				"block": room_doc.block,
				"camp": room_doc.camp,
				"bed_type": bed_type,
			}
		)
		bed.insert()

		existing_numbers.add(candidate)
		created.append(candidate)
		number += 1

	return {"created": created, "skipped_existing": skipped}


def _parse_bed_number_seed(start_bed_number, existing_numbers):
	"""
	Splits a starting bed number like "B-07" into a ("B-", 7, 2) prefix/number/
	zero-padding-width tuple so the sequence keeps incrementing the numeric tail
	while preserving whatever prefix/padding style is already in use. Falls back to
	continuing after the highest existing plain-numeric bed number in the room when
	no starting value is given.
	"""
	if start_bed_number:
		match = BED_NUMBER_SUFFIX_RE.match(str(start_bed_number).strip())
		if match:
			prefix, digits = match.groups()
			width = len(digits) if digits.startswith("0") else 0
			return prefix, int(digits), width
		return str(start_bed_number).strip(), 1, 0

	highest = 0
	for value in existing_numbers:
		match = BED_NUMBER_SUFFIX_RE.match(str(value or "").strip())
		if match and not match.group(1):
			highest = max(highest, int(match.group(2)))
	return "", highest + 1, 0
